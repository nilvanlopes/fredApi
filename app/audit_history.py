"""Semantic audit events for accepted WhatsApp list snapshots."""
from datetime import date

from sqlalchemy import select

from app import management as d
from app.aliases import resolve_normalized_name
from app.models import AuditEvent, Person, ProcessedConversationMessage
from app.parser import normalize_name, parse_monthly_subscribers_message, parse_weekly_attendance_message


async def record_list_history(session, *, message_id, message_type: str, chat_id: str,
                              aggregate_key: str, text: str, occurred_at, status: str,
                              sender_contact_name: str | None = None,
                              sender_name: str | None = None,
                              semantic_text: str | None = None):
    """Record semantic diffs for one accepted incoming WhatsApp snapshot.

    Outgoing sends and technical/rejected events deliberately stay outside this history.
    """
    if status not in {"applied", "unchanged"} or message_type not in {"monthly_subscribers", "weekly_attendance"}:
        return None
    current = await session.get(ProcessedConversationMessage, message_id)
    if current is None or current.source in {"waha-send", "fred-payment-list"}:
        return None
    previous = await session.scalar(select(ProcessedConversationMessage).where(
        ProcessedConversationMessage.chat_id == chat_id,
        ProcessedConversationMessage.aggregate_key == aggregate_key,
        ProcessedConversationMessage.id != message_id,
        ProcessedConversationMessage.status.in_(("applied", "unchanged")),
        ProcessedConversationMessage.raw_text.is_not(None),
    ).order_by(ProcessedConversationMessage.occurred_at.desc(),
               ProcessedConversationMessage.source_ordinal.desc(),
               ProcessedConversationMessage.created_at.desc()).limit(1))
    if previous and (previous.occurred_at, previous.source_ordinal) >= (current.occurred_at, current.source_ordinal):
        return None
    effective_text = semantic_text or text
    if message_type == "monthly_subscribers":
        changes, ids = await _monthly_diff(session, previous.raw_text if previous else None, effective_text, occurred_at)
    else:
        previous_semantic_text = None
        if previous is not None:
            old_event = await session.scalar(select(AuditEvent).where(
                AuditEvent.action == "list_change",
                AuditEvent.entity_type == "whatsapp_list",
                AuditEvent.after["message_id"].as_string() == str(previous.id),
            ).order_by(AuditEvent.recorded_at.desc()).limit(1))
            previous_semantic_text = (old_event.after.get("message_diff", {}).get("effective_text")
                                      if old_event is not None else None)
        changes, ids = await _weekly_diff(
            session, previous_semantic_text or (previous.raw_text if previous else None),
            effective_text, occurred_at,
        )
    # A first snapshot is a useful baseline, but without a predecessor it does
    # not establish that every listed person was added by this message.
    actor_id = None
    actor = None
    for candidate in (sender_contact_name, sender_name):
        if not candidate:
            continue
        normalized = await resolve_normalized_name(session, normalize_name(candidate))
        matches = (await session.scalars(select(Person).where(Person.normalized_name == normalized))).all()
        if len(matches) == 1:
            actor = matches[0]
            actor_id = actor.id
            break
    if actor_id:
        for change in changes:
            for person in change["people"]:
                if person["id"] == str(actor_id):
                    person["is_actor"] = True
    event = AuditEvent(occurred_at=d.aware(occurred_at),
        actor_name=sender_contact_name or sender_name or (actor.name if actor else "WhatsApp"),
        source="whatsapp", action="list_change", entity_type="whatsapp_list", entity_id=aggregate_key,
        person_id=None, before={"message_id": str(previous.id) if previous else None},
        after={"message_id": str(current.id), "previous_message_id": str(previous.id) if previous else None,
               "changes": changes, "participant_ids": sorted(ids),
               "message_diff": {"before_text": previous.raw_text if previous else None,
                                "after_text": current.raw_text,
                                "effective_text": effective_text}})
    session.add(event)
    return event


async def _resolve_id(session, normalized):
    normalized = await resolve_normalized_name(session, normalized)
    return await session.scalar(select(Person.id).where(Person.normalized_name == normalized))


async def _monthly_diff(session, old_text, new_text, occurred_at):
    current = parse_monthly_subscribers_message(new_text, received_at=occurred_at)
    old = parse_monthly_subscribers_message(old_text, received_at=occurred_at) if old_text else None
    # Position is presentation only; moving a person within the list is not a
    # membership change. Resolve aliases before comparing the two snapshots.
    before, after = {}, {}
    if old:
        for line in old.subscribers:
            if line.normalized_name:
                key = await resolve_normalized_name(session, line.normalized_name)
                before.setdefault(key, line)
    for line in current.subscribers:
        if line.normalized_name:
            key = await resolve_normalized_name(session, line.normalized_name)
            after.setdefault(key, line)
    changes, ids = [], set()
    ref = date(current.year, current.month, 1).isoformat()
    async def append(kind, line, previous_name=None):
        person_id = await _resolve_id(session, line.normalized_name)
        if person_id is None: return
        changes.append({"kind": kind, "people": [{"id": str(person_id), "name": line.name}],
                        "reference_date": ref, **({"previous_name": previous_name} if previous_name else {})})
        ids.add(str(person_id))
    for name in sorted(set(before) | set(after)):
        old_line, new_line = before.get(name), after.get(name)
        if old_line and not new_line:
            await append("subscription_removed", old_line)
        if new_line and not old_line:
            if old is not None:
                await append("subscription_added", new_line)
            if new_line.has_paid:
                await append("monthly_paid", new_line)
        if old_line and new_line and old_line.has_paid != new_line.has_paid and new_line.has_paid:
            await append("monthly_paid", new_line)
    return changes, ids


async def _weekly_diff(session, old_text, new_text, occurred_at):
    current = parse_weekly_attendance_message(new_text, received_at=occurred_at)
    old = parse_weekly_attendance_message(old_text, received_at=occurred_at) if old_text else None
    async def keyed(parsed):
        result = {}
        if parsed is not None:
            for line in parsed.entries:
                canonical = await resolve_normalized_name(session, line.normalized_name)
                result.setdefault(canonical, line)
        return result
    before, after = await keyed(old), await keyed(current)
    changes, ids = [], set()
    ref = current.game_date.isoformat()
    async def append(kind, line):
        person_id = await _resolve_id(session, line.normalized_name)
        if person_id is None: return
        changes.append({"kind": kind, "people": [{"id": str(person_id), "name": line.name}], "reference_date": ref})
        ids.add(str(person_id))
    for name in sorted(set(before) | set(after)):
        a, b = before.get(name), after.get(name)
        a_kind = "guest" if a and a.is_guest else "weekly"
        b_kind = "guest" if b and b.is_guest else "weekly"
        if a and (not b or a_kind != b_kind): await append(f"{a_kind}_removed", a)
        if b and (not a or a_kind != b_kind):
            if old is not None:
                await append(f"{b_kind}_added", b)
            if b.is_guest and b.has_paid:
                await append("guest_paid", b)
        if a and b and b.is_guest and a.has_paid != b.has_paid and b.has_paid:
            await append("guest_paid", b)
    return changes, ids
