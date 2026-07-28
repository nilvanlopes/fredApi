from collections import Counter

from app.parser import ParsedWeeklyAttendanceLine
from app.services import _build_entry_states


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
