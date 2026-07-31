import asyncio
from datetime import date
import json

import httpx

from app.conversation_ai import (
    ConversationAIError,
    OpenAICompatibleConversationAnalyzer,
    WeeklyNameCleanupInput,
)
from app.whatsapp_export import parse_whatsapp_export


def test_openai_compatible_analyzer_validates_structured_response() -> None:
    messages = parse_whatsapp_export(
        """09/12/2024 18:00 - Pessoa: conversa comum
09/12/2024 18:02 - Pessoa: Lista pagamento mensal Frederico
1. Pessoa ✅
"""
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        request_body = json.loads(request.content)
        user_payload = json.loads(request_body["messages"][1]["content"])
        assert len(user_payload["messages"]) == 2
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
                                        },
                                        {
                                            "id": 1,
                                            "kind": "monthly_subscribers",
                                            "confidence": 0.99,
                                            "month": 12,
                                            "year": 2024,
                                            "game_date": None,
                                            "reason": "lista mensal",
                                        },
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
    result = asyncio.run(analyzer.classify(messages))

    assert result[0].kind == "ignore"
    assert result[1].kind == "monthly_subscribers"
    assert (result[1].month, result[1].year) == (12, 2024)


def test_openai_compatible_analyzer_cleans_weekly_names() -> None:
    entries = [
        WeeklyNameCleanupInput(
            id="10:main:1",
            game_date=date(2026, 8, 5),
            section="main",
            position=1,
            name="Gomes (bem provavelmente) 🏐",
            invited_by=None,
        ),
        WeeklyNameCleanupInput(
            id="10:main:2",
            game_date=date(2026, 8, 5),
            section="main",
            position=2,
            name="Daniel depois das 20",
            invited_by=None,
        ),
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        request_body = json.loads(request.content)
        user_payload = json.loads(request_body["messages"][1]["content"])
        assert [entry["id"] for entry in user_payload["entries"]] == [
            "10:main:1",
            "10:main:2",
        ]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "entries": [
                                        {
                                            "id": "10:main:1",
                                            "clean_name": "Gomes",
                                            "confidence": 0.98,
                                            "reason": "removeu observacao",
                                        },
                                        {
                                            "id": "10:main:2",
                                            "clean_name": "Daniel",
                                            "confidence": 0.97,
                                            "reason": "removeu horario",
                                        },
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
    result = asyncio.run(analyzer.clean_weekly_names(entries))

    assert result["10:main:1"].clean_name == "Gomes"
    assert result["10:main:2"].clean_name == "Daniel"


def test_openai_compatible_analyzer_rejects_invented_clean_name_tokens() -> None:
    entries = [
        WeeklyNameCleanupInput(
            id="10:main:1",
            game_date=date(2026, 8, 5),
            section="main",
            position=1,
            name="Gomes (bem provavelmente)",
            invited_by=None,
        )
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "entries": [
                                        {
                                            "id": "10:main:1",
                                            "clean_name": "Joao Gomes",
                                            "confidence": 0.99,
                                            "reason": "inventou nome",
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
        attempts=1,
        transport=httpx.MockTransport(handler),
    )

    try:
        asyncio.run(analyzer.clean_weekly_names(entries))
    except ConversationAIError as exc:
        assert "inventa tokens" in str(exc)
    else:
        raise AssertionError("limpeza com token inventado deveria falhar")
