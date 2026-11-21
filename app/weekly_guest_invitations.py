"""Correct placements and guest inviters on live WhatsApp weekly lists."""
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, time
import os
import re
from types import SimpleNamespace
from typing import Literal

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import management as d
from app.config import get_weekly_attendance_capacity
from app.aliases import resolve_normalized_name
from app.models import Charge, EntityRevision, MonthlySubscriber, Person, ProcessedConversationMessage, WeeklyAttendance, WeeklyAttendanceEntry
from app.message_templates import render_weekly_attendance_message
from app.parser import (
    CHECK_MARK, EDITED_MARKER_RE, GUEST_LABEL_RE, INVISIBLE_RE, ParsedWeeklyAttendanceLine,
    is_weekly_guest_header, normalize_name, normalize_spaces, parse_weekly_attendance_message,
)
from app.schemas import ProcessMessageRequest, WeeklyAttendanceResponse
from app.services import _weekly_entry_to_response, apply_weekly_attendance


def _is_live_group_message(payload: ProcessMessageRequest, game_date: date, received_at: datetime) -> bool:
    group = os.getenv("FRED_PAYMENT_WHATSAPP_CHAT_ID", "").strip()
    return bool(
        payload.source == "waha" and payload.chat_id and payload.chat_id.endswith("@g.us")
        and (not group or payload.chat_id == group)
        and payload.sender_id and payload.message_id and payload.message_id.startswith("false_")
        and payload.received_at and game_date >= max(d.now().astimezone(d.TZ).date(), received_at.date())
    )


async def process_live_weekly_snapshot(
    session: AsyncSession, payload: ProcessMessageRequest, occurred_at: datetime,
) -> tuple[WeeklyAttendanceResponse, Literal["applied", "stale"]]:
    positions = {}
    received_at = d.aware(occurred_at).astimezone(d.TZ)
    text = payload.text
    parsed = parse_weekly_attendance_message(text, received_at=received_at, line_positions=positions)
    numbering_corrected = parsed.numbering_corrected
    inferred = {}
    correction_notices = []
    prior_entries = []
    is_live_snapshot = _is_live_group_message(payload, parsed.game_date, received_at)
    if is_live_snapshot:
        await d.lock(session, f"weekly-date:{parsed.game_date}")
        latest = await _latest_incoming_snapshot(session, payload.chat_id, parsed.game_date)
        if latest is not None and (
            received_at < latest.occurred_at or latest.provider_message_id == payload.message_id
        ):
            return WeeklyAttendanceResponse.model_validate(latest.result), "stale"
        game_id = await session.scalar(select(WeeklyAttendance.id).where(WeeklyAttendance.game_date == parsed.game_date))
        if game_id is not None:
            await d.lock(session, f"game:{game_id}")
            prior_entries = await d.active_entries(session, game_id)
        text, correction_notices = await _move_new_non_subscribers(
            session, payload, parsed, positions, prior_entries, received_at,
            has_prior_snapshot=game_id is not None or latest is not None,
        )
        if text != payload.text:
            positions = {}
            parsed = parse_weekly_attendance_message(text, received_at=received_at, line_positions=positions)
            numbering_corrected = numbering_corrected or parsed.numbering_corrected
        parsed, inferred = await _add_inviter_to_new_guests(
            session, text, _contact_name(payload.sender_contact_name), parsed, positions, prior_entries,
        )

    result = await apply_weekly_attendance(session, parsed=parsed, received_at=received_at, commit=False)
    if inferred:
        text = _correction_text(text, positions, result, inferred) or text
    # Removals and numbering gaps must be echoed from the full persisted list.
    # The incoming text may retain stale positions or blank placeholders.
    removed_existing = False
    positions_compacted = False
    game_id = await session.scalar(select(WeeklyAttendance.id).where(WeeklyAttendance.game_date == parsed.game_date))
    if is_live_snapshot and game_id is not None:
        current_entries = (await session.scalars(select(WeeklyAttendanceEntry).where(
            WeeklyAttendanceEntry.attendance_id == game_id,
            WeeklyAttendanceEntry.deleted_at.is_(None),
        ).order_by(
            case((WeeklyAttendanceEntry.source_section == "main", 0), else_=1),
            WeeklyAttendanceEntry.source_position,
            WeeklyAttendanceEntry.display_order,
        ))).all()
        current_ids = {entry.id for entry in current_entries}
        removed_existing = bool(prior_entries) and any(entry.id not in current_ids for entry in prior_entries)
        positions_compacted = await d.compact_source_positions(session, current_entries)
        if positions_compacted or removed_existing or numbering_corrected or text != payload.text:
            # Reload after reindexing so both the API response and the published
            # correction describe the same persisted ordering.
            current_entries = (await session.scalars(select(WeeklyAttendanceEntry).where(
                WeeklyAttendanceEntry.attendance_id == game_id,
                WeeklyAttendanceEntry.deleted_at.is_(None),
            ).order_by(
                case((WeeklyAttendanceEntry.source_section == "main", 0), else_=1),
                WeeklyAttendanceEntry.source_position,
                WeeklyAttendanceEntry.display_order,
            ))).all()
            result = result.model_copy(update={
                "entries": [_weekly_entry_to_response(entry) for entry in current_entries],
            })
            paid_person_ids = set((await session.scalars(select(Charge.person_id).where(
                Charge.type == "single",
                Charge.reference_date == parsed.game_date,
                Charge.status == "paid",
            ))).all())
            accepted_paid_names = {
                await resolve_normalized_name(session, line.normalized_name)
                for line in parsed.entries if line.has_paid
            }
            for entry in current_entries:
                if entry.person_id is not None and await resolve_normalized_name(
                    session, entry.normalized_name,
                ) in accepted_paid_names:
                    paid_person_ids.add(entry.person_id)
            text = _render_persisted_weekly_entries(parsed.game_date, current_entries, paid_person_ids)
    notice = "\n".join(correction_notices) or None
    return result.model_copy(update={
        "correction_text": text if removed_existing or positions_compacted or numbering_corrected or text != payload.text else None,
        "correction_notice": notice,
    }), "applied"


def _render_persisted_weekly_entries(game_date, entries, paid_person_ids):
    """Render by persisted section and position, independent of payment status."""
    ordered = sorted(entries, key=lambda entry: (
        entry.source_section != "main", entry.source_position, entry.display_order,
    ))
    render_entries = [SimpleNamespace(
        name=entry.name,
        invited_by=entry.invited_by,
        status="main" if entry.source_section == "main" else "waiting",
        prebuilt_team_number=entry.prebuilt_team_number,
        person_id=entry.person_id,
    ) for entry in ordered]
    return render_weekly_attendance_message(
        game_date, render_entries, paid_person_ids=paid_person_ids,
    )


async def _latest_incoming_snapshot(session, chat_id, game_date):
    message = ProcessedConversationMessage
    return await session.scalar(select(message).where(
        message.chat_id == chat_id,
        message.aggregate_key == f"weekly:{game_date.isoformat()}",
        message.source == "waha",
        message.provider_message_id.startswith("false_", autoescape=True),
        message.status.in_(("applied", "unchanged")),
    ).order_by(message.occurred_at.desc(), message.created_at.desc()).limit(1))


async def _move_new_non_subscribers(
    session, payload, parsed, positions, prior_entries, received_at, *, has_prior_snapshot,
):
    # Without a prior snapshot, main-section membership cannot be classified as a new inclusion.
    if not has_prior_snapshot:
        return payload.text, []
    contact = _contact_name(payload.sender_contact_name)
    if contact is None:
        return payload.text, []
    sender = await resolve_normalized_name(session, normalize_name(contact))
    previous = {}
    for row in prior_entries:
        name = await resolve_normalized_name(session, row.normalized_name)
        previous.setdefault(name, []).append(row)
    monthly_names = set()
    monthly_entries = (await session.scalars(select(MonthlySubscriber.normalized_name).where(
        MonthlySubscriber.month == parsed.game_date.month,
        MonthlySubscriber.year == parsed.game_date.year,
        MonthlySubscriber.deleted_at.is_(None),
    ))).all()
    for monthly_name in monthly_entries:
        monthly_names.add(await resolve_normalized_name(session, monthly_name))
    candidates = []
    cutoff_at = datetime.combine(parsed.game_date, time(hour=16), tzinfo=d.TZ)
    after_cutoff = received_at >= cutoff_at
    capacity = get_weekly_attendance_capacity()
    for entry in parsed.entries:
        if entry.section != "main":
            continue
        name = await resolve_normalized_name(session, entry.normalized_name)
        old = previous.get(name, [])
        # A person already listed in the main section is not a new inclusion.
        if old and any(row.source_section == "main" for row in old):
            continue
        if len(old) > 1:
            continue
        person_id = await session.scalar(select(Person.id).where(Person.normalized_name == name))
        if name in monthly_names:
            continue
        if person_id is not None:
            revision = await session.get(EntityRevision, f"weekly:{person_id}:{parsed.game_date}")
            if revision is not None and revision.occurred_at > received_at:
                continue
        candidates.append((name, entry.invited_by or (old[0].invited_by if old else None), name == sender))

    corrected = payload.text
    correction_notices = []
    current = parsed
    main_candidates = []
    guest_candidates = candidates
    if after_cutoff:
        candidate_names = {name for name, _, _ in candidates}
        existing_main_names = [
            await resolve_normalized_name(session, entry.normalized_name)
            for entry in parsed.entries if entry.section == "main"
        ]
        existing_main_count = sum(name not in candidate_names for name in existing_main_names)
        main_slots = max(0, capacity - existing_main_count)
        main_candidates = candidates[:main_slots]
        guest_candidates = candidates[main_slots:]

    if main_candidates:
        name_set = {name for name, _, _ in main_candidates}
        corrected = await _move_main_candidates_to_end(
            session, corrected, positions, parsed, name_set,
        )
        current_positions = {}
        current = parse_weekly_attendance_message(
            corrected, received_at=received_at, line_positions=current_positions,
        )
        for name, prior_inviter, self_signed in main_candidates:
            matches = [entry for entry in current.entries if entry.section == "main"
                       and await resolve_normalized_name(session, entry.normalized_name) == name]
            if len(matches) != 1:
                continue
            current_entry = matches[0]
            inviter = prior_inviter if prior_inviter else (None if self_signed else contact)
            label = f"conv. {inviter}" if inviter else "conv"
            already_marked = current_entry.is_guest
            if not already_marked:
                source_index = current_positions["main", current_entry.position]
                corrected = _append_guest_label_at_line(corrected, source_index, label)
                correction_notices.append(
                    f"{current_entry.name} não está na lista de assinantes, identificando como convidado."
                )
            current_positions = {}
            current = parse_weekly_attendance_message(
                corrected, received_at=received_at, line_positions=current_positions,
            )

    for name, prior_inviter, self_signed in guest_candidates:
        current_positions = {}
        current = parse_weekly_attendance_message(
            corrected, received_at=received_at, line_positions=current_positions,
        )
        matches = [entry for entry in current.entries if entry.section == "main"
                   and await resolve_normalized_name(session, entry.normalized_name) == name]
        if len(matches) != 1:
            continue
        inviter = prior_inviter if prior_inviter else (None if self_signed else contact)
        corrected = _move_line_to_guests(corrected, current_positions, matches[0], inviter)
        correction_notices.append(
            f"{matches[0].name} não está na lista de assinantes, movendo para a lista de convidados."
        )
    return corrected, correction_notices


async def _move_main_candidates_to_end(session, text, positions, parsed, candidate_names):
    """Append new main-section guests after everyone already in the main queue."""
    ordered = [entry for entry in parsed.entries if entry.section == "main"]
    moving = [entry for entry in ordered if await resolve_normalized_name(session, entry.normalized_name) in candidate_names]
    if not moving:
        return text
    moved_ids = {id(entry) for entry in moving}
    reordered = [entry for entry in ordered if id(entry) not in moved_ids] + moving
    lines = text.splitlines(keepends=True)
    content = text.splitlines()
    row_indexes = [positions["main", entry.position] for entry in ordered]
    replacements = {}
    for position, (target_index, entry) in enumerate(zip(row_indexes, reordered), 1):
        source_index = positions["main", entry.position]
        source_slot = _NUMBERED_SLOT.match(content[source_index])
        if source_slot is None:
            continue
        body = content[source_index][source_slot.end():]
        newline = lines[target_index][len(content[target_index]):]
        replacements[target_index] = f"{position}. {body}{newline}"
    for index, value in replacements.items():
        lines[index] = value
    return "".join(lines)


def _append_guest_label_at_line(text: str, line_index: int, label: str) -> str:
    lines = text.splitlines(keepends=True)
    content = text.splitlines()
    lines[line_index] = _append_guest_label(content[line_index], label) + lines[line_index][len(content[line_index]):]
    return "".join(lines)


def _move_line_to_guests(
    text: str,
    positions: dict[tuple[str, int], int],
    entry: ParsedWeeklyAttendanceLine,
    prior_inviter: str | None,
) -> str:
    lines = text.splitlines(keepends=True)
    content = text.splitlines()
    index = positions[entry.section, entry.position]
    slot = _NUMBERED_SLOT.match(content[index])
    if slot is None:
        return text
    body = content[index][slot.end():]
    newline = lines[index][len(content[index]):]
    lines[index] = content[index][:slot.end()].rstrip() + newline
    newline = newline or "\n"
    if entry.invited_by is None and not entry.is_guest:
        label = f"conv. {prior_inviter}" if prior_inviter else "conv"
        body = _append_guest_label(body, label, replace_guest_label=True)

    guest_headers = [i for i, line in enumerate(content) if is_weekly_guest_header(line)]
    guests = {position: i for (section, position), i in positions.items() if section == "guests"}
    next_position = max(guests, default=0) + 1
    new_line = f"{next_position}. {body}"
    if guest_headers:
        last_guest = max(guest_headers[-1], max(guests.values(), default=-1))
        for i in range(last_guest + 1, len(content)):
            placeholder = _NUMBERED_SLOT.fullmatch(content[i])
            if placeholder and int(INVISIBLE_RE.sub("", placeholder.group("number"))) == next_position:
                lines[i] = f"{content[i].rstrip()} {body}{lines[i][len(content[i]):]}"
                return "".join(lines)
        insert_at = last_guest + 1
    else:
        insert_at = len(lines)
        while insert_at > 0 and not normalize_spaces(content[insert_at - 1]):
            insert_at -= 1
        new_line = f"{newline}Convidados{newline}{new_line}"
    separator = "" if len(lines[insert_at - 1]) > len(content[insert_at - 1]) else newline
    suffix = newline if insert_at < len(lines) or len(lines[-1]) > len(content[-1]) else ""
    lines.insert(insert_at, f"{separator}{new_line}{suffix}")
    return "".join(lines)


async def _add_inviter_to_new_guests(session, text, contact, parsed, positions, prior_entries):
    if not prior_entries:
        return parsed, {}

    names = [await resolve_normalized_name(session, entry.normalized_name) for entry in parsed.entries]
    counts = Counter(names)
    previous = {}
    for entry in prior_entries:
        name = await resolve_normalized_name(session, entry.normalized_name)
        previous.setdefault(name, []).append(entry)

    content = text.splitlines()
    entries = []
    inferred = {}
    for entry, name in zip(parsed.entries, names):
        index = positions[entry.section, entry.position]
        if (entry.invited_by or counts[name] > 1 or _EXPLICIT_INVITER.search(content[index])
                or GUEST_LABEL_RE.search(content[index])):
            entries.append(entry)
            continue
        old = previous.get(name)
        inviter = old[0].invited_by if old and len(old) == 1 else None
        if old is None and entry.section == "guests" and contact:
            inviter = contact
            inferred[entry.section, entry.position] = (entry.name, inviter)
        entries.append(replace(entry, invited_by=inviter, normalized_invited_by=normalize_name(inviter)) if inviter else entry)

    return replace(parsed, entries=entries), inferred


def _correction_text(text, positions, result, inferred):
    lines = text.splitlines(keepends=True)
    content = text.splitlines()
    corrected = False
    for entry in result.entries:
        key = entry.section, entry.position
        if inferred.get(key) != (entry.name, entry.invited_by):
            continue
        index = positions[key]
        lines[index] = _append_inviter(content[index], entry.invited_by) + lines[index][len(content[index]):]
        corrected = True
    return "".join(lines) if corrected else None


_EXPLICIT_INVITER = re.compile(r"\(\s*(?:conv\s*[.:=-]|convidad[oa]\s+por\b)", re.IGNORECASE)
_GAP = rf"(?:[^\S\r\n]|{INVISIBLE_RE.pattern})*"
_NUMBERED_SLOT = re.compile(rf"^{_GAP}(?P<number>\d(?:{INVISIBLE_RE.pattern}*\d)*){_GAP}[.\-)]?{_GAP}")
_TRAILING_FLAGS = re.compile(rf"(?:{_GAP}(?:{CHECK_MARK}\ufe0f?|[1-9]\ufe0f?\u20e3))+{_GAP}$")


def _contact_name(value: str | None) -> str | None:
    if not value or len(value) > 100 or len(value.splitlines()) != 1 or any(char in value for char in ("(", ")", CHECK_MARK)):
        return None
    name = normalize_spaces(value)
    return name if any(char.isalpha() for char in name) else None


def _append_inviter(line: str, inviter: str) -> str:
    return _append_guest_label(line, f"conv. {inviter}")


def _append_guest_label(line: str, label: str, *, replace_guest_label=False) -> str:
    edited = EDITED_MARKER_RE.search(line)
    end = edited.start() if edited else len(line)
    flags = _TRAILING_FLAGS.search(line[:end])
    start = flags.start() if flags else len(line[:end].rstrip())
    name = line[:start]
    if replace_guest_label:
        name = GUEST_LABEL_RE.sub("", name).rstrip()
    return f"{name} ({label}){line[start:]}"
