import asyncio
import json
import httpx

from app.conversation_ai import OpenAICompatibleConversationAnalyzer
from app.conversation_import import (
    _get_latest_weekly_batch_messages,
    _is_stale,
    _messages_after_position,
    prepare_conversation_messages,
)
from app.whatsapp_export import parse_whatsapp_export


def test_prepare_conversation_recognizes_real_export_formats_without_ai() -> None:
    messages = parse_whatsapp_export(
        """09/12/2024 18:00 - Pessoa: conversa comum
09/12/2024 18:02 - Pessoa: Lista pagamento mensal Frederico
1. Pessoa ✅
2. Outra
11/12/2024 06:00 - Pessoa: 🏐 Vôlei Frederico 19h30 🏐
1. Pessoa
2. Outra (Convidado)
"""
    )

    prepared = asyncio.run(
        prepare_conversation_messages(
            messages,
            chat_id="fred",
            analysis_mode="rules",
        )
    )

    assert [item.message_type for item in prepared.messages] == [
        "ignored",
        "monthly_subscribers",
        "weekly_attendance",
    ]
    assert prepared.messages[1].aggregate_key == "monthly:2024-12"
    assert prepared.messages[2].aggregate_key == "weekly:2024-12-11"


def test_full_export_starts_after_last_processed_position() -> None:
    messages = parse_whatsapp_export(
        """09/12/2024 18:00 - Pessoa: conversa comum
09/12/2024 18:02 - Pessoa: Lista pagamento mensal Frederico
1. Pessoa
11/12/2024 06:00 - Pessoa: Lista Volei Frederico 11/12
1. Pessoa
"""
    )

    remaining = _messages_after_position(
        messages,
        position=(messages[1].occurred_at, messages[1].ordinal),
    )

    assert [message.ordinal for message in remaining] == [2]


def test_hybrid_mode_warns_when_ai_is_not_configured() -> None:
    messages = parse_whatsapp_export("09/12/2024 18:00 - Pessoa: conversa comum")
    analyzer = OpenAICompatibleConversationAnalyzer(base_url="", model="")

    prepared = asyncio.run(
        prepare_conversation_messages(
            messages,
            chat_id="fred",
            analysis_mode="hybrid",
            analyzer=analyzer,
        )
    )

    assert prepared.ai_analyzed_messages == 0
    assert prepared.warnings


def test_hybrid_mode_warns_when_ai_request_fails() -> None:
    messages = parse_whatsapp_export("09/12/2024 18:00 - Pessoa: conversa comum")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    analyzer = OpenAICompatibleConversationAnalyzer(
        base_url="http://ai.test/v1",
        model="test-model",
        attempts=1,
        transport=httpx.MockTransport(handler),
    )

    prepared = asyncio.run(
        prepare_conversation_messages(
            messages,
            chat_id="fred",
            analysis_mode="hybrid",
            analyzer=analyzer,
        )
    )

    assert prepared.ai_analyzed_messages == 0
    assert "IA falhou" in prepared.warnings[0]


def test_hybrid_mode_sends_only_locally_ignored_messages_to_ai() -> None:
    messages = parse_whatsapp_export(
        """09/12/2024 18:00 - Pessoa: conversa comum
09/12/2024 18:02 - Pessoa: Lista pagamento mensal Frederico
1. Pessoa ✅
"""
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        request_body = json.loads(request.content)
        user_payload = json.loads(request_body["messages"][1]["content"])
        assert [message["id"] for message in user_payload["messages"]] == [0]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "messages": [
                                        {
                                            "id": 0,
                                            "kind": "ignore",
                                            "confidence": 1,
                                            "month": None,
                                            "year": None,
                                            "game_date": None,
                                            "reason": "conversa",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    analyzer = OpenAICompatibleConversationAnalyzer(
        base_url="http://ai.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    prepared = asyncio.run(
        prepare_conversation_messages(
            messages,
            chat_id="fred",
            analysis_mode="hybrid",
            analyzer=analyzer,
        )
    )

    assert prepared.ai_analyzed_messages == 1
    assert [item.message_type for item in prepared.messages] == [
        "ignored",
        "monthly_subscribers",
    ]


def test_hybrid_mode_keeps_successful_ai_batches_when_one_batch_fails() -> None:
    messages = parse_whatsapp_export(
        """09/12/2024 18:00 - Pessoa: conversa comum
09/12/2024 18:01 - Pessoa: outra conversa
"""
    )

    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        request_body = json.loads(request.content)
        user_payload = json.loads(request_body["messages"][1]["content"])
        message_id = user_payload["messages"][0]["id"]
        if calls == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "messages": [
                                            {
                                                "id": message_id,
                                                "kind": "ignore",
                                                "confidence": 1,
                                                "month": None,
                                                "year": None,
                                                "game_date": None,
                                                "reason": "conversa",
                                            }
                                        ]
                                    }
                                )
                            }
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"messages": []})
                        }
                    }
                ]
            },
        )

    analyzer = OpenAICompatibleConversationAnalyzer(
        base_url="http://ai.test/v1",
        model="test-model",
        attempts=1,
        batch_messages=1,
        transport=httpx.MockTransport(handler),
    )
    prepared = asyncio.run(
        prepare_conversation_messages(
            messages,
            chat_id="fred",
            analysis_mode="hybrid",
            analyzer=analyzer,
        )
    )

    assert prepared.ai_analyzed_messages == 1
    assert prepared.warnings
    assert "IA falhou em um lote" in prepared.warnings[0]


def test_participants_list_is_monthly_and_virtual_attendance_requires_review() -> None:
    messages = parse_whatsapp_export(
        """03/01/2025 15:59 - Pessoa: Lista Participantes
1. Pessoa
18/02/2026 15:57 - Pessoa: LISTA VOLEI FREDERICO 18/02
1. Pessoa - *virtualmente*
"""
    )

    prepared = asyncio.run(
        prepare_conversation_messages(
            messages,
            chat_id="fred",
            analysis_mode="rules",
        )
    )

    assert [item.message_type for item in prepared.messages] == [
        "monthly_subscribers",
        "review_required",
    ]
    assert prepared.messages[0].aggregate_key == "monthly:2025-01"
    assert all(item.analyzer == "rules" for item in prepared.messages)


def test_weekly_import_keeps_only_latest_batch_message_for_same_game_date() -> None:
    messages = parse_whatsapp_export(
        """30/12/2024 18:00 - Pessoa: 🏐 Vôlei Frederico 19h30 🏐
1. Pessoa
31/12/2024 19:00 - Pessoa: 🏐 Vôlei Frederico 19h30 🏐
1. Pessoa
2. Outra
01/01/2025 08:00 - Pessoa: 🏐 Vôlei Frederico 19h30 🏐
1. Pessoa
2. Outra
3. Terceira
"""
    )

    prepared = asyncio.run(
        prepare_conversation_messages(
            messages,
            chat_id="fred",
            analysis_mode="rules",
        )
    )
    weekly_messages = [
        item for item in prepared.messages if item.message_type == "weekly_attendance"
    ]
    latest = _get_latest_weekly_batch_messages(prepared.messages)

    assert [item.aggregate_key for item in weekly_messages] == [
        "weekly:2025-01-01",
        "weekly:2025-01-01",
        "weekly:2025-01-01",
    ]
    assert [_is_stale(item, {}, latest) for item in weekly_messages] == [
        True,
        True,
        False,
    ]
