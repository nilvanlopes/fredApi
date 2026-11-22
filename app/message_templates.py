from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.parser import CHECK_MARK

LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
MONTH_NAMES = (
    "JANEIRO",
    "FEVEREIRO",
    "MARÇO",
    "ABRIL",
    "MAIO",
    "JUNHO",
    "JULHO",
    "AGOSTO",
    "SETEMBRO",
    "OUTUBRO",
    "NOVEMBRO",
    "DEZEMBRO",
)


def local_reference_date(reference_date: date | None = None) -> date:
    return reference_date or datetime.now(LOCAL_TZ).date()


def next_wednesday(reference_date: date) -> date:
    days_until_wednesday = (2 - reference_date.weekday()) % 7
    return reference_date + timedelta(days=days_until_wednesday)


def monthly_subscribers_title(reference_date: date) -> str:
    month_name = MONTH_NAMES[reference_date.month - 1]
    return f"LISTA DE ASSINANTES DO MÊS DE {month_name}"


def render_monthly_subscribers_template(reference_date: date) -> str:
    return f"{monthly_subscribers_title(reference_date)}\n1. pyu ✅"


def render_monthly_subscribers_message(reference_date: date, entries) -> str:
    entries = [f"{entry.position}. {_with_payment_mark(entry.name, paid)}" for entry, paid in entries]
    return "\n".join([monthly_subscribers_title(reference_date), *entries])


def render_weekly_attendance_template(reference_date: date) -> tuple[date, str]:
    game_date = next_wednesday(reference_date)
    text = (
        f"LISTA VÔLEI FREDERICO {game_date:%d/%m}\n"
        "1. Pyu\n\n"
        "Convidados\n"
        "1. "
    )
    return game_date, text


def render_weekly_attendance_message(game_date: date, entries, *, paid_person_ids=None, include_year=False) -> str:
    main_entries = [entry for entry in entries if entry.status == "main"]
    waiting_entries = [entry for entry in entries if entry.status == "waiting"]

    def display_name(entry) -> str:
        name = entry.name
        invited_by = getattr(entry, "invited_by", None)
        if invited_by:
            invite_label = "conv" if invited_by.strip().casefold() == name.strip().casefold() else f"conv. {invited_by}"
            name = f"{name} ({invite_label})"
        if paid_person_ids is not None:
            team = entry.prebuilt_team_number
            if team is not None:
                name = f"{name} {team}\ufe0f\u20e3"
            name = _with_payment_mark(name, entry.person_id in paid_person_ids)
        return name

    date_format = "%d/%m/%Y" if include_year else "%d/%m"
    lines = [f"LISTA VÔLEI FREDERICO {game_date:{date_format}}"]
    lines.extend(
        f"{position}. {display_name(entry)}"
        for position, entry in enumerate(main_entries, start=1)
    )
    if waiting_entries:
        lines.append("")
        lines.append("Convidados")
        lines.extend(
            f"{position}. {display_name(entry)}"
            for position, entry in enumerate(waiting_entries, start=1)
        )
    return "\n".join(lines)


def _with_payment_mark(name: str, paid: bool) -> str:
    return f"{name} {CHECK_MARK}" if paid else name
