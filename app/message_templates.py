from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


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


def render_monthly_subscribers_template(reference_date: date) -> str:
    month_name = MONTH_NAMES[reference_date.month - 1]
    return f"LISTA DE ASSINANTES DO MÊS DE {month_name}\n1. pyu ✅"


def render_weekly_attendance_template(reference_date: date) -> tuple[date, str]:
    game_date = next_wednesday(reference_date)
    text = (
        f"LISTA VÔLEI FREDERICO {game_date:%d/%m}\n"
        "1. Pyu\n\n"
        "Convidados\n"
        "1. "
    )
    return game_date, text


def render_weekly_attendance_message(game_date: date, entries) -> str:
    main_entries = [entry for entry in entries if entry.status == "main"]
    waiting_entries = [entry for entry in entries if entry.status == "waiting"]

    def display_name(entry) -> str:
        invited_by = getattr(entry, "invited_by", None)
        if invited_by:
            return f"{entry.name} (conv. {invited_by})"
        return entry.name

    lines = [f"LISTA VÔLEI FREDERICO {game_date:%d/%m}"]
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
