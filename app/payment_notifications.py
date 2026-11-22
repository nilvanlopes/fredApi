"""Publish administrator list and payment changes to WhatsApp."""
import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, timedelta, timezone
import logging
import os
import re
from typing import Literal
from uuid import UUID

import httpx
from sqlalchemy import case, exists, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import aliased

from app.aliases import resolve_normalized_name
from app.database import SessionLocal
from app.management import active_entries, lock
from app.message_templates import (
    LOCAL_TZ,
    monthly_subscribers_title,
    render_monthly_subscribers_message,
    render_weekly_attendance_message,
)
from app.models import Charge, MonthlySubscriber, PaymentListNotification, ProcessedConversationMessage, WeeklyAttendance
from app.parser import CHECK_MARK, EDITED_MARKER_RE, HEADER_RE, INVISIBLE_RE, ParseError, normalize_name, normalize_spaces, parse_monthly_subscribers_message, parse_weekly_attendance_message


logger = logging.getLogger(__name__)
POLL_SECONDS = 2


def _webhook_config() -> tuple[str, str] | None:
    url = os.getenv("FRED_PAYMENT_WEBHOOK_URL", "").strip()
    token = os.getenv("FRED_PAYMENT_WEBHOOK_TOKEN", "").strip()
    return (url, token) if url and token else None


def enqueue_payment_list(session, *, person_id, kind, reference: date, was_paid: bool, is_paid: bool) -> None:
    """Store the payment transition in the same transaction as the change."""
    if was_paid == is_paid or kind not in {"monthly", "single"} or _webhook_config() is None:
        return

    if kind == "monthly":
        list_type = "monthly_subscribers"
        aggregate = f"monthly:{reference:%Y-%m}"
    else:
        list_type = "weekly_attendance"
        aggregate = f"weekly:{reference.isoformat()}"
    session.add(PaymentListNotification(aggregate_key=aggregate, payload={
        "list_type": list_type,
        "reference_date": reference.isoformat(),
        "person_id": str(person_id),
        "is_paid": is_paid,
    }))


def enqueue_list_update(
    session, *, list_type: Literal["monthly_subscribers", "weekly_attendance"], reference: date,
) -> None:
    """Queue a complete list after its membership or displayed rows change."""
    if _webhook_config() is None:
        return
    if list_type == "monthly_subscribers":
        aggregate = f"monthly:{reference:%Y-%m}"
    else:
        aggregate = f"weekly:{reference.isoformat()}"
    session.add(PaymentListNotification(aggregate_key=aggregate, payload={
        "list_type": list_type,
        "reference_date": reference.isoformat(),
    }))


async def _latest_source(session, aggregate, list_type):
    message = ProcessedConversationMessage
    group_id = os.getenv("FRED_PAYMENT_WHATSAPP_CHAT_ID", "").strip()
    group_source = message.chat_id == group_id if group_id else message.chat_id.endswith("@g.us")
    order = [message.occurred_at.desc(), message.source_ordinal.desc(), message.created_at.desc(), message.id.desc()]
    if list_type == "monthly_subscribers":
        # Outgoing payment copies are recorded in history, but the original
        # announcement is the layout reference for later monthly changes.
        order.insert(0, case((message.source.in_(("waha-send", "fred-payment-list")), 1), else_=0))
    return await session.scalar(
        select(message).where(
            message.aggregate_key == aggregate,
            message.message_type == list_type,
            message.raw_text.is_not(None),
            message.status.in_(("applied", "unchanged")),
            or_(group_source, ~message.chat_id.contains("@")),
        ).order_by(*order).limit(1)
    )


async def _monthly_message(session, reference, person_id, is_paid, source):
    entries = (await session.execute(
        select(MonthlySubscriber, Charge.status).outerjoin(Charge, (
            (Charge.type == "monthly") & (Charge.reference_date == reference) &
            (Charge.person_id == MonthlySubscriber.person_id)
        )).where(
            MonthlySubscriber.month == reference.month,
            MonthlySubscriber.year == reference.year,
            MonthlySubscriber.deleted_at.is_(None),
        ).order_by(MonthlySubscriber.position)
    )).all()
    if person_id is not None and not any(entry.person_id == person_id for entry, _ in entries):
        return None
    if not entries:
        return f"{monthly_subscribers_title(reference)}\n1."

    rows = []
    for entry, charge_status in entries:
        paid = entry.has_paid if charge_status is None else charge_status == "paid"
        rows.append((entry, is_paid if person_id is not None and entry.person_id == person_id else paid))
    if source is not None:
        try:
            rewritten = await _rewrite_monthly(session, reference, rows, source)
        except ParseError:
            rewritten = None
        if rewritten is not None:
            return rewritten
    return render_monthly_subscribers_message(reference, rows)


async def _rewrite_monthly(session, reference, rows, source):
    positions = {}
    original = source.raw_text
    parsed = parse_monthly_subscribers_message(
        original, received_at=source.occurred_at.astimezone(LOCAL_TZ), line_positions=positions,
    )
    saved = {entry.position: (entry, paid) for entry, paid in rows}
    occupied = [line for line in parsed.subscribers if line.normalized_name is not None]
    if len(positions) != len(parsed.subscribers) or saved.keys() != {line.position for line in occupied}:
        return None
    content = original.splitlines()
    checks = {}
    replacements = {}
    for line in occupied:
        index = positions[line.position]
        entry, paid = saved[line.position]
        source_name = await resolve_normalized_name(session, line.normalized_name)
        if source_name != entry.normalized_name:
            replacements[index] = _replace_monthly_name(content[index], entry.name)
        checks[index] = paid

    current = parse_monthly_subscribers_message(original, received_at=datetime.now(LOCAL_TZ))
    raw_title = next(line for line in content if normalize_spaces(line))
    title = _monthly_title_without_year(raw_title, current.month, reference)
    return _rewrite_lines(original, checks, title=title, replacements=replacements)


def _monthly_title_without_year(title: str, inferred_month: int, reference: date) -> str | None:
    if inferred_month != reference.month:
        return monthly_subscribers_title(reference)
    normalized = HEADER_RE.search(normalize_name(title))
    if normalized is None or not (normalized.group(2) or normalized.group(3)):
        return None
    raw = HEADER_RE.search(title)
    if raw is not None and (raw.group(2) or raw.group(3)):
        return title[:raw.end(1)] + title[raw.end():]
    return monthly_subscribers_title(reference)


_SLOT_GAP = rf"(?:[^\S\r\n]|{INVISIBLE_RE.pattern})*"
_MONTHLY_SLOT_PREFIX = re.compile(rf"^{_SLOT_GAP}\d(?:{INVISIBLE_RE.pattern}*\d)*{_SLOT_GAP}[.\-)]?{_SLOT_GAP}")
_MONTHLY_SLOT_SUFFIX = re.compile(rf"(?:{_SLOT_GAP}{CHECK_MARK}\ufe0f?)?{_SLOT_GAP}$")


def _replace_monthly_name(line: str, name: str) -> str:
    matched = _MONTHLY_SLOT_PREFIX.match(line)
    if matched is None:
        raise ParseError("posição mensal sem prefixo no texto original")
    prefix = matched.group()
    body = line[len(prefix):]
    edit_marker = EDITED_MARKER_RE.search(body)
    end = edit_marker.start() if edit_marker else len(body)
    suffix = _MONTHLY_SLOT_SUFFIX.search(body[:end]).group() + body[end:]
    return f"{prefix}{name}{suffix}"


async def _weekly_message(session, reference, person_id, is_paid, source):
    game = await session.scalar(select(WeeklyAttendance).where(WeeklyAttendance.game_date == reference))
    if game is None:
        return None
    entries = await active_entries(session, game.id)
    if person_id is not None and not any(entry.person_id == person_id for entry in entries):
        return None
    charges = dict((await session.execute(select(Charge.person_id, Charge.status).where(
        Charge.type == "single", Charge.reference_date == reference,
    ))).all())
    if person_id is None:
        return await _render_updated_weekly(session, reference, entries, charges, source)
    charges[person_id] = "paid" if is_paid else "pending"
    if source is not None:
        try:
            rewritten = await _rewrite_weekly(session, reference, entries, charges, source)
        except ParseError:
            rewritten = None
        if rewritten is not None:
            return rewritten
    paid_ids = {identifier for identifier, status in charges.items() if status == "paid"}
    return render_weekly_attendance_message(reference, entries, paid_person_ids=paid_ids, include_year=False)


def _weekly_title_without_year(title: str, reference: date) -> str:
    pattern = re.compile(
        r"(LISTA\s+V[ÔO]LEI\s+FREDERICO\s+)\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?",
        re.IGNORECASE,
    )
    if pattern.search(title) is None:
        return f"LISTA VÔLEI FREDERICO {reference:%d/%m}"
    return pattern.sub(lambda match: f"{match.group(1)}{reference:%d/%m}", title, count=1)


def empty_weekly_list_message(reference: date) -> str:
    return f"LISTA VÔLEI FREDERICO {reference:%d/%m}\nLista sem participantes."


async def _render_updated_weekly(session, reference, entries, charges, source):
    if not entries:
        return empty_weekly_list_message(reference)

    paid_positions = defaultdict(set)
    previous_positions = defaultdict(set)
    if source is not None:
        try:
            parsed = parse_weekly_attendance_message(
                source.raw_text, received_at=source.occurred_at.astimezone(LOCAL_TZ),
            )
        except ParseError:
            pass
        else:
            if any(line.has_paid for line in parsed.entries):
                aliases = {
                    name: await resolve_normalized_name(session, name)
                    for name in {line.normalized_name for line in parsed.entries}
                }
                for line in parsed.entries:
                    key = line.section, aliases[line.normalized_name]
                    previous_positions[key].add(line.position)
                    if line.has_paid:
                        paid_positions[key].add(line.position)

    current_positions = defaultdict(set)
    for entry in entries:
        current_positions[entry.source_section, entry.normalized_name].add(entry.source_position)

    sections = {"main": [], "guests": []}
    for entry in sorted(entries, key=lambda row: row.source_position):
        name = entry.name
        inviter = (entry.invited_by or "").strip()
        if inviter:
            label = "conv" if normalize_name(inviter) == normalize_name(name) else f"conv. {inviter}"
            name = f"{name} ({label})"
        if entry.prebuilt_team_number is not None:
            team = "".join(f"{digit}\ufe0f\u20e3" for digit in str(entry.prebuilt_team_number))
            name = f"{name} {team}"
        status = charges.get(entry.person_id)
        paid = status == "paid"
        key = entry.source_section, entry.normalized_name
        if status is None and key in paid_positions:
            before, after = previous_positions[key], current_positions[key]
            # A unique name can move with its mark. Reuse positional marks for
            # repeated names only when their positions remain the same.
            paid = len(before) == len(after) == 1 or (
                before == after and entry.source_position in paid_positions[key]
            )
        if paid:
            name = f"{name} {CHECK_MARK}"
        sections[entry.source_section].append(f"{entry.source_position}. {name}")

    lines = [f"LISTA VÔLEI FREDERICO {reference:%d/%m}", *sections["main"]]
    if sections["guests"]:
        lines.extend(["", "Convidados", *sections["guests"]])
    return "\n".join(lines)


async def _rewrite_weekly(session, reference, entries, charges, source):
    positions = {}
    original = source.raw_text
    parsed = parse_weekly_attendance_message(
        original, received_at=source.occurred_at.astimezone(LOCAL_TZ), line_positions=positions,
    )
    saved = {(entry.source_section, entry.source_position): entry for entry in entries}
    if len(saved) != len(parsed.entries):
        return None
    checks = {}
    for line in parsed.entries:
        key = line.section, line.position
        stored = saved.get(key)
        if stored is None or stored.prebuilt_team_number != line.prebuilt_team_number:
            return None
        name = await resolve_normalized_name(session, line.normalized_name)
        inviter = await resolve_normalized_name(session, line.normalized_invited_by)
        stored_inviter = await resolve_normalized_name(session, stored.normalized_invited_by)
        if stored.normalized_name != name or stored_inviter != inviter:
            return None
        if stored.person_id in charges:
            checks[positions[key]] = charges[stored.person_id] == "paid"

    title = _weekly_title_without_year(parsed.title, reference)
    return _rewrite_lines(original, checks, title=title)


_PAYMENT_MARK = re.compile(rf"(?:[ \t]{CHECK_MARK}\ufe0f?(?=$|[ \t]))|{CHECK_MARK}\ufe0f?")


def _rewrite_lines(text: str, checks: dict[int, bool], *, title: str | None = None,
                   replacements: dict[int, str] | None = None) -> str:
    lines = text.splitlines(keepends=True)
    content = text.splitlines()
    if title is not None:
        index = next(index for index, line in enumerate(content) if normalize_spaces(line))
        lines[index] = title + lines[index][len(content[index]):]
    replacements = replacements or {}
    for index in checks.keys() | replacements.keys():
        line = replacements.get(index, content[index])
        paid = checks.get(index)
        if paid is True and CHECK_MARK not in line:
            marker = EDITED_MARKER_RE.search(line)
            body = (line[:marker.start()] if marker else line).rstrip()
            line = f"{body} {CHECK_MARK}{line[len(body):]}"
        elif paid is False:
            line = _PAYMENT_MARK.sub("", line)
        lines[index] = line + lines[index][len(content[index]):]
    return "".join(lines)


async def _deliver_next(client, url: str) -> bool:
    async with SessionLocal.begin() as session:
        await lock(session, "payment-list-delivery")
        notification = PaymentListNotification
        predecessor = aliased(notification)
        item = await session.scalar(select(notification).where(
            notification.delivered_at.is_(None),
            notification.next_attempt_at <= datetime.now(timezone.utc),
            ~exists().where(
                predecessor.aggregate_key == notification.aggregate_key,
                predecessor.delivered_at.is_(None),
                predecessor.id < notification.id,
            ),
        ).order_by(notification.id).limit(1))
        if item is None:
            return False

        item.attempts += 1
        try:
            # Keep a failed render from aborting the queue transaction and
            # preventing other lists from being delivered on subsequent polls.
            async with session.begin_nested():
                payload = await _webhook_payload(session, item)
            if payload is None:
                logger.info("List update %s no longer applies to %s", item.event_id, item.aggregate_key)
                item.delivered_at = datetime.now(timezone.utc)
                return True
            response = await client.post(url, json=payload)
            response.raise_for_status()
            acknowledgement = response.json()
            if not isinstance(acknowledgement, dict) or acknowledgement.get("ok") is not True:
                raise ValueError("missing n8n acknowledgement")
        except (httpx.HTTPError, SQLAlchemyError, KeyError, ValueError) as error:
            delay = min(300, 5 * 2 ** min(item.attempts - 1, 6))
            item.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            reason = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else type(error).__name__
            logger.warning("Payment list event %s will retry in %ds (%s)", item.event_id, delay, reason)
        else:
            item.delivered_at = datetime.now(timezone.utc)
        return True


async def _webhook_payload(session, item):
    list_type = item.payload["list_type"]
    reference = date.fromisoformat(item.payload["reference_date"])
    person = item.payload.get("person_id")
    person_id = UUID(person) if person is not None else None
    is_paid = item.payload.get("is_paid")
    source = await _latest_source(session, item.aggregate_key, list_type)
    render = _monthly_message if list_type == "monthly_subscribers" else _weekly_message
    text = await render(session, reference, person_id, is_paid, source)
    if text is None:
        return None
    return {
        "event_id": str(item.event_id),
        "chat_id": source.chat_id if source and source.chat_id.endswith("@g.us") else None,
        "list_type": list_type,
        "reference_date": reference.isoformat(),
        "text": text,
    }


async def _deliver_pending(url: str, token: str) -> None:
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"}, timeout=30, follow_redirects=False,
    ) as client:
        while True:
            try:
                if await _deliver_next(client, url):
                    continue
            except Exception:
                logger.exception("Unable to process the payment list outbox")
            await asyncio.sleep(POLL_SECONDS)


@asynccontextmanager
async def payment_notification_lifespan(app):
    config = _webhook_config()
    if config is None:
        yield
        return
    worker = asyncio.create_task(_deliver_pending(*config))
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
