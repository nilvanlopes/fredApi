"""Management domain. All writes share revisions, durable charges and audit."""
from collections.abc import Collection
from datetime import date, datetime, time, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func, text, case, or_, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.aliases import resolve_normalized_name
from app.models import (Person, PersonAlias, FredAccount, MonthlySubscriber, WeeklyAttendance,
                        WeeklyAttendanceEntry, Charge, AuditEvent, EntityRevision)
from app.parser import normalize_name

TZ = ZoneInfo("America/Sao_Paulo")
MONTHLY_COVERAGE_REASON = "Coberto pela mensalidade paga no mesmo mês"
WHATSAPP_SNAPSHOT_REMOVAL_REASON = "Ausente na lista semanal do WhatsApp"
WHATSAPP_SNAPSHOT_CAPACITY_REASON = "Fora das vagas cobráveis na lista semanal do WhatsApp"
WHATSAPP_SNAPSHOT_PAID_REASON = "Pagamento confirmado na lista semanal do WhatsApp"


def now():
    return datetime.now(timezone.utc)


def aware(value=None):
    value = value or now()
    return value.replace(tzinfo=TZ) if value.tzinfo is None else value


def starts(game):
    return game.starts_at or datetime.combine(game.game_date, time(19, 30), TZ)


def ensure_open(game, at=None):
    if aware(at) >= starts(game):
        raise HTTPException(409, "As inscrições e saídas encerraram no início da partida.")


async def lock(session, key):
    # A single transaction lock also serializes first insertion of a revision.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})


async def touch_account(session, user):
    account = await session.get(FredAccount, user["uid"])
    if account is None:
        account = FredAccount(uid=user["uid"], username=user["username"], name=user.get("name") or user["username"], email=user.get("email") or "", is_admin=bool(user.get("is_admin")))
        session.add(account)
    else:
        account.username = user["username"]
        account.name = user.get("name") or user["username"]
        account.email = user.get("email") or ""
        if user.get("is_admin"):
            account.is_admin = True
    await session.flush()
    return account


async def person_for_name(session, name):
    normalized = await resolve_normalized_name(session, normalize_name(name))
    if not normalized:
        raise HTTPException(422, "Nome inválido")
    person = await session.scalar(select(Person).where(Person.normalized_name == normalized))
    if person is None:
        person = Person(name=name.strip(), normalized_name=normalized, active=True)
        session.add(person)
        await session.flush()
    return person


async def get_or_404(session, model, identifier):
    row = await session.get(model, identifier)
    if row is None:
        raise HTTPException(404, "Registro não encontrado")
    return row


async def merge_people(session: AsyncSession, source_id: UUID, target_id: UUID, *, user: dict) -> None:
    if source_id == target_id:
        raise HTTPException(422, "Escolha outro jogador para receber os registros.")

    await lock(session, "merge-people")
    person_ids = (source_id, target_id)
    people = {person.id: person for person in (await session.scalars(
        select(Person).where(Person.id.in_(person_ids)).order_by(Person.id).with_for_update()
    )).all()}
    if len(people) != 2:
        raise HTTPException(404, "Um dos cadastros de jogador não foi encontrado.")
    source, target = people[source_id], people[target_id]
    if not target.active:
        raise HTTPException(409, "Escolha um jogador ativo para receber os registros.")

    # A merge must not silently discard a public profile or its evaluations.
    from app.models import PersonProfile, PlayerRating
    if await session.get(PersonProfile, source_id) is not None or await session.scalar(
        select(PlayerRating.id).where(or_(PlayerRating.evaluator_person_id == source_id,
                                         PlayerRating.target_person_id == source_id)).limit(1)
    ) is not None:
        raise HTTPException(409, "O jogador de origem tem perfil ou avaliações. A união exige revisão desses dados para preservá-los.")

    try:
        source_name = await resolve_normalized_name(session, source.normalized_name)
        target_name = await resolve_normalized_name(session, target.normalized_name)
    except ValueError as exc:
        raise HTTPException(409, "Há um conflito nos apelidos destes jogadores.") from exc
    if target_name != target.normalized_name or source_name not in {source.normalized_name, target_name}:
        raise HTTPException(409, "Um dos nomes já é apelido de outro jogador. Revise os apelidos antes de unir os cadastros.")

    async def records(model):
        return (await session.scalars(select(model).where(model.person_id.in_(person_ids)).with_for_update())).all()

    accounts = await records(FredAccount)
    if len(accounts) > 1:
        raise HTTPException(409, "Os dois jogadores têm contas vinculadas. Desvincule a conta duplicada antes de unir os cadastros.")
    monthly = await records(MonthlySubscriber)
    weekly = await records(WeeklyAttendanceEntry)
    charges = await records(Charge)

    def overlaps(rows, key):
        return {key(row) for row in rows if row.person_id == source_id} & {key(row) for row in rows if row.person_id == target_id}

    monthly_overlap = overlaps([row for row in monthly if row.deleted_at is None], lambda row: (row.year, row.month))
    if monthly_overlap:
        year, month = min(monthly_overlap)
        raise HTTPException(409, f"Os dois jogadores têm mensalidade ativa em {month:02d}/{year}. Revise a lista do mês antes de unir os cadastros.")
    weekly_overlap = overlaps([row for row in weekly if row.deleted_at is None], lambda row: row.attendance_id)
    if weekly_overlap:
        game_date = await session.scalar(select(func.min(WeeklyAttendance.game_date)).where(WeeklyAttendance.id.in_(weekly_overlap)))
        raise HTTPException(409, f"Os dois jogadores têm inscrição ativa em {game_date:%d/%m/%Y}. Revise a lista da partida antes de unir os cadastros.")
    charge_overlap = overlaps(charges, lambda row: (row.reference_date, row.type))
    if charge_overlap:
        reference, kind = min(charge_overlap)
        label = "mensalidade" if kind == "monthly" else "convidado"
        raise HTTPException(409, f"Os dois jogadores têm cobrança de {label} com referência em {reference:%d/%m/%Y}. Os cadastros não podem ser unidos enquanto houver cobranças sobrepostas.")

    aliases = (await session.scalars(select(PersonAlias).where(or_(
        PersonAlias.alias_normalized == source.normalized_name,
        PersonAlias.canonical_normalized == source.normalized_name,
    )).with_for_update())).all()
    old_names = {source.normalized_name, *(alias.alias_normalized for alias in aliases)}
    for alias in aliases:
        alias.canonical_name = target.name
        alias.canonical_normalized = target.normalized_name
    if not any(alias.alias_normalized == source.normalized_name for alias in aliases):
        session.add(PersonAlias(
            alias=source.name if normalize_name(source.name) == source.normalized_name else source.normalized_name,
            alias_normalized=source.normalized_name, canonical_name=target.name,
            canonical_normalized=target.normalized_name,
        ))

    moved_games = {row.attendance_id for row in weekly if row.person_id == source_id and row.deleted_at is None}
    moved_months = {(row.year, row.month) for row in monthly if row.person_id == source_id and row.deleted_at is None}
    moved_months.update((charge.reference_date.year, charge.reference_date.month)
                        for charge in charges if charge.person_id == source_id and charge.type == "monthly")
    moved = {}
    for label, rows in (("monthly", monthly), ("weekly", weekly), ("charges", charges), ("accounts", accounts)):
        moved[label] = 0
        for row in rows:
            if row.person_id != source_id:
                continue
            row.person_id = target_id
            if isinstance(row, (MonthlySubscriber, WeeklyAttendanceEntry)):
                row.name = target.name
                row.normalized_name = target.normalized_name
            moved[label] += 1

    await session.execute(update(WeeklyAttendanceEntry).where(WeeklyAttendanceEntry.normalized_invited_by.in_(old_names)).values(normalized_invited_by=target.normalized_name))
    await session.execute(update(AuditEvent).where(AuditEvent.person_id == source_id).values(person_id=target_id))

    # Keep the most recent change per period, so imports that were stale
    # for either name are still stale once the records share an identity.
    prefixes = ("monthly", "weekly", "charge")
    revisions = (await session.scalars(select(EntityRevision).where(or_(*(
        EntityRevision.key.like(f"{prefix}:{person_id}:%")
        for prefix in prefixes for person_id in person_ids
    ))).with_for_update())).all()
    by_key = {revision.key: revision for revision in revisions}
    for revision in revisions:
        prefix, person_id, reference = revision.key.split(":", 2)
        if person_id != str(source_id):
            continue
        key = f"{prefix}:{target_id}:{reference}"
        current = by_key.get(key)
        if current is None:
            session.add(EntityRevision(key=key, occurred_at=revision.occurred_at))
        else:
            current.occurred_at = max(current.occurred_at, revision.occurred_at)
        await session.delete(revision)

    await audit(session, entity_type="person", entity_id=source_id, action="merge", user=user, person_id=target_id,
                before={"id": source_id, "name": source.name}, after={"id": target_id, "name": target.name, "moved": moved})
    await session.flush()
    await session.delete(source)
    await refresh_identity_games(session, {target_id}, game_ids=moved_games, months=moved_months, user=user)


async def audit(session, *, entity_type, entity_id, action, user=None, person_id=None,
                before=None, after=None, occurred_at=None, source="panel", status="applied"):
    row = AuditEvent(occurred_at=aware(occurred_at), actor_uid=(user or {}).get("uid"),
                     actor_name=(user or {}).get("name") or (user or {}).get("username") or source,
                     source=source, action=action, entity_type=entity_type, entity_id=str(entity_id),
                     person_id=person_id, before=jsonable_encoder(before or {}), after=jsonable_encoder(after or {}), status=status)
    session.add(row)
    return row


async def revision(session, key, occurred_at, **event):
    await lock(session, key)
    timestamp = aware(occurred_at)
    current = await session.get(EntityRevision, key)
    if current is not None and timestamp < current.occurred_at:
        await audit(session, occurred_at=timestamp, status="stale", **event)
        return False
    if current is None:
        session.add(EntityRevision(key=key, occurred_at=timestamp))
    else:
        current.occurred_at = timestamp
    return True


async def set_charge(session, person_id, kind, reference_date, *, status=None, amount=None,
                     user=None, occurred_at=None, source="panel", reason=""):
    key = f"charge:{person_id}:{kind}:{reference_date}"
    await lock(session, key)
    charge = await session.scalar(select(Charge).where(Charge.person_id == person_id, Charge.type == kind, Charge.reference_date == reference_date))
    # No implicit paid->pending reset during a capacity recalculation.
    before = charge_dict(charge) if charge else {}
    if charge is None:
        charge = Charge(person_id=person_id, type=kind, reference_date=reference_date,
                        amount_cents=amount if amount is not None else (1250 if kind == "monthly" else 750), status="pending")
        session.add(charge)
        await session.flush()
    if status is not None or amount is not None:
        event = dict(entity_type="charge", entity_id=charge.id, action="update", user=user,
                     person_id=person_id, source=source, before=before, after={"status":status,"amount_cents":amount,"reason":reason})
        if not await revision(session, key, occurred_at, **event):
            return charge
        if status == "waived":
            if not reason.strip():
                raise HTTPException(422,"Informe o motivo da dispensa de pagamento")
            if charge.status not in {"pending","waived"}:
                raise HTTPException(409,"Somente cobranças pendentes podem ser dispensadas. Reverta o pagamento antes.")
        if status is not None:
            charge.status = status
            if status == "paid" and charge.paid_at is None:
                charge.paid_at = aware(occurred_at)
            elif status == "pending":
                charge.paid_at = None
        if amount is not None:
            charge.amount_cents = amount
        await audit(session, occurred_at=occurred_at, **{**event,"after":{**charge_dict(charge),"reason":reason}})
    elif not before:
        await audit(session, entity_type="charge", entity_id=charge.id, action="create", user=user, person_id=person_id, source=source, occurred_at=occurred_at, after=charge_dict(charge))
    return charge


def charge_dict(row, name=None):
    result = {key:getattr(row,key) for key in ("id","person_id","type","reference_date","amount_cents","status","paid_at")}
    if name is not None:
        result["name"] = name
    return result


async def active_entries(session, game_id):
    return list((await session.scalars(select(WeeklyAttendanceEntry).where(WeeklyAttendanceEntry.attendance_id == game_id, WeeklyAttendanceEntry.deleted_at.is_(None)).order_by(WeeklyAttendanceEntry.display_order))).all())


async def compact_source_positions(session, entries) -> bool:
    grouped = {"main": [], "guests": []}
    for entry in entries:
        grouped[entry.source_section].append(entry)
    for section in grouped:
        grouped[section].sort(key=lambda item: (item.source_position, item.display_order))
    changed = any(
        entry.source_position != position
        for section_entries in grouped.values()
        for position, entry in enumerate(section_entries, 1)
    )
    if not changed:
        return False

    # Move active rows out of the compact range before reassigning positions
    # to preserve the partial unique index during both flushes.
    offset = max((entry.source_position for entry in entries), default=0) + len(entries)
    for index, entry in enumerate(entries, 1):
        entry.source_position = offset + index
    await session.flush()
    for section_entries in grouped.values():
        for position, entry in enumerate(section_entries, 1):
            entry.source_position = position
    await session.flush()
    return True


async def cancelled_by_monthly_coverage(session, charge):
    latest_change = await session.scalar(select(AuditEvent.after).where(
        AuditEvent.entity_type == "charge",
        AuditEvent.entity_id == str(charge.id),
        AuditEvent.action == "update",
        AuditEvent.status == "applied",
        AuditEvent.before["status"].as_string() != AuditEvent.after["status"].as_string(),
    ).order_by(AuditEvent.recorded_at.desc(), AuditEvent.occurred_at.desc()).limit(1))
    return bool(latest_change and latest_change.get("reason") == MONTHLY_COVERAGE_REASON)


async def cancelled_by_weekly_snapshot(session, charge):
    latest = (await session.execute(select(AuditEvent.source, AuditEvent.after).where(
        AuditEvent.entity_type == "charge",
        AuditEvent.entity_id == str(charge.id),
        AuditEvent.action == "update",
        AuditEvent.status == "applied",
        AuditEvent.before["status"].as_string() != AuditEvent.after["status"].as_string(),
    ).order_by(AuditEvent.recorded_at.desc(), AuditEvent.occurred_at.desc()).limit(1))).first()
    if latest is None or latest.source != "whatsapp":
        return False
    return latest.after.get("reason") in {
        "Saída antes do início",
        "Sem vaga principal ou coberto pela mensalidade",
        WHATSAPP_SNAPSHOT_REMOVAL_REASON,
        WHATSAPP_SNAPSHOT_CAPACITY_REASON,
    }


async def reconcile_weekly_snapshot_charges(
    session, game, *, occurred_at, source="whatsapp", paid_person_ids: Collection[UUID] = (),
):
    """Reconcile single-game charges against the accepted WhatsApp list snapshot.

    The date in the message identifies the game, so a late snapshot still
    updates pending charges for that game. Revisions of the entry and charge
    reject older snapshots. A payment marker confirms payment and an unmarked
    line leaves an existing paid state intact.
    """
    timestamp = aware(occurred_at)
    entries = await active_entries(session, game.id)
    active_person_ids = {entry.person_id for entry in entries}
    billable_entries: dict[UUID, list[WeeklyAttendanceEntry]] = {}
    for entry in entries:
        if entry.person_id is not None and entry.status == "main" and not entry.is_monthly_subscriber:
            billable_entries.setdefault(entry.person_id, []).append(entry)
    charges = (await session.scalars(select(Charge).where(
        Charge.type == "single",
        Charge.reference_date == game.game_date,
    ))).all()
    for charge in charges:
        revision_keys = (
            f"weekly:{charge.person_id}:{game.game_date}",
            f"charge:{charge.person_id}:{charge.type}:{game.game_date}",
        )
        newer_revision = await session.scalar(select(EntityRevision.key).where(
            EntityRevision.key.in_(revision_keys), EntityRevision.occurred_at > timestamp,
        ).limit(1))
        if newer_revision is not None:
            continue
        if charge.person_id in billable_entries:
            marked_paid = charge.person_id in paid_person_ids
            if marked_paid and charge.status != "paid":
                new_status = "paid"
            elif charge.status == "cancelled" and (
                await cancelled_by_monthly_coverage(session, charge)
                or await cancelled_by_weekly_snapshot(session, charge)
            ):
                new_status = "paid" if charge.paid_at is not None else "pending"
            else:
                continue
            reason = (
                WHATSAPP_SNAPSHOT_PAID_REASON if marked_paid
                else "Presente em vaga cobrável no snapshot semanal"
            )
            updated_charge = await set_charge(
                session,
                charge.person_id,
                "single",
                game.game_date,
                status=new_status,
                occurred_at=timestamp,
                source=source,
                reason=reason,
            )
            for entry in billable_entries[charge.person_id]:
                entry.owes_single_payment = updated_charge.status == "pending"
        elif charge.status == "pending":
            reason = (
                WHATSAPP_SNAPSHOT_CAPACITY_REASON
                if charge.person_id in active_person_ids
                else WHATSAPP_SNAPSHOT_REMOVAL_REASON
            )
            await set_charge(
                session,
                charge.person_id,
                "single",
                game.game_date,
                status="cancelled",
                occurred_at=timestamp,
                source=source,
                reason=reason,
            )


async def paid_monthly_person_ids(session, game_date):
    return set((await session.scalars(
        select(MonthlySubscriber.person_id)
        .join(Charge, (Charge.person_id == MonthlySubscriber.person_id)
              & (Charge.type == "monthly")
              & (Charge.reference_date == game_date.replace(day=1))
              & (Charge.status == "paid"))
        .where(
            MonthlySubscriber.month == game_date.month,
            MonthlySubscriber.year == game_date.year,
            MonthlySubscriber.deleted_at.is_(None),
        )
    )).all())


async def recalculate(
    session, game, at=None, user=None, source="panel", *, historical_person_ids=None,
    defer_snapshot_charges=False,
):
    timestamp = max(aware(at), now())
    # Reads may catch up an open list; historical games are frozen unless an
    # explicit command supplied its event time.
    if at is None and timestamp >= starts(game):
        return
    await lock(session, f"game:{game.id}")
    entries = await active_entries(session, game.id)
    monthly_ids = await paid_monthly_person_ids(session, game.game_date)
    before_cutoff = timestamp < game.cutoff_at
    # display_order is the current authoritative queue. WhatsApp snapshots can
    # reorder existing entries without changing joined_at, so timestamps would
    # silently undo the latest list order at cutoff or after a vacancy.
    ordered = sorted(entries, key=lambda e:(e.display_order, str(e.id)))
    if before_cutoff:
        eligible = [e for e in ordered if e.person_id in monthly_ids]
    else:
        # Preserve confirmed players; newly freed slots go to waiting players in FIFO.
        eligible = [e for e in ordered if e.status == "main"] + [e for e in ordered if e.status != "main"]
    preserve_allocation = historical_person_ids is not None and timestamp >= starts(game)
    accepted = {e.id for e in entries if e.status == "main"} if preserve_allocation else {e.id for e in eligible[:game.capacity]}
    billable_people={e.person_id for e in entries if e.id in accepted and e.person_id not in monthly_ids}
    for index, entry in enumerate(ordered, 1):
        if preserve_allocation and entry.person_id not in historical_person_ids:
            continue
        old_status=entry.status
        if not preserve_allocation:
            entry.display_order = index
        entry.is_monthly_subscriber = entry.person_id in monthly_ids
        entry.status = "main" if entry.id in accepted else "waiting"
        charge = await session.scalar(select(Charge).where(Charge.person_id == entry.person_id, Charge.type == "single", Charge.reference_date == game.game_date))
        if entry.status == "main" and not entry.is_monthly_subscriber:
            charge = await set_charge(session, entry.person_id, "single", game.game_date, user=user, occurred_at=timestamp, source=source)
            # WhatsApp decides whether to restore a charge after applying the full list.
            if charge.status == "cancelled" and not defer_snapshot_charges and (
                timestamp < starts(game) or (preserve_allocation and await cancelled_by_monthly_coverage(session, charge))
            ):
                charge = await set_charge(session, entry.person_id, "single", game.game_date, status="paid" if charge.paid_at is not None else "pending", user=user, occurred_at=timestamp, source=source)
        elif entry.is_monthly_subscriber and charge is not None and charge.status in {"pending", "paid"}:
            # A paid monthly subscription covers every avulso in that same
            # calendar month, including charges for games already played.
            charge = await set_charge(session,entry.person_id,"single",game.game_date,status="cancelled",user=user,occurred_at=timestamp,source=source,reason=MONTHLY_COVERAGE_REASON)
        elif not defer_snapshot_charges and not entry.is_monthly_subscriber and charge is not None and entry.person_id not in billable_people and charge.status not in {"cancelled","waived"} and timestamp < starts(game):
            charge = await set_charge(session,entry.person_id,"single",game.game_date,status="cancelled",user=user,occurred_at=timestamp,source=source,reason="Sem vaga principal ou coberto pela mensalidade")
        entry.owes_single_payment = bool(charge and charge.status == "pending" and not entry.is_monthly_subscriber and entry.status == "main")
        entry.single_payment_amount_cents = charge.amount_cents if charge else None
        if old_status != entry.status:
            await audit(session,entity_type="weekly",entity_id=game.id,action="allocation",user=user,person_id=entry.person_id,source=source,occurred_at=timestamp,before={"status":old_status},after={"status":entry.status,"game_date":game.game_date})
    await session.flush()


async def replace_entry_player(session, game, entry, player, *, user):
    """Correct the identity attached to one weekly row and its avulso."""
    source_id = entry.person_id
    if source_id == player.id:
        return
    if not player.active:
        raise HTTPException(409, "Escolha um jogador ativo.")

    entries = await active_entries(session, game.id)
    if any(other.person_id == player.id for other in entries):
        raise HTTPException(409, "Este jogador já está na lista da partida.")

    person_ids = {player.id}
    if source_id is not None:
        person_ids.add(source_id)
    charge_keys = {person_id: f"charge:{person_id}:single:{game.game_date}" for person_id in person_ids}
    for key in sorted(charge_keys.values()):
        await lock(session, key)
    charges = {charge.person_id: charge for charge in (await session.scalars(
        select(Charge).where(
            Charge.person_id.in_(person_ids),
            Charge.type == "single",
            Charge.reference_date == game.game_date,
        )
    )).all()}

    charge = charges.get(source_id)
    remaining = [other for other in entries if other.id != entry.id and other.person_id == source_id]
    if charge is not None and remaining:
        if entry.status == "waiting" and any(other.status == "main" for other in remaining):
            charge = None
        elif entry.status == "waiting" or any(other.status == "main" for other in remaining):
            raise HTTPException(409, "As inscrições deste jogador compartilham uma cobrança. Revise as entradas duplicadas antes de trocar o jogador.")
    if charge is not None and player.id in charges:
        raise HTTPException(409, "O jogador selecionado já tem uma cobrança deste jogo. Revise as cobranças antes de trocar o jogador.")

    timestamp = now()
    before = {"entry_id": entry.id, "game_date": game.game_date, "person_id": source_id, "name": entry.name}
    after = {**before, "person_id": player.id, "name": player.name}
    event = dict(entity_type="weekly", entity_id=game.id, action="replace_player",
                 before=before, after=after, user=user, person_id=player.id)
    for key in sorted(f"weekly:{person_id}:{game.game_date}" for person_id in person_ids):
        if not await revision(session, key, timestamp, **event):
            raise HTTPException(409, "A inscrição tem uma alteração mais recente. Atualize a lista e tente novamente.")

    if charge is not None:
        charge_before = charge_dict(charge)
        charge.person_id = player.id
        charge_event = dict(entity_type="charge", entity_id=charge.id, action="identity_transfer",
                            before=charge_before, after={**charge_dict(charge), "entry_id": entry.id},
                            user=user, person_id=player.id)
        for key in sorted(charge_keys.values()):
            if not await revision(session, key, timestamp, **charge_event):
                raise HTTPException(409, "A cobrança tem uma alteração mais recente. Atualize a lista e tente novamente.")
        await audit(session, occurred_at=timestamp, **charge_event)

    entry.person_id = player.id
    entry.name = player.name
    entry.normalized_name = player.normalized_name
    await session.flush()
    await recalculate(session, game, at=timestamp, user=user, historical_person_ids={player.id})
    await audit(session, occurred_at=timestamp, **event)


async def add_entry(session, game, person, *, user=None, at=None, source="panel", invited_by=None, position=None, section="main", team=None, source_name=None):
    timestamp = aware(at)
    await lock(session, f"game:{game.id}")
    entry = await session.scalar(select(WeeklyAttendanceEntry).where(WeeklyAttendanceEntry.attendance_id == game.id, WeeklyAttendanceEntry.person_id == person.id).order_by(WeeklyAttendanceEntry.deleted_at.asc().nulls_first(),case((WeeklyAttendanceEntry.status=="main",0),else_=1),WeeklyAttendanceEntry.display_order,WeeklyAttendanceEntry.id).limit(1))
    event = dict(entity_type="weekly",entity_id=game.id,action="join",person_id=person.id,user=user,source=source,after={"game_date":game.game_date,"person_id":person.id})
    if not await revision(session, f"weekly:{person.id}:{game.game_date}",timestamp,**event):
        return entry
    max_position = await session.scalar(select(func.max(WeeklyAttendanceEntry.source_position)).where(
        WeeklyAttendanceEntry.attendance_id == game.id,
        WeeklyAttendanceEntry.deleted_at.is_(None),
    )) or 0
    max_display_order = await session.scalar(select(func.max(WeeklyAttendanceEntry.display_order)).where(
        WeeklyAttendanceEntry.attendance_id == game.id,
        WeeklyAttendanceEntry.deleted_at.is_(None),
    )) or 0
    if entry is None:
        entry = WeeklyAttendanceEntry(attendance_id=game.id,person_id=person.id,name=source_name or person.name,normalized_name=person.normalized_name,source_section=section,source_position=position or max_position+1,display_order=max_display_order+1,status="waiting",is_monthly_subscriber=False,owes_single_payment=False,joined_at=timestamp)
        session.add(entry)
    elif entry.deleted_at is not None:
        entry.joined_at = timestamp
        entry.source_section = section
        # Rejoins append to the current queue. An incoming WhatsApp snapshot
        # assigns its authoritative source position and display order below.
        entry.source_position = max_position + 1
        entry.display_order = max_display_order + 1
    entry.deleted_at = None
    entry.name = source_name or person.name
    entry.normalized_name = person.normalized_name
    if position is not None:
        entry.source_position = position
        entry.source_section = section
    if source not in {"whatsapp", "import"}:
        entry.source_message_id = None
    entry.invited_by = invited_by
    entry.normalized_invited_by = normalize_name(invited_by) if invited_by else None
    entry.prebuilt_team_number = team
    await session.flush()
    await recalculate(session,game,timestamp,user,source,defer_snapshot_charges=source == "whatsapp")
    await audit(session,occurred_at=timestamp,**event)
    return entry


async def remove_entry(session, game, entry, *, user=None, at=None, source="panel", all_for_person=False):
    timestamp=aware(at)
    await lock(session,f"game:{game.id}")
    targets=[entry]
    if all_for_person:
        targets=list((await session.scalars(select(WeeklyAttendanceEntry).where(WeeklyAttendanceEntry.attendance_id==game.id,WeeklyAttendanceEntry.person_id==entry.person_id,WeeklyAttendanceEntry.deleted_at.is_(None)))).all())
    event=dict(entity_type="weekly",entity_id=game.id,action="leave",person_id=entry.person_id,user=user,source=source,
               before={"game_date":game.game_date,"name":entry.name,"entries":[{"id":e.id,"status":e.status,"position":e.display_order} for e in targets]},
               after={"deleted":True,"entry_ids":[e.id for e in targets]})
    if not await revision(session,f"weekly:{entry.person_id}:{game.game_date}",timestamp,**event):
        return
    for target in targets:
        target.deleted_at=timestamp
    await session.flush()
    if source in {"panel", "self_service"}:
        await compact_source_positions(session, await active_entries(session, game.id))
    remaining=await session.scalar(select(WeeklyAttendanceEntry.id).where(WeeklyAttendanceEntry.attendance_id==game.id,WeeklyAttendanceEntry.person_id==entry.person_id,WeeklyAttendanceEntry.deleted_at.is_(None)).limit(1))
    charge = await session.scalar(select(Charge).where(Charge.person_id==entry.person_id,Charge.type=="single",Charge.reference_date==game.game_date))
    if source != "whatsapp" and remaining is None and charge is not None and charge.status != "waived" and timestamp < starts(game):
        await set_charge(session,entry.person_id,"single",game.game_date,status="cancelled",user=user,occurred_at=timestamp,source=source,reason="Saída antes do início")
    await recalculate(session,game,timestamp,user,source,defer_snapshot_charges=source == "whatsapp")
    await audit(session,occurred_at=timestamp,**event)


async def monthly_upsert(session, person, month, year, *, has_paid=None, position=None, user=None, at=None, source="panel", source_name=None):
    reference=date(year,month,1)
    await lock(session,f"monthly:{reference}")
    row=await session.scalar(select(MonthlySubscriber).where(MonthlySubscriber.person_id==person.id,MonthlySubscriber.month==month,MonthlySubscriber.year==year).order_by(MonthlySubscriber.deleted_at.desc().nulls_first(),MonthlySubscriber.id).limit(1))
    event=dict(entity_type="monthly",entity_id=f"{person.id}:{reference}",action="upsert",person_id=person.id,user=user,source=source,after={"month":month,"year":year,"has_paid":has_paid})
    if not await revision(session,f"monthly:{person.id}:{reference}",at,**event):
        return row
    active=list((await session.scalars(select(MonthlySubscriber).where(MonthlySubscriber.month==month,MonthlySubscriber.year==year,MonthlySubscriber.deleted_at.is_(None)))).all())
    if (row is None or row.deleted_at is not None) and len(active)>=24:
        raise HTTPException(409,"O mês já possui 24 assinantes")
    if position is None:
        position=row.position if row else next(i for i in range(1,25) if i not in {r.position for r in active})
    if not 1<=position<=24:
        raise HTTPException(409,"Posição mensal deve estar entre 1 e 24")
    if any(r.position==position and (row is None or r.id!=row.id) for r in active):
        raise HTTPException(409,"Posição mensal já ocupada")
    if row is None:
        row=MonthlySubscriber(person_id=person.id,name=source_name or person.name,normalized_name=person.normalized_name,month=month,year=year,position=position,has_paid=bool(has_paid))
        session.add(row)
    elif source_name:
        row.name=source_name
    row.deleted_at=None
    row.position=position
    if source not in {"whatsapp", "import"}:
        row.source_message_id = None
    charge=await set_charge(session,person.id,"monthly",reference,status=("paid" if has_paid else "pending") if has_paid is not None else None,user=user,occurred_at=at,source=source)
    row.has_paid=charge.status=="paid"
    await session.flush()
    await audit(session,occurred_at=at,**event)
    await refresh_month_games(session,month,year,user=user,source=source)
    return row


async def monthly_remove(session,row,*,user=None,at=None,source="panel"):
    reference=date(row.year,row.month,1)
    event=dict(entity_type="monthly",entity_id=row.id,action="delete",person_id=row.person_id,user=user,source=source,before={"month":row.month,"year":row.year,"name":row.name},after={"deleted":True})
    if await revision(session,f"monthly:{row.person_id}:{reference}",at,**event):
        row.deleted_at=aware(at)
        # Removing a subscriber never silently forgives an existing debt.
        await audit(session,occurred_at=at,**event)
        await session.flush()
        await refresh_month_games(session,row.month,row.year,user=user,source=source)


async def refresh_month_games(session,month,year,*,user=None,source="panel"):
    games=(await session.scalars(select(WeeklyAttendance).where(func.extract("month",WeeklyAttendance.game_date)==month,func.extract("year",WeeklyAttendance.game_date)==year))).all()
    for game in games:
        await lock(session,f"game:{game.id}")
        # Supplying an explicit timestamp permits recalculating historical
        # games when that month's subscription is added or its payment changes.
        await recalculate(session,game,at=now(),user=user,source=source)


async def refresh_identity_games(session, person_ids, *, game_ids=(), months=(), user=None):
    """Recalculate changed entries and games with affected subscriptions."""
    scopes = []
    if game_ids:
        scopes.append(WeeklyAttendance.id.in_(game_ids))
    if months:
        participants = select(WeeklyAttendanceEntry.attendance_id).where(
            WeeklyAttendanceEntry.person_id.in_(person_ids),
            WeeklyAttendanceEntry.deleted_at.is_(None),
        )
        period = tuple_(func.extract("year", WeeklyAttendance.game_date),
                        func.extract("month", WeeklyAttendance.game_date))
        scopes.append(period.in_(months) & WeeklyAttendance.id.in_(participants))
    if not scopes:
        return
    games = (await session.scalars(
        select(WeeklyAttendance).where(or_(*scopes)).order_by(WeeklyAttendance.game_date)
    )).all()
    for game in games:
        await lock(session, f"game:{game.id}")
        await recalculate(session, game, at=now(), user=user, source="alias_reconcile",
                          historical_person_ids=person_ids)
