from datetime import date, datetime, time, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user, require_admin
from app.database import get_session
from app.aliases import create_alias, detach_alias_history, reconcile_alias_history, resolve_normalized_name
from app.models import Person, PersonAlias, FredAccount, MonthlySubscriber, WeeklyAttendance, WeeklyAttendanceEntry, Charge, AuditEvent, ProcessedConversationMessage
from app.parser import normalize_name
from app.payment_notifications import enqueue_list_update, enqueue_payment_list
from app import management as d

router=APIRouter(prefix="/api")

class PersonInput(BaseModel):
    name:str=Field(min_length=1,max_length=100)
class PersonPatch(BaseModel):
    name:str|None=Field(default=None,min_length=1,max_length=100)
    active:bool|None=None
class PersonMerge(BaseModel):
    target_id:UUID
class AliasInput(BaseModel):
    alias:str=Field(min_length=1,max_length=100)
class AccountPatch(BaseModel):
    person_id:UUID|None=None
    is_admin:bool|None=None
class MonthlyInput(BaseModel):
    person_id:UUID
    month:int=Field(ge=1,le=12)
    year:int=Field(ge=2000,le=2200)
    has_paid:bool=False
    position:int|None=Field(default=None,ge=1,le=24)
class MonthlyPatch(BaseModel):
    has_paid:bool|None=None
    position:int|None=Field(default=None,ge=1,le=24)
class GameInput(BaseModel):
    game_date:date
    capacity:int=Field(default=24,ge=1,le=200)
    starts_at:datetime|None=None
class GamePatch(BaseModel):
    capacity:int|None=Field(default=None,ge=1,le=200)
    starts_at:datetime|None=None
class EntryInput(BaseModel):
    person_id:UUID
    invited_by:str|None=Field(default=None,max_length=100)
    prebuilt_team_number:int|None=Field(default=None,ge=1,le=200)
class EntryPatch(BaseModel):
    invited_by:str|None=Field(default=None,max_length=100)
    prebuilt_team_number:int|None=Field(default=None,ge=1,le=200)
class EntryPlayerPatch(BaseModel):
    person_id:UUID
class GuestInput(BaseModel):
    name:str=Field(min_length=1,max_length=100)
class ChargePatch(BaseModel):
    status:Literal["pending","paid","cancelled","waived"]|None=None
    amount_cents:int|None=Field(default=None,ge=0,le=10000000)
    reason:str=Field(default="",max_length=1000)


def person_dict(p):
    return {"id":p.id,"name":p.name,"normalized_name":p.normalized_name,"active":p.active}


def entry_dict(e):
    return {"id":e.id,"person_id":e.person_id,"name":e.name,"status":e.status,"position":e.display_order,
            "is_monthly_subscriber":e.is_monthly_subscriber,"invited_by":e.invited_by,"has_source":e.source_message_id is not None,"source_message_id":e.source_message_id,
            "prebuilt_team_number":e.prebuilt_team_number,"owes_single_payment":e.owes_single_payment}


def game_dict(g,entries):
    return {"id":g.id,"game_date":g.game_date,"capacity":g.capacity,"cutoff_at":g.cutoff_at,"starts_at":d.starts(g),
            "main_count":sum(e.status=="main" for e in entries),"waiting_count":sum(e.status=="waiting" for e in entries)}


async def monthly_items(session,month=None,year=None,person_id=None):
    query=select(MonthlySubscriber,Person,Charge).join(Person,Person.id==MonthlySubscriber.person_id).outerjoin(Charge,(Charge.person_id==Person.id)&(Charge.type=="monthly")&(func.extract("month",Charge.reference_date)==MonthlySubscriber.month)&(func.extract("year",Charge.reference_date)==MonthlySubscriber.year)).where(MonthlySubscriber.deleted_at.is_(None))
    if month is not None: query=query.where(MonthlySubscriber.month==month)
    if year is not None: query=query.where(MonthlySubscriber.year==year)
    if person_id: query=query.where(Person.id==person_id)
    rows=(await session.execute(query.order_by(MonthlySubscriber.year.desc(),MonthlySubscriber.month.desc(),MonthlySubscriber.position))).all()
    return [{"id":m.id,"person_id":p.id,"name":p.name,"position":m.position,"month":m.month,"year":m.year,"has_paid":c.status=="paid" if c else m.has_paid,"charge_status":c.status if c else ("paid" if m.has_paid else "pending"),"amount_cents":c.amount_cents if c else 1250,"charge_id":c.id if c else None,"has_source":m.source_message_id is not None,"source_message_id":m.source_message_id} for m,p,c in rows]


def source_message_dict(message):
    if message is None or message.raw_text is None:
        return None
    return {"id":message.id,"occurred_at":message.occurred_at,"sender_name":message.sender_name,
            "provider_message_id":message.provider_message_id,"sender_id":message.sender_id,
            "chat_id":message.chat_id,"source":message.source,
            "text":message.raw_text,"status":message.status}


def source_history_item(message):
    return source_message_dict(message) | {"message_type":message.message_type}


def user_readable_audit_event(event):
    """Hide ingestion plumbing and source mutations from human histories."""
    return event.entity_type != "ingestion" and (
        event.action == "list_change" or event.source not in {"whatsapp", "import"}
    )


@router.get("/people")
async def people(user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    rows=(await session.scalars(select(Person).order_by(Person.name))).all()
    aliases=(await session.scalars(select(PersonAlias))).all()
    return {"items":[{
        **person_dict(p),
        "aliases":[a.alias for a in aliases if a.canonical_normalized==p.normalized_name],
        "alias_details":[
            {"id":a.id,"alias":a.alias,"protected":a.alias_normalized==normalize_name(p.name) and a.alias_normalized!=p.normalized_name}
            for a in aliases if a.canonical_normalized==p.normalized_name
        ],
    } for p in rows]}


@router.post("/people",status_code=201)
async def person_create(payload:PersonInput,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    normalized=normalize_name(payload.name)
    if await session.scalar(select(Person).where(Person.normalized_name==normalized)):
        raise HTTPException(409,"Pessoa já cadastrada")
    if await session.scalar(select(PersonAlias.id).where(PersonAlias.alias_normalized==normalized)):
        raise HTTPException(409,"O nome já é apelido de outro jogador")
    p=await d.person_for_name(session,payload.name)
    await d.audit(session,entity_type="person",entity_id=p.id,action="create",user=user,person_id=p.id,after=person_dict(p))
    await session.commit()
    return person_dict(p)


@router.patch("/people/{identifier}")
async def person_patch(identifier:UUID,payload:PersonPatch,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    p=await d.get_or_404(session,Person,identifier)
    before=person_dict(p)
    if payload.name is not None:
        if not normalize_name(payload.name): raise HTTPException(422,"Nome inválido")
        normalized=normalize_name(payload.name)
        if normalized!=p.normalized_name:
            other=await session.scalar(select(Person).where(Person.normalized_name==normalized,Person.id!=p.id))
            if other: raise HTTPException(409,"O nome já identifica outra pessoa")
            alias=await session.scalar(select(PersonAlias).where(PersonAlias.alias_normalized==normalized))
            if alias and alias.canonical_normalized!=p.normalized_name: raise HTTPException(409,"O nome é apelido de outra pessoa")
            if not alias:
                try:
                    await create_alias(session,alias=payload.name,canonical_name=p.normalized_name,user=user)
                except ValueError as exc:
                    raise HTTPException(409,str(exc)) from exc
        p.name=payload.name.strip()
    if payload.active is not None: p.active=payload.active
    await d.audit(session,entity_type="person",entity_id=p.id,action="update",user=user,person_id=p.id,before=before,after=person_dict(p))
    await session.commit()
    return person_dict(p)


@router.post("/people/{identifier}/merge")
async def person_merge(identifier:UUID,payload:PersonMerge,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    try:
        await d.merge_people(session, identifier, payload.target_id, user=user)
        await session.commit()
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) not in {"23503", "23505", "40001", "40P01"}:
            raise
        await session.rollback()
        raise HTTPException(409, "Os registros mudaram durante a união. Atualize a lista e tente novamente.") from exc
    return {"ok":True}


@router.post("/people/{identifier}/aliases")
async def alias_create(identifier:UUID,payload:AliasInput,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    p=await d.get_or_404(session,Person,identifier)
    other=await session.scalar(select(Person).where(Person.normalized_name==normalize_name(payload.alias),Person.id!=p.id))
    if other: raise HTTPException(409,"O apelido já identifica outra pessoa cadastrada")
    try:
        row,*_=await create_alias(session,alias=payload.alias,canonical_name=p.normalized_name,user=user)
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc
    await d.audit(session,entity_type="person",entity_id=p.id,action="alias",user=user,person_id=p.id,after={"alias":row.alias,"canonical_person_name":p.name})
    await session.commit()
    return {"ok":True}


async def editable_alias(session:AsyncSession,p:Person,alias_id:UUID):
    row=await session.scalar(select(PersonAlias).where(PersonAlias.id==alias_id,PersonAlias.canonical_normalized==p.normalized_name))
    if row is None: raise HTTPException(404,"Apelido não encontrado")
    if row.alias_normalized==normalize_name(p.name) and row.alias_normalized!=p.normalized_name:
        raise HTTPException(409,"Este apelido corresponde ao nome exibido do jogador. Altere o nome do jogador antes de removê-lo.")
    return row


@router.patch("/people/{identifier}/aliases/id/{alias_id}")
async def alias_update(identifier:UUID,alias_id:UUID,payload:AliasInput,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    p=await d.get_or_404(session,Person,identifier)
    row=await editable_alias(session,p,alias_id)
    normalized=normalize_name(payload.alias)
    if not normalized: raise HTTPException(422,"O apelido deve conter letras ou números")
    if normalized==p.normalized_name: raise HTTPException(409,"O apelido não pode ser igual ao nome canônico do jogador")
    duplicate=await session.scalar(select(PersonAlias.id).where(PersonAlias.alias_normalized==normalized,PersonAlias.id!=row.id))
    other=await session.scalar(select(Person.id).where(Person.normalized_name==normalized,Person.id!=p.id))
    if duplicate or other: raise HTTPException(409,"Esse apelido já identifica outra entrada")
    before={"alias":row.alias}
    if normalized!=row.alias_normalized:
        await detach_alias_history(session, alias=row.alias, canonical=p, user=user)
    row.alias=payload.alias.strip()
    row.alias_normalized=normalized
    try:
        await reconcile_alias_history(session,row,user=user)
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from exc
    await d.audit(session,entity_type="person",entity_id=p.id,action="alias_updated",user=user,person_id=p.id,before=before,after={"alias":row.alias})
    await session.commit()
    return {"ok":True}


@router.delete("/people/{identifier}/aliases/id/{alias_id}")
async def alias_delete_by_id(identifier:UUID,alias_id:UUID,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    p=await d.get_or_404(session,Person,identifier)
    row=await editable_alias(session,p,alias_id)
    counts=await detach_alias_history(session, alias=row.alias, canonical=p, user=user)
    await session.delete(row)
    await d.audit(session,entity_type="person",entity_id=p.id,action="remove_alias",user=user,person_id=p.id,before={"alias":row.alias},after={"detached_records":counts})
    await session.commit()
    return {"ok":True}


@router.delete("/people/{identifier}/aliases/{alias}")
async def alias_delete(identifier:UUID,alias:str,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    p=await d.get_or_404(session,Person,identifier)
    row=await session.scalar(select(PersonAlias).where(PersonAlias.alias_normalized==normalize_name(alias),PersonAlias.canonical_normalized==p.normalized_name))
    if row is None: raise HTTPException(404,"Apelido não encontrado")
    if row.alias_normalized==normalize_name(p.name) and row.alias_normalized!=p.normalized_name:
        raise HTTPException(409,"Este apelido corresponde ao nome exibido do jogador. Altere o nome do jogador antes de removê-lo.")
    counts=await detach_alias_history(session, alias=row.alias, canonical=p, user=user)
    await session.delete(row)
    await d.audit(session,entity_type="person",entity_id=p.id,action="remove_alias",user=user,person_id=p.id,before={"alias":alias},after={"detached_records":counts})
    await session.commit()
    return {"ok":True}


@router.get("/accounts")
async def accounts(user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    rows=(await session.execute(select(FredAccount,Person).outerjoin(Person,Person.id==FredAccount.person_id).order_by(FredAccount.username))).all()
    return {"items":[{"uid":a.uid,"username":a.username,"name":a.name,"email":a.email,"is_admin":a.is_admin,"person_id":a.person_id,"person_name":p.name if p else None} for a,p in rows]}


@router.patch("/accounts/{uid}")
async def account_patch(uid:str,payload:AccountPatch,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    a=await d.get_or_404(session,FredAccount,uid)
    before={"person_id":a.person_id,"is_admin":a.is_admin}
    if "person_id" in payload.model_fields_set:
        if payload.person_id:
            await d.get_or_404(session,Person,payload.person_id)
            linked=await session.scalar(select(FredAccount).where(FredAccount.person_id==payload.person_id,FredAccount.uid!=uid))
            if linked: raise HTTPException(409,"Pessoa já vinculada a outra conta")
        a.person_id=payload.person_id
    if payload.is_admin is not None:
        if a.username=="pyu" and not payload.is_admin: raise HTTPException(409,"O gestor inicial deve permanecer ativo")
        a.is_admin=payload.is_admin
    await d.audit(session,entity_type="account",entity_id=uid,action="update",user=user,person_id=a.person_id,before=before,after={"person_id":a.person_id,"is_admin":a.is_admin})
    await session.commit()
    return {"ok":True}


@router.delete("/accounts/{uid}")
async def account_delete(uid:str,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    if uid==user["uid"]:
        raise HTTPException(409,"Você não pode excluir a própria conta")
    account=await d.get_or_404(session,FredAccount,uid)
    before={"uid":account.uid,"username":account.username,"name":account.name,
            "email":account.email,"is_admin":account.is_admin,"person_id":account.person_id}
    await d.audit(session,entity_type="account",entity_id=uid,action="delete",user=user,
                  person_id=account.person_id,before=before)
    await session.delete(account)
    await session.commit()
    return {"ok":True}


@router.get("/monthly")
async def monthly(month:int=Query(ge=1,le=12),year:int=Query(ge=2000,le=2200),user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    return {"month":month,"year":year,"items":await monthly_items(session,month,year)}


@router.get("/source-history/monthly")
async def monthly_source_history(response:Response,month:int=Query(ge=1,le=12),year:int=Query(ge=2000,le=2200),user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    response.headers["Cache-Control"] = "no-store"
    key=f"monthly:{year:04d}-{month:02d}"
    rows=(await session.scalars(select(ProcessedConversationMessage).where(
        ProcessedConversationMessage.aggregate_key==key,
        ProcessedConversationMessage.message_type=="monthly_subscribers",
        ProcessedConversationMessage.raw_text.is_not(None),
        ProcessedConversationMessage.status.in_(["applied","unchanged","stale"]),
    ).order_by(ProcessedConversationMessage.occurred_at,ProcessedConversationMessage.source_ordinal,
               ProcessedConversationMessage.created_at,ProcessedConversationMessage.id))).all()
    return {"items":[source_history_item(row) for row in rows]}


@router.get("/source-history/weekly")
async def weekly_source_history(response:Response,game_date:date,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    response.headers["Cache-Control"] = "no-store"
    key=f"weekly:{game_date.isoformat()}"
    rows=(await session.scalars(select(ProcessedConversationMessage).where(
        ProcessedConversationMessage.aggregate_key==key,
        ProcessedConversationMessage.message_type=="weekly_attendance",
        ProcessedConversationMessage.raw_text.is_not(None),
        ProcessedConversationMessage.status.in_(["applied","unchanged","stale"]),
    ).order_by(ProcessedConversationMessage.occurred_at,ProcessedConversationMessage.source_ordinal,
               ProcessedConversationMessage.created_at,ProcessedConversationMessage.id))).all()
    return {"items":[source_history_item(row) for row in rows]}


@router.get("/monthly/{identifier}/source")
async def monthly_source(identifier:UUID,response:Response,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    response.headers["Cache-Control"] = "no-store"
    row=await d.get_or_404(session,MonthlySubscriber,identifier)
    message=await session.get(ProcessedConversationMessage,row.source_message_id) if row.source_message_id else None
    return {"message":source_message_dict(message)}


@router.get("/games/{game_id}/entries/{entry_id}/source")
async def weekly_source(game_id:UUID,entry_id:UUID,response:Response,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    response.headers["Cache-Control"] = "no-store"
    _,row=await entry_for_game(session,game_id,entry_id)
    message=await session.get(ProcessedConversationMessage,row.source_message_id) if row.source_message_id else None
    return {"message":source_message_dict(message)}


@router.post("/monthly",status_code=201)
async def monthly_create(payload:MonthlyInput,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    p=await d.get_or_404(session,Person,payload.person_id)
    if not p.active: raise HTTPException(409,"Pessoa inativa")
    await update_monthly_from_panel(session,p,payload.month,payload.year,payload,user)
    await session.commit()
    return {"ok":True}


@router.patch("/monthly/{identifier}")
async def monthly_patch(identifier:UUID,payload:MonthlyPatch,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    row=await d.get_or_404(session,MonthlySubscriber,identifier)
    await d.lock(session, f"monthly:{date(row.year,row.month,1)}")
    await session.refresh(row)
    if row.deleted_at: raise HTTPException(404,"Assinatura removida")
    p=await d.get_or_404(session,Person,row.person_id)
    await update_monthly_from_panel(session,p,row.month,row.year,payload,user)
    await session.commit()
    return {"ok":True}


async def update_monthly_from_panel(session, person, month, year, payload, user):
    reference = date(year, month, 1)
    await d.lock(session, f"monthly:{reference}")
    previous = (await session.execute(select(MonthlySubscriber.position, MonthlySubscriber.has_paid).where(
        MonthlySubscriber.person_id == person.id, MonthlySubscriber.month == month,
        MonthlySubscriber.year == year, MonthlySubscriber.deleted_at.is_(None),
    ))).first()
    previous_status = await session.scalar(select(Charge.status).where(
        Charge.person_id == person.id, Charge.type == "monthly", Charge.reference_date == reference,
    ))
    if previous_status is None:
        was_paid = bool(previous and previous.has_paid)
    else:
        was_paid = previous_status == "paid"
    row = await d.monthly_upsert(session, person, month, year, has_paid=payload.has_paid,
                                 position=payload.position, user=user)
    if row is None or row.deleted_at is not None:
        return
    if previous is None or previous.position != row.position:
        enqueue_list_update(session, list_type="monthly_subscribers", reference=reference)
    elif payload.has_paid is not None:
        enqueue_payment_list(session, person_id=person.id, kind="monthly", reference=reference,
                             was_paid=was_paid, is_paid=row.has_paid)


@router.delete("/monthly/{identifier}")
async def monthly_delete(identifier:UUID,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    row=await d.get_or_404(session,MonthlySubscriber,identifier)
    reference = date(row.year, row.month, 1)
    await d.lock(session, f"monthly:{reference}")
    await session.refresh(row)
    was_active = row.deleted_at is None
    await d.monthly_remove(session,row,user=user)
    if was_active and row.deleted_at is not None:
        enqueue_list_update(session, list_type="monthly_subscribers", reference=reference)
    await session.commit()
    return {"ok":True}


@router.get("/games")
async def games(user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    rows=(await session.scalars(select(WeeklyAttendance).order_by(WeeklyAttendance.game_date.desc()))).all()
    return {"items":[game_dict(g,await d.active_entries(session,g.id)) for g in rows]}


@router.post("/games",status_code=201)
async def game_create(payload:GameInput,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    if payload.game_date.weekday()!=2: raise HTTPException(422,"A partida deve ser uma quarta-feira")
    if await session.scalar(select(WeeklyAttendance).where(WeeklyAttendance.game_date==payload.game_date)): raise HTTPException(409,"Partida já cadastrada")
    start=d.aware(payload.starts_at) if payload.starts_at else datetime.combine(payload.game_date,time(19,30),d.TZ)
    if start.astimezone(d.TZ).date()!=payload.game_date or start<=datetime.combine(payload.game_date,time(16),d.TZ): raise HTTPException(422,"Início deve ocorrer após 16h na data da partida")
    g=WeeklyAttendance(game_date=payload.game_date,capacity=payload.capacity,cutoff_at=datetime.combine(payload.game_date,time(16),d.TZ),starts_at=start)
    session.add(g)
    await session.flush()
    await d.audit(session,entity_type="game",entity_id=g.id,action="create",user=user,after=game_dict(g,[]))
    await session.commit()
    return game_dict(g,[])


@router.get("/games/{identifier}")
async def game_get(identifier:UUID,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    g=await d.get_or_404(session,WeeklyAttendance,identifier)
    await d.recalculate(session,g,source="system")
    entries = sorted(await d.active_entries(session, g.id), key=lambda entry: (
        entry.source_section != "main", entry.source_position,
    ))
    await session.commit()
    return {
        **game_dict(g, entries),
        "entries": [entry_dict(entry) | {
            "source_section": entry.source_section,
            "source_position": entry.source_position,
        } for entry in entries],
    }


@router.patch("/games/{identifier}")
async def game_patch(identifier:UUID,payload:GamePatch,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    g=await d.get_or_404(session,WeeklyAttendance,identifier)
    await d.lock(session,f"game:{g.id}")
    before=game_dict(g,await d.active_entries(session,g.id))
    if payload.capacity is not None: g.capacity=payload.capacity
    if payload.starts_at is not None:
        start=d.aware(payload.starts_at)
        if start.astimezone(d.TZ).date()!=g.game_date or start<=g.cutoff_at: raise HTTPException(422,"Início deve ser após 16h na data da partida")
        g.starts_at=start
    await d.recalculate(session,g,at=d.now(),user=user)
    await d.audit(session,entity_type="game",entity_id=g.id,action="update",user=user,before=before,after=game_dict(g,await d.active_entries(session,g.id)))
    await session.commit()
    return {"ok":True}


@router.post("/games/{identifier}/entries")
async def entry_create(identifier:UUID,payload:EntryInput,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    g=await d.get_or_404(session,WeeklyAttendance,identifier)
    p=await d.get_or_404(session,Person,payload.person_id)
    await d.lock(session, f"game:{g.id}")
    before = {
        entry.id: (entry.name, entry.invited_by, entry.prebuilt_team_number)
        for entry in await d.active_entries(session, g.id)
        if entry.person_id == p.id
    }
    entry = await d.add_entry(session,g,p,user=user,invited_by=payload.invited_by,team=payload.prebuilt_team_number)
    if entry is not None and entry.deleted_at is None:
        after = (entry.name, entry.invited_by, entry.prebuilt_team_number)
        if before.get(entry.id) != after:
            enqueue_list_update(session, list_type="weekly_attendance", reference=g.game_date)
    await session.commit()
    return {"ok":True}


async def entry_for_game(session,identifier,entry_id,*,lock_game=False):
    g=await d.get_or_404(session,WeeklyAttendance,identifier)
    if lock_game:
        await d.lock(session,f"game:{g.id}")
    e=await d.get_or_404(session,WeeklyAttendanceEntry,entry_id)
    if e.attendance_id!=g.id or e.deleted_at: raise HTTPException(404,"Inscrição não encontrada")
    return g,e


@router.patch("/games/{identifier}/entries/{entry_id}")
async def entry_patch(identifier:UUID,entry_id:UUID,payload:EntryPatch,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    g,e=await entry_for_game(session,identifier,entry_id,lock_game=True)
    before=entry_dict(e)
    timestamp=d.now()
    if not await d.revision(session,f"weekly:{e.person_id}:{g.game_date}",timestamp,entity_type="weekly",entity_id=g.id,action="update",user=user,person_id=e.person_id,after=payload.model_dump()):
        await session.commit()
        return {"ok": True}
    if "invited_by" in payload.model_fields_set:
        e.invited_by = (payload.invited_by or "").strip() or None
        e.normalized_invited_by = (normalize_name(e.invited_by) or None) if e.invited_by else None
    if "prebuilt_team_number" in payload.model_fields_set: e.prebuilt_team_number=payload.prebuilt_team_number
    await d.audit(session,entity_type="weekly",entity_id=g.id,action="update",user=user,person_id=e.person_id,before=before,after=entry_dict(e))
    if (before["invited_by"], before["prebuilt_team_number"]) != (e.invited_by, e.prebuilt_team_number):
        enqueue_list_update(session, list_type="weekly_attendance", reference=g.game_date)
    await session.commit()
    return {"ok":True}


@router.patch("/games/{identifier}/entries/{entry_id}/player")
async def entry_player_patch(
    identifier: UUID, entry_id: UUID, payload: EntryPlayerPatch,
    user=Depends(require_admin), session: AsyncSession=Depends(get_session),
):
    game, entry = await entry_for_game(session, identifier, entry_id, lock_game=True)
    player = await d.get_or_404(session, Person, payload.person_id)
    previous_player_id = entry.person_id
    await d.replace_entry_player(session, game, entry, player, user=user)
    if previous_player_id != entry.person_id:
        enqueue_list_update(session, list_type="weekly_attendance", reference=game.game_date)
    await session.commit()
    return {"ok": True}


@router.delete("/games/{identifier}/entries/{entry_id}")
async def entry_delete(identifier:UUID,entry_id:UUID,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    g,e=await entry_for_game(session,identifier,entry_id,lock_game=True)
    await d.remove_entry(session,g,e,user=user)
    if e.deleted_at is not None:
        enqueue_list_update(session, list_type="weekly_attendance", reference=g.game_date)
    await session.commit()
    return {"ok":True}


async def weekly_charge_entries(session: AsyncSession, charges: list[Charge]):
    charge_keys = {(charge.person_id, charge.reference_date) for charge in charges if charge.type == "single"}
    if not charge_keys:
        return {}
    person_ids = {person_id for person_id, _ in charge_keys}
    game_dates = {game_date for _, game_date in charge_keys}
    rows = await session.execute(
        select(WeeklyAttendanceEntry, WeeklyAttendance.game_date)
        .join(WeeklyAttendance, WeeklyAttendance.id == WeeklyAttendanceEntry.attendance_id)
        .where(WeeklyAttendanceEntry.person_id.in_(person_ids), WeeklyAttendance.game_date.in_(game_dates))
        .order_by(
            WeeklyAttendanceEntry.deleted_at.is_not(None),
            WeeklyAttendanceEntry.updated_at.desc(),
            WeeklyAttendanceEntry.display_order,
            WeeklyAttendanceEntry.id,
        )
    )
    latest_entries = {}
    for entry, game_date in rows:
        key = (entry.person_id, game_date)
        if key in charge_keys and key not in latest_entries:
            latest_entries[key] = entry
    return latest_entries


async def charge_items(session: AsyncSession, rows):
    entries = await weekly_charge_entries(session, [charge for charge, _ in rows])
    inviters: dict[str, Person | None] = {}
    items = []
    for charge, owner_name in rows:
        entry = entries.get((charge.person_id, charge.reference_date)) if charge.type == "single" else None
        invited_by = entry.invited_by if entry else None
        # Older panel edits could leave the stored normalized name out of date.
        inviter_key = normalize_name(invited_by or "")
        if inviter_key and inviter_key not in inviters:
            canonical = await resolve_normalized_name(session, inviter_key)
            inviters[inviter_key] = await session.scalar(select(Person).where(Person.normalized_name == canonical))
        inviter = inviters.get(inviter_key)
        if inviter is not None and inviter.id == charge.person_id:
            inviter = None

        item = d.charge_dict(charge, entry.name if entry and invited_by else owner_name)
        item["debtor_person_id"] = inviter.id if inviter else charge.person_id
        item["debtor_name"] = inviter.name if inviter else owner_name
        item["invited_by"] = invited_by if inviter else None
        items.append(item)
    return items


@router.get("/charges")
async def charges(status:Literal["pending","paid","cancelled","waived"]|None=None,type:str|None=None,person_id:UUID|None=None,start_date:date|None=None,end_date:date|None=None,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    query=select(Charge,Person.name).join(Person,Person.id==Charge.person_id)
    if status: query=query.where(Charge.status==status)
    if type: query=query.where(Charge.type==type)
    if person_id: query=query.where(Charge.person_id==person_id)
    if start_date: query=query.where(Charge.reference_date>=start_date)
    if end_date: query=query.where(Charge.reference_date<=end_date)
    rows=(await session.execute(query.order_by(Charge.reference_date.desc(),Person.name))).all()
    items = await charge_items(session, rows)
    return {"items":items,"total_cents":sum(c.amount_cents for c,_ in rows)}


@router.patch("/charges/{identifier}")
async def charge_patch(identifier:UUID,payload:ChargePatch,user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    c=await d.get_or_404(session,Charge,identifier)
    if c.type=="monthly":
        await d.lock(session,f"monthly:{c.reference_date}")
        await session.refresh(c)
    elif c.type=="single":
        game_id=await session.scalar(select(WeeklyAttendance.id).where(WeeklyAttendance.game_date==c.reference_date))
        if game_id is not None:
            await d.lock(session,f"game:{game_id}")
            await session.refresh(c)
    was_paid = c.status == "paid"
    c=await d.set_charge(session,c.person_id,c.type,c.reference_date,status=payload.status,amount=payload.amount_cents,user=user,reason=payload.reason)
    if c.type=="monthly":
        rows=(await session.scalars(select(MonthlySubscriber).where(MonthlySubscriber.person_id==c.person_id,MonthlySubscriber.year==c.reference_date.year,MonthlySubscriber.month==c.reference_date.month))).all()
        for row in rows: row.has_paid=c.status=="paid"
        await d.refresh_month_games(session,c.reference_date.month,c.reference_date.year,user=user)
    elif c.type=="single":
        entries=(await session.scalars(select(WeeklyAttendanceEntry).join(WeeklyAttendance).where(WeeklyAttendanceEntry.person_id==c.person_id,WeeklyAttendance.game_date==c.reference_date))).all()
        for entry in entries:
            entry.owes_single_payment=c.status=="pending" and entry.status=="main" and not entry.is_monthly_subscriber
            entry.single_payment_amount_cents=c.amount_cents
    if payload.status is not None:
        enqueue_payment_list(session, person_id=c.person_id, kind=c.type, reference=c.reference_date,
                             was_paid=was_paid, is_paid=c.status == "paid")
    await session.commit()
    return {"ok":True}


@router.get("/debtors")
async def debtors(user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    rows=(await session.execute(select(Charge,Person.name).join(Person,Person.id==Charge.person_id).where(Charge.status=="pending"))).all()
    grouped={}
    for item in await charge_items(session, rows):
        person_id = item["debtor_person_id"]
        name = item["debtor_name"]
        summary=grouped.setdefault(person_id,{"person_id":person_id,"name":name,"amount_cents":0,"count":0})
        summary["amount_cents"]+=item["amount_cents"]
        summary["count"]+=1
    items=sorted(grouped.values(),key=lambda item:(-item["amount_cents"],item["name"].casefold()))
    return {"items":items,"total_cents":sum(item["amount_cents"] for item in items)}


@router.get("/audit")
async def audit_list(person_id:UUID|None=None,limit:int=Query(default=100,ge=1,le=500),user=Depends(require_admin),session:AsyncSession=Depends(get_session)):
    # Filter semantic list changes before applying the requested page limit;
    # participant_ids lets a multi-person WhatsApp update appear for each player.
    rows=(await session.scalars(select(AuditEvent).order_by(AuditEvent.recorded_at.desc()))).all()
    selected=[]
    for event in rows:
        after=event.after or {}
        if not user_readable_audit_event(event):
            continue
        participants={str(value) for value in after.get("participant_ids", [])}
        if event.person_id is not None:
            participants.add(str(event.person_id))
        if event.entity_type=="weekly" and event.action=="replace_player":
            for value in ((event.before or {}).get("person_id"), after.get("person_id")):
                if value:
                    participants.add(str(value))
        if person_id is not None and str(person_id) not in participants:
            continue
        selected.append(event)
        if len(selected)>=limit:
            break

    message_ids=set()
    for event in selected:
        change=event.after or {}
        if change.get("message_id"):
            message_ids.add(change["message_id"])
        if change.get("previous_message_id"):
            message_ids.add(change["previous_message_id"])
    messages={}
    if message_ids:
        found=(await session.scalars(select(ProcessedConversationMessage).where(
            ProcessedConversationMessage.id.in_(message_ids)
        ))).all()
        messages={str(message.id):message.raw_text for message in found}

    def public_change(change):
        # Keep this projection deliberately semantic and bounded. Raw parser,
        # model, and internal processing metadata remain in the admin payload's
        # existing before/after fields only for the established event types.
        allowed={"kind","reference_date","previous_name","alias"}
        result={key:change[key] for key in allowed if key in change}
        people=[]
        for person in change.get("people", []):
            if isinstance(person, dict):
                people.append({key:person[key] for key in ("id","name","is_actor") if key in person})
        if people:
            result["people"]=people
        return result

    person_ids=set()
    for event in selected:
        after=event.after or {}
        if event.person_id:
            person_ids.add(event.person_id)
        if event.entity_type=="weekly" and event.action=="replace_player":
            for value in ((event.before or {}).get("person_id"), after.get("person_id")):
                if value:
                    try: person_ids.add(UUID(str(value)))
                    except ValueError: pass
    people={str(person.id):person.name for person in (await session.scalars(select(Person).where(Person.id.in_(person_ids)))).all()} if person_ids else {}

    items=[]
    for event in selected:
        item={key:getattr(event,key) for key in ("id","occurred_at","recorded_at","actor_uid","actor_name","source","action","entity_type","entity_id","person_id","before","after","status")}
        after=event.after or {}
        changes=after.get("changes")
        if isinstance(changes,list):
            item["changes"]=[public_change(change) for change in changes if isinstance(change,dict)]
            item["participant_ids"]=after.get("participant_ids", [])
            item["message_diff"]={
                "before":messages.get(str(after["previous_message_id"])) if after.get("previous_message_id") else None,
                "after":messages.get(str(after["message_id"])) if after.get("message_id") else None,
            }
        else:
            semantic=[]
            if event.entity_type=="charge" and event.action=="update" and event.source=="panel":
                before=event.before or {}
                if before.get("status")!="paid" and after.get("status")=="paid":
                    person=str(after.get("person_id") or event.person_id or "")
                    semantic.append({"kind":"monthly_paid" if after.get("type")=="monthly" else "guest_paid",
                        "reference_date":after.get("reference_date"),"people":[{"id":person,"name":people.get(person, after.get("name") or "")} ] if person else []})
            elif event.entity_type=="weekly" and event.action=="replace_player":
                before=event.before or {}
                old_id=str(before.get("person_id") or "")
                new_id=str(after.get("person_id") or event.person_id or "")
                semantic.append({"kind":"player_replaced","reference_date":after.get("game_date") or before.get("game_date"),
                    "people":[{"id":old_id,"name":before.get("name") or people.get(old_id,""),"is_actor":False},
                              {"id":new_id,"name":after.get("name") or people.get(new_id,""),"is_actor":False}]})
            elif event.entity_type=="person" and event.action=="alias":
                person=str(event.person_id or event.entity_id)
                semantic.append({"kind":"alias_added","alias":after.get("alias"),
                    "people":[{"id":person,"name":after.get("canonical_person_name") or people.get(person,"")}]})
            if semantic:
                item["changes"]=semantic
        items.append(item)
    return {"items":items}


async def own_person(session,user):
    account=await d.touch_account(session,user)
    if account.person_id is None: raise HTTPException(403,"Aguarde o vínculo da sua conta pelo gestor")
    return await d.get_or_404(session,Person,account.person_id)


@router.get("/me")
async def me(user=Depends(current_user),session:AsyncSession=Depends(get_session)):
    a=await d.touch_account(session,user)
    result={"person":None,"monthly":[],"charges":[],"games":[],"history":[],"can_manage":bool(user.get("is_admin"))}
    if a.person_id:
        p=await d.get_or_404(session,Person,a.person_id)
        result["person"]={"id":p.id,"name":p.name}
        result["monthly"]=[{k:v for k,v in item.items() if k not in {"has_source","source_message_id"}} for item in await monthly_items(session,person_id=p.id)]
        games=(await session.scalars(select(WeeklyAttendance).order_by(WeeklyAttendance.game_date.desc()))).all()
        for g in games:
            await d.recalculate(session,g,source="system")
            entries=await d.active_entries(session,g.id)
            own=min((e for e in entries if e.person_id==p.id),key=lambda e:(e.status!="main",e.display_order,str(e.id)),default=None)
            if own or d.starts(g)>d.now():
                result["games"].append({**game_dict(g,entries),"own_entry":{k:v for k,v in entry_dict(own).items() if k not in {"invited_by","has_source","source_message_id"}} if own else None,"can_join":p.active and d.now()<d.starts(g),"can_leave":d.now()<d.starts(g)})
        has_inviter = (
            select(1)
            .select_from(WeeklyAttendanceEntry)
            .join(WeeklyAttendance, WeeklyAttendance.id == WeeklyAttendanceEntry.attendance_id)
            .where(
                WeeklyAttendanceEntry.person_id == Charge.person_id,
                WeeklyAttendance.game_date == Charge.reference_date,
                WeeklyAttendanceEntry.invited_by.is_not(None),
            )
            .correlate(Charge)
            .exists()
        )
        charge_rows = (
            await session.execute(
                select(Charge, Person.name)
                .join(Person, Person.id == Charge.person_id)
                .where(or_(Charge.person_id == p.id, (Charge.type == "single") & has_inviter))
                .order_by(Charge.reference_date.desc(), Person.name)
            )
        ).all()
        result["charges"] = [
            item for item in await charge_items(session, charge_rows) if item["debtor_person_id"] == p.id
        ]
        events=(await session.scalars(select(AuditEvent).where(AuditEvent.person_id==p.id).order_by(AuditEvent.recorded_at.desc()))).all()
        events=[event for event in events if user_readable_audit_event(event)][:100]
        result["history"]=[{"id":e.id,"occurred_at":e.occurred_at,"action":e.action,"entity_type":e.entity_type,"status":e.status} for e in events]
    await session.commit()
    return result


def current_brasilia_month() -> tuple[int, int]:
    today = d.aware(d.now()).astimezone(d.TZ).date()
    return today.month, today.year


def monthly_reference_is_current(month: int, year: int) -> bool:
    return (month, year) == current_brasilia_month()


async def inviter_matches_owner(session: AsyncSession, entry: WeeklyAttendanceEntry,
                                owner: Person) -> bool:
    inviter = entry.normalized_invited_by or normalize_name(entry.invited_by)
    if not inviter:
        return False
    inviter = await resolve_normalized_name(session, inviter)
    owner_name = await resolve_normalized_name(session, owner.normalized_name)
    return inviter == owner_name


def player_entry_dict(entry: WeeklyAttendanceEntry, *, can_remove: bool = False) -> dict:
    result = entry_dict(entry)
    result["source_section"] = entry.source_section
    result["source_position"] = entry.source_position
    result["can_remove"] = can_remove
    return result


async def player_history_names(session:AsyncSession, entries) -> dict:
    people_ids = {entry.person_id for entry in entries if entry.person_id is not None}
    if not people_ids:
        return {}
    people = (await session.scalars(select(Person).where(Person.id.in_(people_ids)))).all()
    canonical_names = {person.normalized_name for person in people}
    aliases = (await session.scalars(select(PersonAlias).where(
        PersonAlias.canonical_normalized.in_(canonical_names),
    ).order_by(PersonAlias.alias))).all()
    by_person = {person.id: [person.name, *[
        alias.alias for alias in aliases if alias.canonical_normalized == person.normalized_name
    ]] for person in people}
    result = {}
    for entry in entries:
        names = [entry.name, *by_person.get(entry.person_id, [])]
        result[entry.id] = list(dict.fromkeys(name for name in names if name))
    return result


@router.get("/me/games")
async def player_games(response:Response, user=Depends(current_user), session:AsyncSession=Depends(get_session)):
    response.headers["Cache-Control"] = "no-store"
    person = await own_person(session, user)
    rows = (await session.scalars(select(WeeklyAttendance).order_by(WeeklyAttendance.game_date.desc()))).all()
    items = []
    for game in rows:
        await d.recalculate(session, game, source="system")
        entries = await d.active_entries(session, game.id)
        own = min((entry for entry in entries if entry.person_id == person.id),
                  key=lambda entry: (entry.status != "main", entry.display_order, str(entry.id)),
                  default=None)
        open_for_changes = d.now() < d.starts(game)
        items.append({
            **game_dict(game, entries),
            "own_entry": player_entry_dict(own) if own else None,
            "can_join": bool(person.active and own is None and open_for_changes),
            "can_leave": bool(own and open_for_changes),
            "can_add_guest": bool(person.active and open_for_changes),
        })
    await session.commit()
    return {"items": items}


@router.get("/me/games/{identifier}")
async def player_game_get(identifier:UUID, response:Response, user=Depends(current_user),
                          session:AsyncSession=Depends(get_session)):
    response.headers["Cache-Control"] = "no-store"
    person = await own_person(session, user)
    game = await d.get_or_404(session, WeeklyAttendance, identifier)
    await d.recalculate(session, game, source="system")
    entries = sorted(await d.active_entries(session, game.id), key=lambda entry: (
        entry.source_section != "main", entry.source_position,
    ))
    own = min((entry for entry in entries if entry.person_id == person.id),
              key=lambda entry: (entry.status != "main", entry.display_order, str(entry.id)),
              default=None)
    open_for_changes = d.now() < d.starts(game)
    history_names = await player_history_names(session, entries)
    public_entries = []
    for entry in entries:
        can_remove = bool(
            entry.invited_by and entry.person_id != person.id
            and open_for_changes and await inviter_matches_owner(session, entry, person)
        )
        public_entry = player_entry_dict(entry, can_remove=can_remove)
        public_entry["history_names"] = history_names.get(entry.id, [entry.name])
        public_entries.append(public_entry)
    await session.commit()
    return {
        **game_dict(game, entries),
        "entries": public_entries,
        "own_entry": player_entry_dict(own) if own else None,
        "can_join": bool(person.active and own is None and open_for_changes),
        "can_leave": bool(own and open_for_changes),
        "can_add_guest": bool(person.active and open_for_changes),
    }


@router.get("/me/games/{identifier}/history")
async def player_game_history(identifier:UUID, response:Response,
                              user=Depends(current_user), session:AsyncSession=Depends(get_session)):
    await own_person(session, user)
    response.headers["Cache-Control"] = "no-store"
    game = await d.get_or_404(session, WeeklyAttendance, identifier)
    key = f"weekly:{game.game_date.isoformat()}"
    rows = (await session.scalars(select(ProcessedConversationMessage).where(
        ProcessedConversationMessage.aggregate_key == key,
        ProcessedConversationMessage.message_type == "weekly_attendance",
        ProcessedConversationMessage.raw_text.is_not(None),
        ProcessedConversationMessage.status.in_(("applied", "unchanged", "stale")),
    ).order_by(ProcessedConversationMessage.occurred_at,
               ProcessedConversationMessage.source_ordinal,
               ProcessedConversationMessage.created_at,
               ProcessedConversationMessage.id))).all()
    return {"items": [{
        "id": row.id,
        "occurred_at": row.occurred_at,
        "sender_name": row.sender_name,
        "source": row.source,
        "text": row.raw_text,
        "status": row.status,
        "message_type": row.message_type,
    } for row in rows]}


@router.get("/me/monthly")
async def player_monthly(response:Response, month:int=Query(ge=1,le=12), year:int=Query(ge=2000,le=2200),
                         user=Depends(current_user), session:AsyncSession=Depends(get_session)):
    response.headers["Cache-Control"] = "no-store"
    person = await own_person(session, user)
    rows = (await session.scalars(select(MonthlySubscriber).where(
        MonthlySubscriber.month == month, MonthlySubscriber.year == year,
        MonthlySubscriber.deleted_at.is_(None),
    ).order_by(MonthlySubscriber.position))).all()
    items = [{"id": row.id, "person_id": row.person_id, "name": row.name,
              "position": row.position} for row in rows]
    own = next((item for item in items if item["person_id"] == person.id), None)
    current = monthly_reference_is_current(month, year)
    return {"items": items, "own_subscription": own,
            "can_join": bool(current and person.active and own is None and len(items) < 24),
            "can_leave": bool(current and own is not None)}


def require_current_month(month: int, year: int) -> None:
    if not monthly_reference_is_current(month, year):
        raise HTTPException(409, "Só é possível alterar a lista do mês atual.")


async def month_weekly_snapshots(session:AsyncSession, month:int, year:int, *, normalize=False):
    first = date(year, month, 1)
    last = date(year + (month == 12), month % 12 + 1, 1)
    games = (await session.scalars(select(WeeklyAttendance).where(
        WeeklyAttendance.game_date >= first, WeeklyAttendance.game_date < last,
    ).order_by(WeeklyAttendance.game_date))).all()
    result = {}
    for game in games:
        if d.starts(game) <= d.aware(d.now()):
            continue
        if normalize:
            await d.recalculate(session, game, source="system")
        entries = await d.active_entries(session, game.id)
        charges = (await session.scalars(select(Charge).where(
            Charge.type == "single", Charge.reference_date == game.game_date,
        ).order_by(Charge.person_id))).all()
        result[game.game_date] = (
            tuple((entry.person_id, entry.name, entry.status, entry.is_monthly_subscriber,
                   entry.owes_single_payment) for entry in entries),
            tuple((charge.person_id, charge.status, charge.amount_cents) for charge in charges),
        )
    return result


def enqueue_changed_month_weeklies(session, before, after):
    for game_date in sorted(before.keys() | after.keys()):
        if before.get(game_date) != after.get(game_date):
            enqueue_list_update(session, list_type="weekly_attendance", reference=game_date)


@router.post("/me/monthly")
async def player_monthly_join(month:int=Query(ge=1,le=12), year:int=Query(ge=2000,le=2200),
                              user=Depends(current_user), session:AsyncSession=Depends(get_session)):
    person = await own_person(session, user)
    if not person.active:
        raise HTTPException(403, "Cadastro de jogador inativo")
    require_current_month(month, year)
    reference = date(year, month, 1)
    await d.lock(session, f"monthly:{reference}")
    active = (await session.scalars(select(MonthlySubscriber).where(
        MonthlySubscriber.month == month, MonthlySubscriber.year == year,
        MonthlySubscriber.deleted_at.is_(None),
    ))).all()
    own = next((row for row in active if row.person_id == person.id), None)
    if own is None:
        if len(active) >= 24:
            raise HTTPException(409, "O mês já possui 24 assinantes")
        occupied = {row.position for row in active}
        position = next(value for value in range(1, 25) if value not in occupied)
        before_weeklies = await month_weekly_snapshots(session, month, year, normalize=True)
        updated = await d.monthly_upsert(session, person, month, year, has_paid=None,
                                         position=position, user=user, source="self_service")
        if updated is not None and updated.deleted_at is None:
            enqueue_list_update(session, list_type="monthly_subscribers", reference=reference)
            after_weeklies = await month_weekly_snapshots(session, month, year)
            enqueue_changed_month_weeklies(session, before_weeklies, after_weeklies)
    await session.commit()
    return {"ok": True}


@router.delete("/me/monthly")
async def player_monthly_leave(month:int=Query(ge=1,le=12), year:int=Query(ge=2000,le=2200),
                               user=Depends(current_user), session:AsyncSession=Depends(get_session)):
    person = await own_person(session, user)
    require_current_month(month, year)
    reference = date(year, month, 1)
    await d.lock(session, f"monthly:{reference}")
    row = await session.scalar(select(MonthlySubscriber).where(
        MonthlySubscriber.person_id == person.id, MonthlySubscriber.month == month,
        MonthlySubscriber.year == year, MonthlySubscriber.deleted_at.is_(None),
    ))
    if row is not None:
        before_weeklies = await month_weekly_snapshots(session, month, year, normalize=True)
        before_deleted_at = row.deleted_at
        await d.monthly_remove(session, row, user=user, source="self_service")
        if row.deleted_at != before_deleted_at:
            enqueue_list_update(session, list_type="monthly_subscribers", reference=reference)
            after_weeklies = await month_weekly_snapshots(session, month, year)
            enqueue_changed_month_weeklies(session, before_weeklies, after_weeklies)
    await session.commit()
    return {"ok": True}


@router.post("/me/games/{identifier}/join")
async def join(identifier:UUID,user=Depends(current_user),session:AsyncSession=Depends(get_session)):
    p=await own_person(session,user)
    if not p.active: raise HTTPException(403,"Cadastro de jogador inativo")
    g=await d.get_or_404(session,WeeklyAttendance,identifier)
    d.ensure_open(g)
    await d.lock(session, f"game:{g.id}")
    was_active = await session.scalar(select(WeeklyAttendanceEntry.id).where(
        WeeklyAttendanceEntry.attendance_id == g.id,
        WeeklyAttendanceEntry.person_id == p.id,
        WeeklyAttendanceEntry.deleted_at.is_(None),
    ).limit(1)) is not None
    if was_active:
        await session.commit()
        return {"ok": True}
    entry = await d.add_entry(session,g,p,user=user,source="self_service")
    if entry is not None and entry.deleted_at is None:
        enqueue_list_update(session, list_type="weekly_attendance", reference=g.game_date)
    await session.commit()
    return {"ok":True}


@router.delete("/me/games/{identifier}/join")
async def leave(identifier:UUID,user=Depends(current_user),session:AsyncSession=Depends(get_session)):
    p=await own_person(session,user)
    g=await d.get_or_404(session,WeeklyAttendance,identifier)
    d.ensure_open(g)
    await d.lock(session,f"game:{g.id}")
    entry=await session.scalar(select(WeeklyAttendanceEntry).where(WeeklyAttendanceEntry.attendance_id==g.id,WeeklyAttendanceEntry.person_id==p.id,WeeklyAttendanceEntry.deleted_at.is_(None)).limit(1))
    if entry:
        await d.remove_entry(session,g,entry,user=user,source="self_service",all_for_person=True)
        still_active = await session.scalar(select(WeeklyAttendanceEntry.id).where(
            WeeklyAttendanceEntry.attendance_id == g.id,
            WeeklyAttendanceEntry.person_id == p.id,
            WeeklyAttendanceEntry.deleted_at.is_(None),
        ).limit(1))
        if still_active is None:
            enqueue_list_update(session, list_type="weekly_attendance", reference=g.game_date)
    await session.commit()
    return {"ok":True}


@router.post("/me/games/{identifier}/guests")
async def player_guest_create(identifier:UUID, payload:GuestInput, user=Depends(current_user),
                              session:AsyncSession=Depends(get_session)):
    owner = await own_person(session, user)
    if not owner.active:
        raise HTTPException(403, "Cadastro de jogador inativo")
    game = await d.get_or_404(session, WeeklyAttendance, identifier)
    d.ensure_open(game)
    await d.lock(session, f"game:{game.id}")
    normalized = await resolve_normalized_name(session, normalize_name(payload.name))
    if not normalized:
        raise HTTPException(422, "Nome inválido")
    existing_person = await session.scalar(select(Person).where(Person.normalized_name == normalized))
    guest = await d.person_for_name(session, payload.name)
    if existing_person is None:
        await d.audit(session, entity_type="person", entity_id=guest.id, action="create",
                      user=user, person_id=guest.id, after=person_dict(guest),
                      source="self_service")
    if not guest.active:
        raise HTTPException(409, "O cadastro do convidado está inativo")
    if guest.id == owner.id:
        raise HTTPException(409, "Use sua própria inscrição para entrar na partida")
    active_entries = (await session.scalars(select(WeeklyAttendanceEntry).where(
        WeeklyAttendanceEntry.attendance_id == game.id,
        WeeklyAttendanceEntry.person_id == guest.id,
        WeeklyAttendanceEntry.deleted_at.is_(None),
    ))).all()
    if active_entries:
        is_own_guest = False
        for active_entry in active_entries:
            if active_entry.invited_by and await inviter_matches_owner(session, active_entry, owner):
                is_own_guest = True
                break
        if is_own_guest:
            await session.commit()
            return {"ok": True}
        raise HTTPException(409, "Este jogador já está inscrito nesta partida")
    guest_entry = await d.add_entry(session, game, guest, user=user, source="self_service",
                                    invited_by=owner.name, section="guests")
    if guest_entry is not None and guest_entry.deleted_at is None:
        enqueue_list_update(session, list_type="weekly_attendance", reference=game.game_date)
    await session.commit()
    return {"ok": True}


@router.delete("/me/games/{identifier}/guests/{entry_id}")
async def player_guest_delete(identifier:UUID, entry_id:UUID, user=Depends(current_user),
                              session:AsyncSession=Depends(get_session)):
    owner = await own_person(session, user)
    game, entry = await entry_for_game(session, identifier, entry_id, lock_game=True)
    d.ensure_open(game)
    if entry.person_id == owner.id:
        raise HTTPException(409, "Sua inscrição deve ser removida pelo controle de entrada da partida")
    if not entry.invited_by or not await inviter_matches_owner(session, entry, owner):
        raise HTTPException(404, "Convidado não encontrado")
    before_deleted_at = entry.deleted_at
    await d.remove_entry(session, game, entry, user=user, source="self_service")
    if entry.deleted_at != before_deleted_at:
        enqueue_list_update(session, list_type="weekly_attendance", reference=game.game_date)
    await session.commit()
    return {"ok": True}
