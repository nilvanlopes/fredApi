from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
IMPLICIT_MONTHLY_HEADER_RE = re.compile(
    r"(?:lista\s+pagamento(?:\s+mensal)?\s+frederico|lista\s+participantes)",
    re.IGNORECASE,
)
WEEKLY_HEADER_RE = re.compile(
    r"lista\s+volei\s+frederico\s+(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?",
    re.IGNORECASE,
)
IMPLICIT_WEEKLY_HEADER_RE = re.compile(
    r"(?:lista\s+)?volei\s+frederico(?:\s+\d{1,2}h(?:\d{2})?)?",
    re.IGNORECASE,
)
LINE_RE = re.compile(r"^\s*(\d+)\s*[\.\-\)]?\s*(.*?)\s*$")
BULLET_LINE_RE = re.compile(r"^\s*[-•]\s*(.*?)\s*$")
INVITED_BY_RE = re.compile(
    r"\(\s*(?:conv\.?|convidado(?:\s+por)?)\s+(.+?)\)?\s*$",
    re.IGNORECASE,
)
TRAILING_INVITED_BY_RE = re.compile(
    r"\s*[-–—]\s*(?:conv\.?|convidado\s+por)\s+(.+?)\s*$",
    re.IGNORECASE,
)
EDITED_MARKER_RE = re.compile(r"\s*<mensagem\s+editada>\s*$", re.IGNORECASE)
TRAILING_ASTERISKS_RE = re.compile(r"\s*\*+\s*$")
TENTATIVE_RE = re.compile(r"\s*\(\s*talvez\s*\)\s*$", re.IGNORECASE)
TIME_ANNOTATION_RE = re.compile(
    r"\s*\(\s*\d{1,2}(?::\d{2}|h(?:\d{2})?)\s*\)\s*$",
    re.IGNORECASE,
)
GUEST_LABEL_RE = re.compile(
    r"\s*\(\s*(?:convidad[oa]|conv\.?)\s*\)?\s*$",
    re.IGNORECASE,
)
SELF_GUEST_LABEL_RE = re.compile(r"\s*\(\s*conv\.?\s*\)?\s*$", re.IGNORECASE)
GUEST_SECTION_RE = re.compile(
    r"^(?:lista\s+(?:de\s+)?)?(?:espera\s+(?:dos?\s+)?)?convidad[oa]s?\s*:?$"
)
PREBUILT_TEAM_RE = re.compile(r"\s*([1-9])(?:\ufe0f)?\u20e3\s*$")
INVISIBLE_RE = re.compile(
    r"[\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]"
)
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
    prebuilt_team_number: int | None = None
    is_guest: bool = False


@dataclass(frozen=True)
class ParsedWeeklyAttendance:
    game_date: date
    title: str
    entries: list[ParsedWeeklyAttendanceLine]


def normalize_spaces(value: str) -> str:
    value = INVISIBLE_RE.sub("", value)
    value = EDITED_MARKER_RE.sub("", value)
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
    month_hint: int | None = None,
    year_hint: int | None = None,
    allow_unrecognized_header: bool = False,
) -> ParsedMonthlySubscribers:
    lines = [normalize_spaces(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        raise ParseError("mensagem vazia")

    title = lines[0]
    normalized_title = normalize_name(title)
    header_match = HEADER_RE.search(normalized_title)
    implicit_header = IMPLICIT_MONTHLY_HEADER_RE.search(normalized_title)
    if not header_match and not implicit_header and not allow_unrecognized_header:
        raise ParseError("cabecalho de lista mensal de assinantes nao reconhecido")

    if header_match:
        month_name = header_match.group(1)
        month = MONTHS.get(month_name)
        if month is None:
            raise ParseError(f"mes nao reconhecido: {month_name}")
        explicit_year = header_match.group(2) or header_match.group(3)
        year = int(explicit_year) if explicit_year else (received_at or datetime.now()).year
    else:
        reference_time = received_at or datetime.now()
        month = month_hint or reference_time.month
        year = year_hint or reference_time.year
    if not 1 <= month <= 12:
        raise ParseError("mes da lista mensal invalido")
    if year < 2000:
        raise ParseError("ano da lista mensal invalido")

    subscribers: list[ParsedSubscriberLine] = []
    for line in lines[1:]:
        line_match = LINE_RE.match(line)
        if not line_match:
            continue

        position = int(line_match.group(1))
        raw_name = line_match.group(2)
        has_paid = CHECK_MARK in raw_name
        name = normalize_spaces(raw_name.replace(CHECK_MARK, ""))
        name = normalize_spaces(TRAILING_ASTERISKS_RE.sub("", name))

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
    game_date_hint: date | None = None,
    allow_unrecognized_header: bool = False,
) -> ParsedWeeklyAttendance:
    lines = [normalize_spaces(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        raise ParseError("mensagem vazia")

    title = lines[0]
    normalized_title = normalize_name(title)
    header_match = WEEKLY_HEADER_RE.search(normalized_title)
    implicit_header = IMPLICIT_WEEKLY_HEADER_RE.search(normalized_title)
    if not header_match and not implicit_header and not allow_unrecognized_header:
        raise ParseError("cabecalho de lista semanal de presenca nao reconhecido")

    if header_match:
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
            explicit_game_date = date(year, month, day)
        except ValueError as exc:
            raise ParseError("data da lista semanal invalida") from exc
        game_date = _normalize_weekly_game_date(
            explicit_game_date,
            reference_date=(received_at or datetime.now()).date(),
        )
    else:
        reference_date = (received_at or datetime.now()).date()
        game_date = game_date_hint or _infer_weekly_game_date(reference_date)

    section = "main"
    guest_position = 0
    used_positions: dict[str, set[int]] = {"main": set(), "guests": set()}
    entries: list[ParsedWeeklyAttendanceLine] = []
    for line in lines[1:]:
        normalized_line = normalize_name(line)
        if normalized_line in {"conv", "conv."} or GUEST_SECTION_RE.match(normalized_line):
            section = "guests"
            continue

        line_match = LINE_RE.match(line)
        if line_match:
            position = int(line_match.group(1))
            raw_line_name = line_match.group(2)
            if section == "guests":
                guest_position = max(guest_position, position)
        else:
            bullet_match = BULLET_LINE_RE.match(line) if section == "guests" else None
            if bullet_match:
                guest_position += 1
                position = guest_position
                raw_line_name = bullet_match.group(1)
            elif section == "guests":
                guest_position += 1
                position = guest_position
                raw_line_name = line
            else:
                continue

        raw_name = normalize_spaces(raw_line_name.replace(CHECK_MARK, ""))
        if not raw_name:
            continue

        prebuilt_team_number = None
        prebuilt_team_match = PREBUILT_TEAM_RE.search(raw_name)
        if prebuilt_team_match:
            prebuilt_team_number = int(prebuilt_team_match.group(1))
            raw_name = normalize_spaces(PREBUILT_TEAM_RE.sub("", raw_name))

        invited_by = None
        is_guest = section == "guests"
        invited_match = INVITED_BY_RE.search(raw_name)
        if invited_match:
            invited_by = normalize_spaces(invited_match.group(1))
            raw_name = normalize_spaces(INVITED_BY_RE.sub("", raw_name))
            is_guest = True
        else:
            trailing_invited_match = TRAILING_INVITED_BY_RE.search(raw_name)
            if trailing_invited_match:
                invited_by = normalize_spaces(trailing_invited_match.group(1))
                raw_name = normalize_spaces(TRAILING_INVITED_BY_RE.sub("", raw_name))
                is_guest = True

        raw_name = normalize_spaces(TENTATIVE_RE.sub("", raw_name))
        raw_name = normalize_spaces(TIME_ANNOTATION_RE.sub("", raw_name))
        guest_label_match = GUEST_LABEL_RE.search(raw_name)
        if guest_label_match:
            is_guest = True
            guest_name = normalize_spaces(GUEST_LABEL_RE.sub("", raw_name))
            if invited_by is None and SELF_GUEST_LABEL_RE.search(raw_name):
                invited_by = guest_name
            raw_name = guest_name
        raw_name = normalize_spaces(TRAILING_ASTERISKS_RE.sub("", raw_name))
        if not raw_name:
            continue

        if position < 1:
            continue
        while position in used_positions[section]:
            position += 1
        used_positions[section].add(position)

        entries.append(
            ParsedWeeklyAttendanceLine(
                section=section,
                position=position,
                name=raw_name,
                normalized_name=normalize_name(raw_name),
                invited_by=invited_by,
                normalized_invited_by=normalize_name(invited_by) if invited_by else None,
                prebuilt_team_number=prebuilt_team_number,
                is_guest=is_guest,
            )
        )

    if not entries:
        raise ParseError("nenhuma linha numerada de presenca encontrada")

    return ParsedWeeklyAttendance(
        game_date=game_date,
        title=title,
        entries=entries,
    )


def _infer_weekly_game_date(reference_date: date) -> date:
    days_until_wednesday = (2 - reference_date.weekday()) % 7
    return reference_date + timedelta(days=days_until_wednesday)


def _normalize_weekly_game_date(explicit_game_date: date, *, reference_date: date) -> date:
    if explicit_game_date.weekday() == 2:
        return explicit_game_date
    if explicit_game_date < reference_date - timedelta(days=7):
        return _infer_weekly_game_date(reference_date)
    return _infer_weekly_game_date(explicit_game_date)
