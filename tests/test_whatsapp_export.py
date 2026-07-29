from app.conversation_import import realtime_message_fingerprint
from app.whatsapp_export import WhatsAppExportError, parse_whatsapp_export


EXPORT_SAMPLE = """09/12/2024 17:59 - Th Pai: Glr
09/12/2024 18:02 - Th Pai: Lista pagamento mensal Frederico

1. Th Pai ✅
2. Thay
09/12/2024 18:03 - Alguem entrou no grupo
"""


def test_parse_whatsapp_export_preserves_multiline_messages() -> None:
    messages = parse_whatsapp_export(EXPORT_SAMPLE)

    assert len(messages) == 3
    assert messages[1].occurred_at.isoformat() == "2024-12-09T18:02:00-03:00"
    assert messages[1].sender_name == "Th Pai"
    assert messages[1].text.splitlines() == [
        "Lista pagamento mensal Frederico",
        "",
        "1. Th Pai ✅",
        "2. Thay",
    ]
    assert messages[2].sender_name is None


def test_message_fingerprint_is_stable_and_scoped_by_chat() -> None:
    message = parse_whatsapp_export(EXPORT_SAMPLE)[1]

    assert message.fingerprint(chat_id="fred") == message.fingerprint(chat_id="fred")
    assert message.fingerprint(chat_id="fred") != message.fingerprint(chat_id="outro")


def test_realtime_fingerprint_matches_whatsapp_export_fingerprint() -> None:
    message = parse_whatsapp_export(EXPORT_SAMPLE)[1]

    assert realtime_message_fingerprint(
        chat_id="fred",
        occurred_at=message.occurred_at,
        sender_name=message.sender_name,
        text=message.text,
    ) == message.fingerprint(chat_id="fred")


def test_invalid_export_timezone_is_rejected() -> None:
    try:
        parse_whatsapp_export(EXPORT_SAMPLE, timezone_name="timezone/inexistente")
    except WhatsAppExportError as exc:
        assert "timezone invalido" in str(exc)
    else:
        raise AssertionError("timezone invalido deveria falhar")
