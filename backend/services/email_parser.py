from email import message_from_binary_file, message_from_bytes, policy
from email.message import Message
from pathlib import Path
import datetime
from email.utils import formataddr, getaddresses
from email.utils import parsedate_to_datetime
from typing import TypedDict
from .exceptions import EmailParseError
from .text_safety import strip_html_markup


class EmailData(TypedDict):
    """Parsed email data structure."""

    message_id: str
    thread_id: str | None
    sender: str
    reply_to: str | None
    recipients: str
    subject: str
    in_reply_to: str | None
    references: str | None
    date: datetime.datetime
    body: str
    attachments: list[dict]


def _sanitize_nul(text: str) -> str:
    """Removes NUL characters from strings, which are invalid in PostgreSQL text fields."""
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    return text.replace("\x00", "")


def _sanitize_display_text(text: str) -> str:
    return strip_html_markup(_sanitize_nul(text))


def _sanitize_address_display_text(text: str) -> str:
    sanitized_parts: list[str] = []
    for display_name, address in getaddresses([text]):
        safe_display_name = _sanitize_display_text(display_name).strip()
        safe_address = _sanitize_nul(address).strip()
        if safe_address:
            sanitized_parts.append(formataddr((safe_display_name, safe_address)))
        elif safe_display_name:
            sanitized_parts.append(safe_display_name)
    if sanitized_parts:
        return ", ".join(sanitized_parts)
    return _sanitize_display_text(text)


def _process_multipart_body(msg: Message) -> tuple[str, str, list[dict]]:
    plain_body = ""
    html_body = ""
    attachments = []

    for part in msg.walk():
        content_type = part.get_content_type()
        filename = part.get_filename()
        # Skip attachments
        if filename:
            if content_type == "text/plain":
                part_content = part.get_content()
                if isinstance(part_content, str):
                    attachments.append(
                        {
                            "filename": _sanitize_display_text(filename),
                            "content": _sanitize_display_text(part_content),
                        }
                    )
            continue

        if content_type == "text/plain":
            part_content = part.get_content()
            if isinstance(part_content, str):
                plain_body += part_content
        elif content_type == "text/html":
            part_content = part.get_content()
            if isinstance(part_content, str):
                html_body += part_content
    return plain_body, html_body, attachments


def _process_singlepart_body(msg: Message) -> tuple[str, str, list[dict]]:
    plain_body = ""
    html_body = ""
    content_type = msg.get_content_type()
    part_content = msg.get_content()
    if isinstance(part_content, str):
        if content_type == "text/html":
            html_body = part_content
        else:
            plain_body = part_content
    return plain_body, html_body, []


def _extract_body_and_attachments(msg: Message) -> tuple[str, list[dict]]:
    if msg.is_multipart():
        plain_body, html_body, attachments = _process_multipart_body(msg)
    else:
        plain_body, html_body, attachments = _process_singlepart_body(msg)

    body = plain_body if plain_body else html_body
    return body, attachments


def _extract_date(msg: Message) -> datetime.datetime:
    date_header = msg.get("Date")
    parsed_date = None
    if date_header:
        try:
            parsed_date = parsedate_to_datetime(date_header)
        except (TypeError, ValueError):
            parsed_date = None

    if not parsed_date:
        parsed_date = datetime.datetime.now(datetime.timezone.utc)
    return parsed_date


def _extract_thread_id(msg: Message, message_id: str) -> str | None:
    references = msg.get("References")  # O3: email threading support

    if references:
        refs = references.split(None, 1)
        if refs:
            return _sanitize_nul(refs[0])

    in_reply_to = msg.get("In-Reply-To")
    if in_reply_to:
        in_reply_to_list = in_reply_to.split(None, 1)
        if in_reply_to_list:
            return _sanitize_nul(in_reply_to_list[0])

    return message_id


def _message_to_email_data(msg: Message) -> EmailData:
    body, attachments = _extract_body_and_attachments(msg)
    parsed_date = _extract_date(msg)
    message_id = _sanitize_nul(msg.get("Message-ID", ""))
    thread_id = _extract_thread_id(msg, message_id)

    return {
        "message_id": message_id,
        "thread_id": thread_id,
        "sender": _sanitize_address_display_text(msg.get("From", "")),
        "reply_to": (
            _sanitize_address_display_text(msg.get("Reply-To", ""))
            if msg.get("Reply-To")
            else None
        ),
        "recipients": _sanitize_address_display_text(msg.get("To", "")),
        "subject": _sanitize_display_text(msg.get("Subject", "")),
        "in_reply_to": (
            _sanitize_nul(msg.get("In-Reply-To", ""))
            if msg.get("In-Reply-To")
            else None
        ),
        "references": (
            _sanitize_nul(msg.get("References", "")) if msg.get("References") else None
        ),
        "date": parsed_date,
        "body": _sanitize_display_text(body),
        "attachments": attachments,
    }


def parse_eml(file_path: str | Path) -> EmailData:
    """Parses an EML file and extracts email metadata and body.

    Raises:
        EmailParseError: If there is an issue reading the file.
    """
    try:
        with open(file_path, "rb") as f:
            msg = message_from_binary_file(f, policy=policy.default)
    except OSError as e:
        raise EmailParseError(f"Failed to read file {file_path}: {e}") from e

    return _message_to_email_data(msg)


def parse_eml_bytes(content: bytes) -> EmailData:
    """Parses EML bytes fetched from a provider."""
    try:
        msg = message_from_bytes(content, policy=policy.default)
    except Exception as e:
        raise EmailParseError("Failed to parse provider email bytes") from e

    return _message_to_email_data(msg)
