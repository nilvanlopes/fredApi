from datetime import datetime

import pytest

from app.parser import (
    ParseError,
    normalize_name,
    parse_monthly_subscribers_message,
    parse_weekly_attendance_message,
)


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


def test_parse_implicit_monthly_payment_header_from_export_timestamp() -> None:
    parsed = parse_monthly_subscribers_message(
        """Lista pagamento mensal Frederico
1. Th Pai ✅
2. \u2060Debora
3. Gomes***
4. Thay <Mensagem editada>
""",
        received_at=datetime(2024, 12, 9, 18, 2),
    )

    assert (parsed.month, parsed.year) == (12, 2024)
    assert [(item.name, item.has_paid) for item in parsed.subscribers] == [
        ("Th Pai", True),
        ("Debora", False),
        ("Gomes", False),
        ("Thay", False),
    ]


def test_parse_monthly_participants_header_from_export_timestamp() -> None:
    parsed = parse_monthly_subscribers_message(
        """Lista Participantes
1. Th Pai ✅
2. Débora
""",
        received_at=datetime(2025, 2, 3, 19, 23),
    )

    assert (parsed.month, parsed.year) == (2, 2025)
    assert [(item.position, item.name, item.has_paid) for item in parsed.subscribers] == [
        (1, "Th Pai", True),
        (2, "Débora", False),
    ]


def test_normalize_name_ignores_case_accents_and_extra_spaces() -> None:
    assert normalize_name(" João   Victor ") == "joao victor"
    assert normalize_name("VÍEGAS") == "viegas"


def test_invalid_message_raises_parse_error() -> None:
    with pytest.raises(ParseError):
        parse_monthly_subscribers_message("qualquer coisa")


def test_parse_weekly_attendance_message() -> None:
    parsed = parse_weekly_attendance_message(
        """LISTA VOLEI FREDERICO 03/06
1. pyu
2. João Victor
3. Fábio

Convidados
1. fulano (conv douglas)
""",
        received_at=datetime(2026, 6, 2, 21, 0, 0),
    )

    assert parsed.game_date.isoformat() == "2026-06-03"
    assert [(item.section, item.position, item.name) for item in parsed.entries] == [
        ("main", 1, "pyu"),
        ("main", 2, "João Victor"),
        ("main", 3, "Fábio"),
        ("guests", 1, "fulano"),
    ]
    assert parsed.entries[-1].invited_by == "douglas"
    assert parsed.entries[-1].normalized_invited_by == "douglas"


def test_parse_weekly_attendance_marks_inline_guest_labels() -> None:
    parsed = parse_weekly_attendance_message(
        """LISTA VOLEI FREDERICO 03/06
1. Pessoa (convidado)
2. Pessoa (conv)
3. Pessoa (conv Fulano)
""",
        received_at=datetime(2026, 6, 2, 21, 0, 0),
    )

    assert [entry.name for entry in parsed.entries] == ["Pessoa", "Pessoa", "Pessoa"]
    assert [entry.is_guest for entry in parsed.entries] == [True, True, True]
    assert [entry.invited_by for entry in parsed.entries] == [None, None, "Fulano"]


def test_parse_implicit_weekly_header_infers_current_or_next_wednesday() -> None:
    monday = parse_weekly_attendance_message(
        "🏐 Vôlei Frederico 19h30 🏐\n1. Pessoa\n",
        received_at=datetime(2024, 12, 30, 18, 0),
    )
    wednesday = parse_weekly_attendance_message(
        "🏐 Vôlei Frederico 19h30 🏐\n1. Pessoa\n",
        received_at=datetime(2025, 1, 1, 18, 0),
    )
    thursday = parse_weekly_attendance_message(
        "🏐 Vôlei Frederico 19h30 🏐\n1. Pessoa\n",
        received_at=datetime(2025, 1, 2, 18, 0),
    )

    assert monday.game_date.isoformat() == "2025-01-01"
    assert wednesday.game_date.isoformat() == "2025-01-01"
    assert thursday.game_date.isoformat() == "2025-01-08"


def test_parse_weekly_header_normalizes_non_wednesday_dates() -> None:
    stale_header = parse_weekly_attendance_message(
        "LISTA VOLEI FREDERICO 10/11\n1. Pessoa\n",
        received_at=datetime(2025, 12, 8, 12, 7),
    )
    near_header = parse_weekly_attendance_message(
        "LISTA VOLEI FREDERICO 28/06\n1. Pessoa\n",
        received_at=datetime(2026, 6, 24, 11, 58),
    )

    assert stale_header.game_date.isoformat() == "2025-12-10"
    assert near_header.game_date.isoformat() == "2026-07-01"


def test_parse_weekly_attendance_message_normalizes_invisible_chars() -> None:
    parsed = parse_weekly_attendance_message(
        "LISTA VOLEI FREDERICO 03/06\n1. \u2060Fábio\n2. Murilo (conv. Pyu)\n",
        received_at=datetime(2026, 6, 2, 21, 0, 0),
    )

    assert parsed.entries[0].name == "Fábio"
    assert parsed.entries[0].normalized_name == "fabio"
    assert parsed.entries[1].invited_by == "Pyu"
    assert parsed.entries[1].normalized_invited_by == "pyu"


def test_parse_weekly_attendance_extracts_prebuilt_team_number() -> None:
    parsed = parse_weekly_attendance_message(
        "LISTA VOLEI FREDERICO 03/06\n1. Leal(conv)3️⃣\n2. Mario (conv Pyu)2️⃣\n",
        received_at=datetime(2026, 6, 2, 21, 0, 0),
    )

    assert [(item.name, item.invited_by, item.prebuilt_team_number) for item in parsed.entries] == [
        ("Leal", None, 3),
        ("Mario", "Pyu", 2),
    ]


def test_parse_weekly_attendance_ignores_check_mark_after_annotations() -> None:
    parsed = parse_weekly_attendance_message(
        "LISTA VOLEI FREDERICO 03/06\n"
        "1. Thiago (conv pyu) 1️⃣ ✅\n"
        "2. Thay(conv Tiago)✅\n"
        "3. Samuel - conv Tiago\n"
        "4. Jerffeson (convidado\n"
        "5. Higor (Convidado Murilo)\n",
        received_at=datetime(2026, 6, 2, 21, 0, 0),
    )

    assert [(item.name, item.invited_by, item.prebuilt_team_number) for item in parsed.entries] == [
        ("Thiago", "pyu", 1),
        ("Thay", "Tiago", None),
        ("Samuel", "Tiago", None),
        ("Jerffeson", None, None),
        ("Higor", "Murilo", None),
    ]


def test_parse_legacy_weekly_header_uses_message_date_and_cleans_annotations() -> None:
    parsed = parse_weekly_attendance_message(
        """🏐 Vôlei Frederico 19h30 🏐
1. Gomes (talvez)
2. Carlos Daniel (Convidado)

Convidados
1. Yuri ( conv Magalhães) <Mensagem editada>
""",
        received_at=datetime(2024, 12, 11, 18, 16),
    )

    assert parsed.game_date.isoformat() == "2024-12-11"
    assert [(item.section, item.name) for item in parsed.entries] == [
        ("main", "Gomes"),
        ("main", "Carlos Daniel"),
        ("guests", "Yuri"),
    ]
    assert parsed.entries[-1].invited_by == "Magalhães"


def test_parse_weekly_attendance_list_of_guests_section() -> None:
    parsed = parse_weekly_attendance_message(
        """🏐Vôlei Frederico 19h30🏐
1. Th Pai
2. Débora
3.

Lista de Convidados

1. Mario
2. Gelson
""",
        received_at=datetime(2025, 1, 14, 16, 11),
    )

    assert [(item.section, item.position, item.name) for item in parsed.entries] == [
        ("main", 1, "Th Pai"),
        ("main", 2, "Débora"),
        ("guests", 1, "Mario"),
        ("guests", 2, "Gelson"),
    ]


def test_parse_weekly_attendance_guest_waiting_list_section() -> None:
    parsed = parse_weekly_attendance_message(
        """🏐Vôlei Frederico 19h30🏐
1. Th Pai
2. Débora
3. Mario (conv Thzin)

Lista de espera dos convidados

1. Mario
2. Gelson
""",
        received_at=datetime(2025, 1, 15, 17, 0),
    )

    assert [(item.section, item.position, item.name) for item in parsed.entries] == [
        ("main", 1, "Th Pai"),
        ("main", 2, "Débora"),
        ("main", 3, "Mario"),
        ("guests", 1, "Mario"),
        ("guests", 2, "Gelson"),
    ]


def test_parse_weekly_attendance_deduplicates_repeated_source_positions() -> None:
    parsed = parse_weekly_attendance_message(
        """🏐 Vôlei Frederico 19h30 🏐
1. Th Pai
2. Débora
5. jeff
5. Vitor

Convidados
1. Daniel
1. Mario
""",
        received_at=datetime(2025, 2, 12, 10, 23),
    )

    assert [(item.section, item.position, item.name) for item in parsed.entries] == [
        ("main", 1, "Th Pai"),
        ("main", 2, "Débora"),
        ("main", 5, "jeff"),
        ("main", 6, "Vitor"),
        ("guests", 1, "Daniel"),
        ("guests", 2, "Mario"),
    ]


def test_parse_weekly_attendance_ignores_zero_position_and_accepts_plain_guest_line() -> None:
    parsed = parse_weekly_attendance_message(
        """LISTA VÔLEI FREDERICO 17/12
0. Ramequi tocedor kkkk
1. Pyu
2. Noleto

Convidado
Débora <Mensagem editada>
""",
        received_at=datetime(2025, 12, 17, 16, 2),
    )

    assert [(item.section, item.position, item.name) for item in parsed.entries] == [
        ("main", 1, "Pyu"),
        ("main", 2, "Noleto"),
        ("guests", 1, "Débora"),
    ]


def test_parse_abbreviated_guest_section_with_bullets() -> None:
    parsed = parse_weekly_attendance_message(
        """LISTA VOLEI FREDERICO 18/02
1. Pyu

Conv.
- Tiago
- Wadson
""",
        received_at=datetime(2026, 2, 18, 15, 57),
    )

    assert [(item.section, item.position, item.name) for item in parsed.entries] == [
        ("main", 1, "Pyu"),
        ("guests", 1, "Tiago"),
        ("guests", 2, "Wadson"),
    ]
