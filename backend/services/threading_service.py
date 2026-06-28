import uuid
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import Email
from services.email_parser import EmailData


import hashlib

# ⚡ Bolt Optimization: Pre-compile reference extraction regex
# Impact: Eliminates redundant inline compilation/caching overhead during repetitive
# email header processing, yielding a measurable speedup when handling long reference lists.
REFERENCE_PATTERN = re.compile(r"<([^>]+)>")

def generate_email_fingerprint(
    subject: str | None,
    date_str: str | None,
    sender: str | None,
    recipient: str | None,
) -> str:
    """Generate a deterministic fingerprint for an email based on key fields."""
    components = [
        str(subject or "").strip(),
        str(date_str or "").strip(),
        str(sender or "").strip(),
        str(recipient or "").strip(),
    ]
    raw = "|".join(components).lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_message_id(value: str | None) -> str | None:
    """Return the canonical persisted form for a Message-ID-like header."""
    if value is None:
        return None

    normalized = str(value).strip().strip("<>").strip()
    return normalized or None


def extract_reference_ids(value: str | None) -> list[str]:
    """Extract canonical message IDs from a References header in header order."""
    if not value:
        return []

    refs = REFERENCE_PATTERN.findall(str(value))
    if not refs:
        refs = str(value).split()

    normalized_refs: list[str] = []
    # Optimization: Use a set for O(1) membership checks to avoid O(n^2) scaling on long reference lists
    seen: set[str] = set()
    for ref in refs:
        normalized = normalize_message_id(ref)
        if normalized and normalized not in seen:
            seen.add(normalized)
            normalized_refs.append(normalized)
    return normalized_refs


async def _find_existing_thread_ids(
    session: AsyncSession,
    message_ids: list[str],
    *,
    user_id: str,
    organization_id: str | None,
) -> dict[str, str]:
    if not message_ids:
        return {}

    target_ids: list[str] = []
    seen_target_ids: set[str] = set()
    for message_id in message_ids:
        for target_id in (message_id, f"<{message_id}>"):
            if target_id not in seen_target_ids:
                seen_target_ids.add(target_id)
                target_ids.append(target_id)

    result = await session.execute(
        select(Email.message_id, Email.thread_id).where(
            *Email.owner_filters(user_id, organization_id),
            Email.message_id.in_(target_ids),
        )
    )

    thread_ids_by_message_id: dict[str, str] = {}
    for message_id, thread_id in result.all():
        if not thread_id:
            continue
        normalized_message_id = normalize_message_id(message_id)
        if normalized_message_id:
            thread_ids_by_message_id[normalized_message_id] = (
                normalize_message_id(thread_id) or thread_id
            )
    return thread_ids_by_message_id


async def assign_thread_id(
    session: AsyncSession,
    email_data: EmailData,
    *,
    user_id: str,
    organization_id: str | None,
) -> str:
    """
    Determine the thread_id for a new email based on in_reply_to and references.
    If no existing match is found, generate a new thread_id.
    """
    in_reply_to = normalize_message_id(email_data.get("in_reply_to"))
    references = extract_reference_ids(email_data.get("references"))

    existing_candidates = []
    # Optimization: Use a set for O(1) membership checks to prevent O(n^2) deduplication of candidates
    seen = set()
    if in_reply_to:
        existing_candidates.append(in_reply_to)
        seen.add(in_reply_to)
    for ref in references:
        if ref not in seen:
            seen.add(ref)
            existing_candidates.append(ref)

    if existing_candidates:
        thread_ids_by_message_id = await _find_existing_thread_ids(
            session,
            existing_candidates,
            user_id=user_id,
            organization_id=organization_id,
        )
        for candidate in existing_candidates:
            thread_id = thread_ids_by_message_id.get(candidate)
            if thread_id:
                return thread_id

    # If the parent/root has not been imported yet, use the oldest known ancestor
    # as the deterministic thread root so later imports converge on one thread.
    if references:
        return references[0]

    if in_reply_to:
        return in_reply_to

    msg_id = normalize_message_id(email_data.get("message_id"))
    if msg_id:
        return msg_id

    return uuid.uuid4().hex
