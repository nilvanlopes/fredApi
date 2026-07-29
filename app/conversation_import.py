from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_conversation_ai_confidence_threshold
from app.conversation_ai import (
    AIClassification,
    AICleanedName,
    ConversationAIError,
    OpenAICompatibleConversationAnalyzer,
    WeeklyNameCleanupInput,
)
from app.models import ProcessedConversationMessage
from app.ollama_service import managed_ollama_service
from app.parser import (
    ParseError,
    ParsedMonthlySubscribers,
    ParsedWeeklyAttendance,
    parse_monthly_subscribers_message,
    parse_weekly_attendance_message,
    normalize_spaces,
    normalize_name,
)
from app.schemas import (
    ConversationImportMessageResult,
    ConversationImportResponse,
    ProcessMessageResponse,
    WeeklyAttendanceResponse,
)
from app.services import (
    apply_monthly_subscribers,
    apply_weekly_attendance,
)
from app.whatsapp_export import WhatsAppMessage, parse_whatsapp_export


ImportMode = Literal["preview", "apply"]
AnalysisMode = Literal["rules", "hybrid", "ai"]
MessageType = Literal[
    "monthly_subscribers",
    "weekly_attendance",
    "ignored",
    "review_required",
]
RESULT_LIMIT = 200


def realtime_message_fingerprint(
    *,
    chat_id: str,
    occurred_at: datetime,
    sender_name: str | None,
    text: str,
) -> str:
    """Build the same content fingerprint used by WhatsApp exports.

    The realtime webhook does not have the export ordinal, so the fingerprint
    intentionally uses the stable message fields shared by both ingestion
    paths.  A provider message id is kept as metadata, but is not part of this
    key because it is not present in a WhatsApp text export.
    """
    value = "\0".join(
        (chat_id, occurred_at.isoformat(), sender_name or "", text)
    )
    return sha256(value.encode("utf-8")).hexdigest()


async def record_realtime_processed_message(
    session: AsyncSession,
    *,
    chat_id: str,
    text: str,
    occurred_at: datetime,
    sender_name: str | None,
    message_id: str | None,
    source: str | None,
    message_type: Literal["monthly_subscribers", "weekly_attendance"],
    aggregate_key: str,
    status: Literal["applied", "unchanged"],
    result: dict,
) -> None:
    """Record a message accepted by the direct/n8n ingestion path."""
    normalized_occurred_at = (
        occurred_at
        if occurred_at.tzinfo is not None
        else occurred_at.replace(tzinfo=timezone.utc)
    )
    await _record_processed_message_values(
        session,
        fingerprint=realtime_message_fingerprint(
            chat_id=chat_id,
            occurred_at=normalized_occurred_at,
            sender_name=sender_name,
            text=text,
        ),
        chat_id=chat_id,
        source_ordinal=0,
        occurred_at=normalized_occurred_at,
        sender_name=sender_name,
        message_type=message_type,
        aggregate_key=aggregate_key,
        status=status,
        analyzer="rules",
        confidence=1.0,
        analysis={
            "source": source or "realtime",
            "message_id": message_id,
            "ingestion": "realtime",
        },
        result=result,
    )


@dataclass(frozen=True)
class PreparedMessage:
    message: WhatsAppMessage
    fingerprint: str
    message_type: MessageType
    analyzer: Literal["rules", "ai"]
    confidence: float
    reason: str
    aggregate_key: str | None = None
    parsed: ParsedMonthlySubscribers | ParsedWeeklyAttendance | None = None


@dataclass(frozen=True)
class PreparationResult:
    messages: list[PreparedMessage]
    ai_analyzed_messages: int
    warnings: list[str]


async def process_conversation_import(
    session: AsyncSession,
    *,
    text: str,
    mode: ImportMode,
    analysis_mode: AnalysisMode,
    chat_id: str,
    timezone_name: str,
    analyzer: OpenAICompatibleConversationAnalyzer | None = None,
) -> ConversationImportResponse:
    all_source_messages = parse_whatsapp_export(text, timezone_name=timezone_name)
    last_processed_position = await _get_last_processed_position(
        session,
        chat_id=chat_id,
    )
    source_messages = _messages_after_position(
        all_source_messages,
        position=last_processed_position,
    )
    unique_messages, repeated_in_file = _deduplicate_export_messages(
        source_messages,
        chat_id=chat_id,
    )
    existing_fingerprints = await _get_existing_fingerprints(
        session,
        [message.fingerprint(chat_id=chat_id) for message in unique_messages],
    )
    await session.rollback()
    new_source_messages = [
        message
        for message in unique_messages
        if message.fingerprint(chat_id=chat_id) not in existing_fingerprints
    ]

    should_manage_ollama = (
        analysis_mode != "rules" and analyzer is None and bool(new_source_messages)
    )
    async with managed_ollama_service(enabled=should_manage_ollama):
        preparation = await prepare_conversation_messages(
            new_source_messages,
            chat_id=chat_id,
            analysis_mode=analysis_mode,
            analyzer=analyzer,
        )
        aggregate_cursors = await _get_aggregate_cursors(
            session,
            chat_id=chat_id,
            aggregate_keys={
                item.aggregate_key
                for item in preparation.messages
                if item.aggregate_key is not None
            },
        )
        latest_weekly_batch_messages = _get_latest_weekly_batch_messages(
            preparation.messages
        )
        prepared_messages = preparation.messages
        if analysis_mode != "rules":
            analyzer = analyzer or OpenAICompatibleConversationAnalyzer()
            prepared_messages, cleanup_warnings = await _clean_weekly_names_with_ai(
                prepared_messages,
                analyzer=analyzer,
                aggregate_cursors=aggregate_cursors,
                latest_weekly_batch_messages=latest_weekly_batch_messages,
                require_ai=analysis_mode == "ai",
            )
            preparation.warnings.extend(cleanup_warnings)

        counters = {
            "relevant": 0,
            "changed": 0,
            "unchanged": 0,
            "ignored": 0,
            "stale": 0,
            "review_required": 0,
        }
        results: list[ConversationImportMessageResult] = []

        try:
            for item in sorted(
                prepared_messages,
                key=lambda value: (value.message.occurred_at, value.message.ordinal),
            ):
                outcome = await _process_prepared_message(
                    session,
                    item=item,
                    mode=mode,
                    chat_id=chat_id,
                    aggregate_cursors=aggregate_cursors,
                    latest_weekly_batch_messages=latest_weekly_batch_messages,
                )
                _increment_counters(counters, outcome)
                if outcome.message_type != "ignored" and len(results) < RESULT_LIMIT:
                    results.append(outcome)

            if mode == "apply":
                await session.commit()
            else:
                await session.rollback()
        except Exception:
            await session.rollback()
            raise

        duplicate_messages = len(existing_fingerprints) + repeated_in_file
        result_count = counters["relevant"] + counters["review_required"] + counters["stale"]
        return ConversationImportResponse(
            mode=mode,
            analysis_mode=analysis_mode,
            chat_id=chat_id,
            total_messages=len(all_source_messages),
            new_messages=len(new_source_messages),
            ai_analyzed_messages=preparation.ai_analyzed_messages,
            relevant_messages=counters["relevant"],
            changed_messages=counters["changed"],
            unchanged_messages=counters["unchanged"],
            ignored_messages=counters["ignored"],
            duplicate_messages=duplicate_messages,
            stale_messages=counters["stale"],
            review_required_messages=counters["review_required"],
            results=results,
            results_truncated=max(result_count - len(results), 0),
            warnings=preparation.warnings,
        )


async def prepare_conversation_messages(
    messages: list[WhatsAppMessage],
    *,
    chat_id: str,
    analysis_mode: AnalysisMode,
    analyzer: OpenAICompatibleConversationAnalyzer | None = None,
) -> PreparationResult:
    ai_classifications: dict[int, AIClassification] = {}
    warnings: list[str] = []
    ai_analyzed_messages = 0
    prepared = [
        _prepare_message(
            message,
            chat_id=chat_id,
            ai_classification=None,
        )
        for message in messages
    ]

    if analysis_mode != "rules" and messages:
        analyzer = analyzer or OpenAICompatibleConversationAnalyzer()
        if analyzer.is_configured:
            ai_candidate_messages = (
                messages
                if analysis_mode == "ai"
                else [
                    item.message
                    for item in prepared
                    if item.message_type == "ignored"
                ]
            )
            try:
                if ai_candidate_messages:
                    if analysis_mode == "ai":
                        ai_classifications = await analyzer.classify(ai_candidate_messages)
                    else:
                        ai_classifications, partial_warnings = (
                            await analyzer.classify_best_effort(ai_candidate_messages)
                        )
                        warnings.extend(partial_warnings)
                    ai_analyzed_messages = len(ai_classifications)
            except ConversationAIError as exc:
                if analysis_mode == "ai":
                    raise
                warnings.append(
                    "IA falhou; o modo hybrid usou somente os formatos deterministas: "
                    f"{str(exc)[:500]}"
                )
        elif analysis_mode == "ai":
            raise ConversationAIError(
                "analysis_mode=ai exige CONVERSATION_AI_BASE_URL e CONVERSATION_AI_MODEL"
            )
        else:
            warnings.append(
                "IA nao configurada; o modo hybrid usou somente os formatos deterministas"
            )

    if ai_classifications:
        prepared = [
            (
                _prepare_message(
                    item.message,
                    chat_id=chat_id,
                    ai_classification=ai_classifications[item.message.ordinal],
                )
                if item.message.ordinal in ai_classifications
                else item
            )
            for item in prepared
        ]
    return PreparationResult(
        messages=prepared,
        ai_analyzed_messages=ai_analyzed_messages,
        warnings=warnings,
    )


def _prepare_message(
    message: WhatsAppMessage,
    *,
    chat_id: str,
    ai_classification: AIClassification | None,
) -> PreparedMessage:
    fingerprint = message.fingerprint(chat_id=chat_id)
    if message.sender_name is None or not message.text:
        return _ignored(message, fingerprint=fingerprint)
    if ai_classification is not None and ai_classification.kind == "review_required":
        return _review_required(
            message,
            fingerprint=fingerprint,
            confidence=ai_classification.confidence,
            reason=ai_classification.reason or "classificacao exige revisao",
        )
    normalized_title = normalize_name(message.text.splitlines()[0])
    if "virtualmente" in normalize_name(message.text):
        return _review_required(
            message,
            fingerprint=fingerprint,
            confidence=1.0,
            reason="presenca virtual nao possui regra de persistencia",
            analyzer="rules",
        )

    try:
        monthly = parse_monthly_subscribers_message(
            message.text,
            received_at=message.occurred_at,
        )
        return PreparedMessage(
            message=message,
            fingerprint=fingerprint,
            message_type="monthly_subscribers",
            analyzer="rules",
            confidence=1.0,
            reason="formato mensal reconhecido",
            aggregate_key=f"monthly:{monthly.year:04d}-{monthly.month:02d}",
            parsed=monthly,
        )
    except ParseError:
        pass

    try:
        weekly = parse_weekly_attendance_message(
            message.text,
            received_at=message.occurred_at,
        )
        return PreparedMessage(
            message=message,
            fingerprint=fingerprint,
            message_type="weekly_attendance",
            analyzer="rules",
            confidence=1.0,
            reason="formato semanal reconhecido",
            aggregate_key=f"weekly:{weekly.game_date.isoformat()}",
            parsed=weekly,
        )
    except ParseError:
        pass

    if ai_classification is None or ai_classification.kind == "ignore":
        return _ignored(
            message,
            fingerprint=fingerprint,
            analyzer="ai" if ai_classification is not None else "rules",
            confidence=ai_classification.confidence if ai_classification else 1.0,
            reason=(
                ai_classification.reason
                if ai_classification
                else "formato sem efeito reconhecido"
            ),
        )

    threshold = get_conversation_ai_confidence_threshold()
    if ai_classification.confidence < threshold:
        return _review_required(
            message,
            fingerprint=fingerprint,
            confidence=ai_classification.confidence,
            reason=ai_classification.reason or "classificacao exige revisao",
        )

    try:
        if ai_classification.kind == "monthly_subscribers":
            parsed = parse_monthly_subscribers_message(
                message.text,
                received_at=message.occurred_at,
                month_hint=ai_classification.month,
                year_hint=ai_classification.year,
                allow_unrecognized_header=True,
            )
            return PreparedMessage(
                message=message,
                fingerprint=fingerprint,
                message_type="monthly_subscribers",
                analyzer="ai",
                confidence=ai_classification.confidence,
                reason=ai_classification.reason,
                aggregate_key=f"monthly:{parsed.year:04d}-{parsed.month:02d}",
                parsed=parsed,
            )

        parsed = parse_weekly_attendance_message(
            message.text,
            received_at=message.occurred_at,
            game_date_hint=ai_classification.game_date,
            allow_unrecognized_header=True,
        )
        return PreparedMessage(
            message=message,
            fingerprint=fingerprint,
            message_type="weekly_attendance",
            analyzer="ai",
            confidence=ai_classification.confidence,
            reason=ai_classification.reason,
            aggregate_key=f"weekly:{parsed.game_date.isoformat()}",
            parsed=parsed,
        )
    except ParseError as exc:
        return _review_required(
            message,
            fingerprint=fingerprint,
            confidence=ai_classification.confidence,
            reason=f"extracao da IA nao passou no parser local: {exc}",
        )


async def _process_prepared_message(
    session: AsyncSession,
    *,
    item: PreparedMessage,
    mode: ImportMode,
    chat_id: str,
    aggregate_cursors: dict[str, datetime],
    latest_weekly_batch_messages: dict[str, tuple[datetime, int]],
) -> ConversationImportMessageResult:
    if mode == "apply" and item.message_type in {
        "monthly_subscribers",
        "weekly_attendance",
    }:
        if await _processed_fingerprint_exists(session, item.fingerprint):
            return ConversationImportMessageResult(
                fingerprint=item.fingerprint,
                occurred_at=item.message.occurred_at,
                sender_name=item.message.sender_name,
                message_type=item.message_type,
                status="unchanged",
                analyzer=item.analyzer,
                confidence=item.confidence,
                aggregate_key=item.aggregate_key,
                reason="mensagem ja processada",
                result={},
            )

    if item.message_type == "ignored":
        status = "ignored"
        result: dict = {}
    elif item.message_type == "review_required":
        status = "review_required"
        result = {}
    elif _is_stale(item, aggregate_cursors, latest_weekly_batch_messages):
        status = "stale"
        result = {}
    else:
        response = await _apply_domain_message(session, item=item)
        changed = _response_has_changes(response)
        status = (
            "would_apply"
            if mode == "preview" and changed
            else "would_be_unchanged"
            if mode == "preview"
            else "applied"
            if changed
            else "unchanged"
        )
        result = response.model_dump(mode="json")
        if item.aggregate_key is not None:
            aggregate_cursors[item.aggregate_key] = item.message.occurred_at

    persisted_status = {
        "would_apply": "applied",
        "would_be_unchanged": "unchanged",
    }.get(status, status)
    analysis = {
        "reason": item.reason,
        "source_timestamp": item.message.occurred_at.isoformat(),
    }
    if mode == "apply" and item.message_type in {
        "monthly_subscribers",
        "weekly_attendance",
    }:
        await _record_processed_message(
            session,
            item=item,
            chat_id=chat_id,
            status=persisted_status,
            analysis=analysis,
            result=result,
        )

    return ConversationImportMessageResult(
        fingerprint=item.fingerprint,
        occurred_at=item.message.occurred_at,
        sender_name=item.message.sender_name,
        message_type=item.message_type,
        status=status,
        analyzer=item.analyzer,
        confidence=item.confidence,
        aggregate_key=item.aggregate_key,
        reason=item.reason,
        result=result,
    )


async def _processed_fingerprint_exists(
    session: AsyncSession,
    fingerprint: str,
) -> bool:
    with session.no_autoflush:
        result = await session.execute(
            select(ProcessedConversationMessage.id)
            .where(ProcessedConversationMessage.fingerprint == fingerprint)
            .limit(1)
        )
    return result.scalar_one_or_none() is not None


async def _record_processed_message(
    session: AsyncSession,
    *,
    item: PreparedMessage,
    chat_id: str,
    status: str,
    analysis: dict,
    result: dict,
) -> None:
    await _record_processed_message_values(
        session,
        fingerprint=item.fingerprint,
        chat_id=chat_id,
        source_ordinal=item.message.ordinal,
        occurred_at=item.message.occurred_at,
        sender_name=item.message.sender_name,
        message_type=item.message_type,
        aggregate_key=item.aggregate_key,
        status=status,
        analyzer=item.analyzer,
        confidence=item.confidence,
        analysis=analysis,
        result=result,
    )


async def _record_processed_message_values(
    session: AsyncSession,
    *,
    fingerprint: str,
    chat_id: str,
    source_ordinal: int,
    occurred_at: datetime,
    sender_name: str | None,
    message_type: str,
    aggregate_key: str | None,
    status: str,
    analyzer: str,
    confidence: float,
    analysis: dict,
    result: dict,
) -> None:
    statement = (
        postgresql_insert(ProcessedConversationMessage)
        .values(
            id=uuid4(),
            fingerprint=fingerprint,
            chat_id=chat_id,
            source_ordinal=source_ordinal,
            occurred_at=occurred_at,
            sender_name=sender_name,
            message_type=message_type,
            aggregate_key=aggregate_key,
            status=status,
            analyzer=analyzer,
            confidence=confidence,
            analysis=analysis,
            result=result,
        )
        .on_conflict_do_nothing(
            constraint="uq_processed_conversation_messages_fingerprint"
        )
    )
    await session.execute(statement)


async def _clean_weekly_names_with_ai(
    messages: list[PreparedMessage],
    *,
    analyzer: OpenAICompatibleConversationAnalyzer,
    aggregate_cursors: dict[str, datetime],
    latest_weekly_batch_messages: dict[str, tuple[datetime, int]],
    require_ai: bool,
) -> tuple[list[PreparedMessage], list[str]]:
    if not analyzer.is_configured:
        if require_ai:
            raise ConversationAIError(
                "analysis_mode=ai exige CONVERSATION_AI_BASE_URL e CONVERSATION_AI_MODEL"
            )
        return messages, ["IA nao configurada; limpeza semantica de nomes nao executada"]

    inputs = _build_weekly_name_cleanup_inputs(
        messages,
        aggregate_cursors=aggregate_cursors,
        latest_weekly_batch_messages=latest_weekly_batch_messages,
    )
    if not inputs:
        return messages, []

    try:
        cleanups = await analyzer.clean_weekly_names(inputs)
    except ConversationAIError as exc:
        if require_ai:
            raise
        return messages, [
            "IA falhou; limpeza semantica de nomes nao executada: "
            f"{str(exc)[:500]}"
        ]

    threshold = get_conversation_ai_confidence_threshold()
    return _apply_weekly_name_cleanups(messages, cleanups, threshold=threshold), []


def _build_weekly_name_cleanup_inputs(
    messages: list[PreparedMessage],
    *,
    aggregate_cursors: dict[str, datetime],
    latest_weekly_batch_messages: dict[str, tuple[datetime, int]],
) -> list[WeeklyNameCleanupInput]:
    inputs: list[WeeklyNameCleanupInput] = []
    for item in messages:
        if item.message_type != "weekly_attendance":
            continue
        if not isinstance(item.parsed, ParsedWeeklyAttendance):
            continue
        if _is_stale(item, aggregate_cursors, latest_weekly_batch_messages):
            continue
        for entry in item.parsed.entries:
            inputs.append(
                WeeklyNameCleanupInput(
                    id=_weekly_name_cleanup_id(item, entry),
                    game_date=item.parsed.game_date,
                    section=entry.section,
                    position=entry.position,
                    name=entry.name,
                    invited_by=entry.invited_by,
                )
            )
    return inputs


def _apply_weekly_name_cleanups(
    messages: list[PreparedMessage],
    cleanups: dict[str, AICleanedName],
    *,
    threshold: float,
) -> list[PreparedMessage]:
    cleaned_messages: list[PreparedMessage] = []
    for item in messages:
        if item.message_type != "weekly_attendance" or not isinstance(
            item.parsed, ParsedWeeklyAttendance
        ):
            cleaned_messages.append(item)
            continue

        changed = False
        cleaned_entries = []
        for entry in item.parsed.entries:
            cleanup = cleanups.get(_weekly_name_cleanup_id(item, entry))
            if cleanup is None or cleanup.confidence < threshold:
                cleaned_entries.append(entry)
                continue
            clean_name = normalize_spaces(cleanup.clean_name)
            if normalize_name(clean_name) == entry.normalized_name:
                cleaned_entries.append(entry)
                continue
            cleaned_entries.append(
                replace(
                    entry,
                    name=clean_name,
                    normalized_name=normalize_name(clean_name),
                )
            )
            changed = True

        if not changed:
            cleaned_messages.append(item)
            continue
        cleaned_messages.append(
            replace(
                item,
                analyzer="ai",
                reason=f"{item.reason}; nomes limpos por IA",
                parsed=replace(item.parsed, entries=cleaned_entries),
            )
        )
    return cleaned_messages


def _weekly_name_cleanup_id(item: PreparedMessage, entry) -> str:
    return f"{item.message.ordinal}:{entry.section}:{entry.position}"


async def _apply_domain_message(
    session: AsyncSession,
    *,
    item: PreparedMessage,
) -> ProcessMessageResponse | WeeklyAttendanceResponse:
    if item.message_type == "monthly_subscribers":
        if not isinstance(item.parsed, ParsedMonthlySubscribers):
            raise RuntimeError("evento mensal sem payload validado")
        return await apply_monthly_subscribers(
            session,
            parsed=item.parsed,
            commit=False,
        )
    if not isinstance(item.parsed, ParsedWeeklyAttendance):
        raise RuntimeError("evento semanal sem payload validado")
    return await apply_weekly_attendance(
        session,
        parsed=item.parsed,
        received_at=item.message.occurred_at,
        commit=False,
    )


def _response_has_changes(
    response: ProcessMessageResponse | WeeklyAttendanceResponse,
) -> bool:
    if isinstance(response, ProcessMessageResponse):
        return bool(response.created or response.updated or response.deleted)
    return True


def _is_stale(
    item: PreparedMessage,
    aggregate_cursors: dict[str, datetime],
    latest_weekly_batch_messages: dict[str, tuple[datetime, int]],
) -> bool:
    if item.aggregate_key is None:
        return False
    cursor = aggregate_cursors.get(item.aggregate_key)
    if cursor is not None and item.message.occurred_at < cursor:
        return True
    if item.message_type != "weekly_attendance":
        return False
    latest_batch_message = latest_weekly_batch_messages.get(item.aggregate_key)
    if latest_batch_message is None:
        return False
    return (item.message.occurred_at, item.message.ordinal) < latest_batch_message


def _get_latest_weekly_batch_messages(
    messages: list[PreparedMessage],
) -> dict[str, tuple[datetime, int]]:
    latest: dict[str, tuple[datetime, int]] = {}
    for item in messages:
        if item.message_type != "weekly_attendance" or item.aggregate_key is None:
            continue
        current = (item.message.occurred_at, item.message.ordinal)
        previous = latest.get(item.aggregate_key)
        if previous is None or previous < current:
            latest[item.aggregate_key] = current
    return latest


def _increment_counters(
    counters: dict[str, int],
    outcome: ConversationImportMessageResult,
) -> None:
    if outcome.status == "ignored":
        counters["ignored"] += 1
    elif outcome.status == "review_required":
        counters["review_required"] += 1
    elif outcome.status == "stale":
        counters["stale"] += 1
    else:
        counters["relevant"] += 1
        if outcome.status in {"applied", "would_apply"}:
            counters["changed"] += 1
        else:
            counters["unchanged"] += 1


def _ignored(
    message: WhatsAppMessage,
    *,
    fingerprint: str,
    analyzer: Literal["rules", "ai"] = "rules",
    confidence: float = 1.0,
    reason: str = "mensagem ignorada",
) -> PreparedMessage:
    return PreparedMessage(
        message=message,
        fingerprint=fingerprint,
        message_type="ignored",
        analyzer=analyzer,
        confidence=confidence,
        reason=reason,
    )


def _review_required(
    message: WhatsAppMessage,
    *,
    fingerprint: str,
    confidence: float,
    reason: str,
    analyzer: Literal["rules", "ai"] = "ai",
) -> PreparedMessage:
    return PreparedMessage(
        message=message,
        fingerprint=fingerprint,
        message_type="review_required",
        analyzer=analyzer,
        confidence=confidence,
        reason=reason,
    )


def _deduplicate_export_messages(
    messages: list[WhatsAppMessage],
    *,
    chat_id: str,
) -> tuple[list[WhatsAppMessage], int]:
    unique: list[WhatsAppMessage] = []
    seen: set[str] = set()
    for message in messages:
        fingerprint = message.fingerprint(chat_id=chat_id)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(message)
    return unique, len(messages) - len(unique)


async def _get_existing_fingerprints(
    session: AsyncSession,
    fingerprints: list[str],
) -> set[str]:
    existing: set[str] = set()
    for offset in range(0, len(fingerprints), 1000):
        chunk = fingerprints[offset : offset + 1000]
        if not chunk:
            continue
        result = await session.execute(
            select(ProcessedConversationMessage.fingerprint).where(
                ProcessedConversationMessage.fingerprint.in_(chunk)
            )
        )
        existing.update(result.scalars().all())
    return existing


async def _get_last_processed_position(
    session: AsyncSession,
    *,
    chat_id: str,
) -> tuple[datetime, int] | None:
    result = await session.execute(
        select(
            ProcessedConversationMessage.occurred_at,
            ProcessedConversationMessage.source_ordinal,
        )
        .where(
            ProcessedConversationMessage.chat_id == chat_id,
            ProcessedConversationMessage.status.in_(('applied', 'unchanged')),
        )
        .order_by(
            ProcessedConversationMessage.occurred_at.desc(),
            ProcessedConversationMessage.source_ordinal.desc(),
        )
        .limit(1)
    )
    return result.one_or_none()


def _messages_after_position(
    messages: list[WhatsAppMessage],
    *,
    position: tuple[datetime, int] | None,
) -> list[WhatsAppMessage]:
    if position is None:
        return messages
    last_occurred_at, last_source_ordinal = position
    return [
        message
        for message in messages
        if (message.occurred_at, message.ordinal)
        > (last_occurred_at, last_source_ordinal)
    ]


async def _get_aggregate_cursors(
    session: AsyncSession,
    *,
    chat_id: str,
    aggregate_keys: set[str],
) -> dict[str, datetime]:
    if not aggregate_keys:
        return {}
    result = await session.execute(
        select(
            ProcessedConversationMessage.aggregate_key,
            func.max(ProcessedConversationMessage.occurred_at),
        )
        .where(
            ProcessedConversationMessage.chat_id == chat_id,
            ProcessedConversationMessage.aggregate_key.in_(aggregate_keys),
            ProcessedConversationMessage.status.in_(("applied", "unchanged")),
        )
        .group_by(ProcessedConversationMessage.aggregate_key)
    )
    return {aggregate_key: occurred_at for aggregate_key, occurred_at in result.all()}
