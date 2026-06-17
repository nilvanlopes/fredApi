from dataclasses import dataclass
from datetime import date, datetime
import re
import unicodedata

CHECK_MARK = "✅"

MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

HEADER_RE = re.compile(
    r"lista\s+de\s+assinantes\s+do\s+m[eê]s\s+de\s+([a-zç]+)(?:\s+de\s+(\d{4})|\s+(\d{4}))?",
    re.IGNORECASE,
)
WEEKLY_HEADER_RE = re.compile(
    r"lista\s+volei\s+frederico\s+(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?",
    re.IGNORECASE,
)
LINE_RE = re.compile(r"^\s*(\d+)\s*[\.\-\)]?\s*(.*?)\s*$")
INVITED_BY_RE = re.compile(
    r"\((?:conv\.?|convidado\s+por)\s+(.+?)\)\s*$",
    re.IGNORECASE,
)
INVISIBLE_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
SPACES_RE = re.compile(r"\s+")


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedSubscriberLine:
    position: int
    name: str | None
    normalized_name: str | None
    has_paid: bool


@dataclass(frozen=True)
class ParsedMonthlySubscribers:
    month: int
    year: int
    title: str
    subscribers: list[ParsedSubscriberLine]


@dataclass(frozen=True)
class ParsedWeeklyAttendanceLine:
    section: str
    position: int
    name: str
    normalized_name: str
    invited_by: str | None
    normalized_invited_by: str | None


@dataclass(frozen=True)
class ParsedWeeklyAttendance:
    game_date: date
    title: str
    entries: list[ParsedWeeklyAttendanceLine]


def normalize_spaces(value: str) -> str:
    value = INVISIBLE_RE.sub("", value)
    return SPACES_RE.sub(" ", value).strip()


def normalize_name(value: str) -> str:
    value = normalize_spaces(value).casefold()
    decomposed = unicodedata.normalize("NFD", value)
    without_accents = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return normalize_spaces(without_accents)


def parse_monthly_subscribers_message(
    text: str,
    *,
    received_at: datetime | None = None,
) -> ParsedMonthlySubscribers:
    lines = [normalize_spaces(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        raise ParseError("mensagem vazia")

    title = lines[0]
    header_match = HEADER_RE.search(normalize_name(title))
    if not header_match:
        raise ParseError("cabecalho de lista mensal de assinantes nao reconhecido")

    month_name = header_match.group(1)
    month = MONTHS.get(month_name)
    if month is None:
        raise ParseError(f"mes nao reconhecido: {month_name}")

    explicit_year = header_match.group(2) or header_match.group(3)
    year = int(explicit_year) if explicit_year else (received_at or datetime.now()).year

    subscribers: list[ParsedSubscriberLine] = []
    for line in lines[1:]:
        line_match = LINE_RE.match(line)
        if not line_match:
            continue

        position = int(line_match.group(1))
        raw_name = line_match.group(2)
        has_paid = CHECK_MARK in raw_name
        name = normalize_spaces(raw_name.replace(CHECK_MARK, ""))

        if not name:
            subscribers.append(
                ParsedSubscriberLine(
                    position=position,
                    name=None,
                    normalized_name=None,
                    has_paid=False,
                )
            )
            continue

        subscribers.append(
            ParsedSubscriberLine(
                position=position,
                name=name,
                normalized_name=normalize_name(name),
                has_paid=has_paid,
            )
        )

    if not subscribers:
        raise ParseError("nenhuma linha numerada de assinante encontrada")

    return ParsedMonthlySubscribers(
        month=month,
        year=year,
        title=title,
        subscribers=subscribers,
    )


def parse_weekly_attendance_message(
    text: str,
    *,
    received_at: datetime | None = None,
) -> ParsedWeeklyAttendance:
    lines = [normalize_spaces(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        raise ParseError("mensagem vazia")

    title = lines[0]
    header_match = WEEKLY_HEADER_RE.search(normalize_name(title))
    if not header_match:
        raise ParseError("cabecalho de lista semanal de presenca nao reconhecido")

    day = int(header_match.group(1))
    month = int(header_match.group(2))
    raw_year = header_match.group(3)
    if raw_year is None:
        year = (received_at or datetime.now()).year
    elif len(raw_year) == 2:
        year = 2000 + int(raw_year)
    else:
        year = int(raw_year)

    try:
        game_date = date(year, month, day)
    except ValueError as exc:
        raise ParseError("data da lista semanal invalida") from exc

    section = "main"
    entries: list[ParsedWeeklyAttendanceLine] = []
    for line in lines[1:]:
        if normalize_name(line) == "convidados":
            section = "guests"
            continue

        line_match = LINE_RE.match(line)
        if not line_match:
            continue

        raw_name = normalize_spaces(line_match.group(2))
        if not raw_name:
            continue

        invited_by = None
        invited_match = INVITED_BY_RE.search(raw_name)
        if invited_match:
            invited_by = normalize_spaces(invited_match.group(1))
            raw_name = normalize_spaces(INVITED_BY_RE.sub("", raw_name))

        entries.append(
            ParsedWeeklyAttendanceLine(
                section=section,
                position=int(line_match.group(1)),
                name=raw_name,
                normalized_name=normalize_name(raw_name),
                invited_by=invited_by,
                normalized_invited_by=normalize_name(invited_by) if invited_by else None,
            )
        )

    if not entries:
        raise ParseError("nenhuma linha numerada de presenca encontrada")

    return ParsedWeeklyAttendance(
        game_date=game_date,
        title=title,
        entries=entries,
    )
