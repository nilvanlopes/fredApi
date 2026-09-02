from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.message_templates import (
    MONTH_NAMES,
    next_wednesday,
    render_monthly_subscribers_template,
    render_weekly_attendance_message,
    render_weekly_attendance_template,
)
from app.parser import (
    parse_monthly_subscribers_message,
    parse_weekly_attendance_message,
)


client = TestClient(app)


@pytest.mark.parametrize(
    ("month", "month_name"),
    enumerate(MONTH_NAMES, start=1),
)
def test_monthly_template_uses_portuguese_month_name(
    month: int,
    month_name: str,
) -> None:
    reference_date = date(2026, month, 1)

    assert render_monthly_subscribers_template(reference_date) == (
        f"LISTA DE ASSINANTES DO MÊS DE {month_name}\n1. pyu ✅"
    )


def test_weekly_template_uses_wednesday_of_monday_week() -> None:
    game_date, text = render_weekly_attendance_template(date(2026, 8, 10))

    assert game_date == date(2026, 8, 12)
    assert text == (
        "LISTA VÔLEI FREDERICO 12/08\n"
        "1. Pyu\n\n"
        "Convidados\n"
        "1. "
    )


def test_next_wednesday_handles_year_boundary() -> None:
    assert next_wednesday(date(2024, 12, 30)) == date(2025, 1, 1)


def test_render_weekly_attendance_message_places_promoted_guests_in_main_list() -> None:
    entries = [
        type("Entry", (), {"name": "Pyu", "status": "main"})(),
        type("Entry", (), {"name": "Convidado", "status": "main"})(),
        type("Entry", (), {"name": "Aguardando", "status": "waiting"})(),
    ]

    assert render_weekly_attendance_message(date(2026, 8, 26), entries) == (
        "LISTA VÔLEI FREDERICO 26/08\n"
        "1. Pyu\n"
        "2. Convidado\n\n"
        "Convidados\n"
        "1. Aguardando"
    )


def test_render_weekly_attendance_message_keeps_inviter_and_omits_empty_waiting() -> None:
    entries = [
        type(
            "Entry",
            (),
            {
                "name": "Pyu",
                "status": "main",
                "invited_by": None,
            },
        )(),
        type(
            "Entry",
            (),
            {
                "name": "Renato",
                "status": "main",
                "invited_by": "Ana Caroline",
            },
        )(),
    ]

    assert render_weekly_attendance_message(date(2026, 9, 2), entries) == (
        "LISTA VÔLEI FREDERICO 02/09\n"
        "1. Pyu\n"
        "2. Renato (conv. Ana Caroline)"
    )


def test_generated_templates_round_trip_through_existing_parsers() -> None:
    monthly_text = render_monthly_subscribers_template(date(2026, 8, 1))
    game_date, weekly_text = render_weekly_attendance_template(date(2026, 8, 10))

    monthly = parse_monthly_subscribers_message(
        monthly_text,
        received_at=datetime(2026, 8, 1, 12),
    )
    weekly = parse_weekly_attendance_message(
        weekly_text,
        received_at=datetime(2026, 8, 10, 12),
    )

    assert (monthly.month, monthly.year) == (8, 2026)
    assert [(entry.name, entry.has_paid) for entry in monthly.subscribers] == [
        ("pyu", True)
    ]
    assert weekly.game_date == game_date
    assert [(entry.section, entry.name) for entry in weekly.entries] == [
        ("main", "Pyu")
    ]


def test_template_endpoints_return_deterministic_contracts() -> None:
    monthly_response = client.get(
        "/messages/templates/monthly-subscribers",
        params={"reference_date": "2026-08-01"},
    )
    weekly_response = client.get(
        "/messages/templates/weekly-attendance",
        params={"reference_date": "2026-08-10"},
    )

    assert monthly_response.status_code == 200
    assert monthly_response.json() == {
        "type": "monthly_subscribers",
        "reference_date": "2026-08-01",
        "month": 8,
        "year": 2026,
        "text": "LISTA DE ASSINANTES DO MÊS DE AGOSTO\n1. pyu ✅",
    }
    assert weekly_response.status_code == 200
    assert weekly_response.json() == {
        "type": "weekly_attendance",
        "reference_date": "2026-08-10",
        "game_date": "2026-08-12",
        "text": (
            "LISTA VÔLEI FREDERICO 12/08\n"
            "1. Pyu\n\n"
            "Convidados\n"
            "1. "
        ),
    }
