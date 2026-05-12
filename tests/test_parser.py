from datetime import datetime

import pytest

from app.parser import ParseError, normalize_name, parse_monthly_subscribers_message


def test_parse_monthly_subscribers_message() -> None:
    parsed = parse_monthly_subscribers_message(
        """LISTA DE ASSINANTES DO MES DE ABRIL
1. pyu ✅
2. Daniel ✅
3. Grid ✅
4. Jessica
5. Klesley ✅
""",
        received_at=datetime(2026, 4, 22),
    )

    assert parsed.month == 4
    assert parsed.year == 2026
    assert [(item.position, item.name, item.has_paid) for item in parsed.subscribers] == [
        (1, "pyu", True),
        (2, "Daniel", True),
        (3, "Grid", True),
        (4, "Jessica", False),
        (5, "Klesley", True),
    ]


def test_parse_empty_position_as_removal() -> None:
    parsed = parse_monthly_subscribers_message(
        """LISTA DE ASSINANTES DO MES DE ABRIL
1. pyu ✅
4.
5. Klesley ✅
""",
        received_at=datetime(2026, 4, 22),
    )

    empty_line = parsed.subscribers[1]

    assert empty_line.position == 4
    assert empty_line.name is None
    assert empty_line.normalized_name is None
    assert empty_line.has_paid is False


def test_normalize_name_ignores_case_accents_and_extra_spaces() -> None:
    assert normalize_name(" João   Victor ") == "joao victor"
    assert normalize_name("VÍEGAS") == "viegas"


def test_invalid_message_raises_parse_error() -> None:
    with pytest.raises(ParseError):
        parse_monthly_subscribers_message("qualquer coisa")

