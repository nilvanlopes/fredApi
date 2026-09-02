import asyncio
from collections import Counter
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.parser import ParsedWeeklyAttendanceLine
from app.services import _build_entry_states, get_weekly_attendance_message


def _line(
    position: int,
    name: str,
    *,
    is_guest: bool = False,
) -> ParsedWeeklyAttendanceLine:
    return ParsedWeeklyAttendanceLine(
        section="main",
        position=position,
        name=name,
        normalized_name=name.casefold(),
        invited_by=None,
        normalized_invited_by=None,
        is_guest=is_guest,
    )


def test_weekly_entries_with_same_name_consume_monthly_match_once() -> None:
    states = _build_entry_states(
        [_line(1, "Pessoa"), _line(2, "Pessoa")],
        monthly_names=Counter({"pessoa": 1}),
        capacity=24,
        after_cutoff=False,
    )

    assert [entry.is_monthly_subscriber for entry in states] == [True, False]
    assert [entry.status for entry in states] == ["main", "waiting"]


def test_duplicate_monthly_names_are_distinct_people() -> None:
    states = _build_entry_states(
        [_line(1, "Pessoa"), _line(2, "Pessoa")],
        monthly_names=Counter({"pessoa": 2}),
        capacity=24,
        after_cutoff=False,
    )

    assert [entry.is_monthly_subscriber for entry in states] == [True, True]
    assert [entry.status for entry in states] == ["main", "main"]


def test_guest_duplicate_does_not_consume_monthly_match() -> None:
    states = _build_entry_states(
        [_line(1, "Pessoa", is_guest=True), _line(2, "Pessoa")],
        monthly_names=Counter({"pessoa": 1}),
        capacity=24,
        after_cutoff=False,
    )

    assert [entry.is_monthly_subscriber for entry in states] == [False, True]


def test_get_weekly_attendance_message_renders_current_persisted_state() -> None:
    attendance = SimpleNamespace(
        game_date=date(2026, 9, 2),
        entries=[
            SimpleNamespace(name="Convidado", status="main", display_order=2),
            SimpleNamespace(name="Pyu", status="main", display_order=1),
            SimpleNamespace(name="Aguardando", status="waiting", display_order=3),
        ],
    )
    query_result = Mock()
    query_result.scalar_one_or_none.return_value = attendance
    session = AsyncMock()
    session.execute.return_value = query_result

    response = asyncio.run(
        get_weekly_attendance_message(
            session,
            game_date=date(2026, 9, 2),
        )
    )

    assert response is not None
    assert response.game_date == date(2026, 9, 2)
    assert response.text == (
        "LISTA VÔLEI FREDERICO 02/09\n"
        "1. Pyu\n"
        "2. Convidado\n\n"
        "Convidados\n"
        "1. Aguardando"
    )
