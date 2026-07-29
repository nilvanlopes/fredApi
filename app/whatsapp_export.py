from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


MESSAGE_HEADER_RE = re.compile(
    r"^(?P<date>\d{1,2}/\d{1,2}/\d{2,4}) "
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?) - (?P<body>.*)$"
)


class WhatsAppExportError(ValueError):
    pass


@dataclass(frozen=True)
class WhatsAppMessage:
    ordinal: int
    occurred_at: datetime
    sender_name: str | None
    text: str

    def fingerprint(self, *, chat_id: str) -> str:
        value = "\0".join(
            (
                chat_id,
                self.occurred_at.isoformat(),
                self.sender_name or "",
                self.text,
            )
        )
        return sha256(value.encode("utf-8")).hexdigest()


def parse_whatsapp_export(
    text: str,
    *,
    timezone_name: str = "America/Sao_Paulo",
) -> list[WhatsAppMessage]:
    if not text.strip():
        raise WhatsAppExportError("export do WhatsApp vazio")

    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise WhatsAppExportError(f"timezone invalido: {timezone_name}") from exc

    messages: list[WhatsAppMessage] = []
    current_occurred_at: datetime | None = None
    current_sender: str | None = None
    current_lines: list[str] = []

    def finish_current() -> None:
        if current_occurred_at is None:
            return
        messages.append(
            WhatsAppMessage(
                ordinal=len(messages),
                occurred_at=current_occurred_at,
                sender_name=current_sender,
                text="\n".join(current_lines).strip(),
            )
        )

    for raw_line in text.lstrip("\ufeff").splitlines():
        header_match = MESSAGE_HEADER_RE.match(raw_line)
        if not header_match:
            if current_occurred_at is not None:
                current_lines.append(raw_line)
            continue

        finish_current()
        current_occurred_at = _parse_timestamp(
            header_match.group("date"),
            header_match.group("time"),
            timezone=timezone,
        )
        current_sender, first_line = _split_sender(header_match.group("body"))
        current_lines = [first_line]

    finish_current()
    if not messages:
        raise WhatsAppExportError("nenhuma mensagem reconhecida no export do WhatsApp")
    return messages


def _parse_timestamp(date_value: str, time_value: str, *, timezone: ZoneInfo) -> datetime:
    year_value = date_value.rsplit("/", maxsplit=1)[-1]
    date_format = "%d/%m/%y" if len(year_value) == 2 else "%d/%m/%Y"
    time_format = "%H:%M:%S" if time_value.count(":") == 2 else "%H:%M"
    try:
        parsed = datetime.strptime(f"{date_value} {time_value}", f"{date_format} {time_format}")
    except ValueError as exc:
        raise WhatsAppExportError(
            f"timestamp invalido no export: {date_value} {time_value}"
        ) from exc
    return parsed.replace(tzinfo=timezone)


def _split_sender(value: str) -> tuple[str | None, str]:
    sender, separator, text = value.partition(": ")
    if not separator:
        return None, value
    return sender.strip() or None, text
