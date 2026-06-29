import asyncio
import datetime
from email import policy as email_policy
import hashlib
import logging
import mailbox
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from sqlalchemy import bindparam, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Attachment, Email
from services.archive import extract_backup_async
from services.email_dedupe_service import strong_email_fingerprint
from services.email_parser import EmailData, parse_eml_bytes
from services.embedding import (
    STORAGE_EMBEDDING_DIMENSION,
    fit_embedding_vector,
    generate_embeddings,
)
from services.exceptions import ArchiveError, EmailParseError, EmbeddingGenerationError
from services.threading_service import (
    assign_thread_id,
    email_owner_filters,
    generate_email_fingerprint,
    normalize_message_id,
)

EMBEDDING_DIMENSION = STORAGE_EMBEDDING_DIMENSION
MAX_IMPORT_UPLOADS = 10
MAX_IMPORT_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_IMPORT_EML_FILES = 100
MAX_IMPORT_EMAILS_PER_OWNER = 1000
EMAIL_IMPORT_QUOTA_LOCK_NAMESPACE = "naruon-email-import-quota"
logger = logging.getLogger(__name__)

EmailImportItemStatus = Literal["imported", "skipped_duplicate", "failed"]


class EmailImportQuotaExceeded(Exception):
    pass


@dataclass(frozen=True)
class EmailImportUpload:
    filename: str
    content: bytes


@dataclass(frozen=True)
class EmailImportEmbeddingProvider:
    api_key: str
    base_url: str | None
    embedding_model: str


@dataclass
class EmailImportItemResult:
    filename: str
    status: EmailImportItemStatus
    reason_code: str | None = None
    attachment_count: int = 0


@dataclass
class EmailImportResult:
    imported_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    attachment_count: int = 0
    items: list[EmailImportItemResult] = field(default_factory=list)

    def add_item(self, item: EmailImportItemResult) -> None:
        self.items.append(item)
        if item.status == "imported":
            self.imported_count += 1
            self.attachment_count += item.attachment_count
        elif item.status == "skipped_duplicate":
            self.skipped_count += 1
        else:
            self.failed_count += 1


def _safe_upload_filename(filename: str) -> str:
    name = Path(filename or "upload").name.strip()
    if name in {".", ".."}:
        return "upload"
    return name or "upload"


def _safe_item_filename(upload_name: str, eml_path: Path | None = None) -> str:
    safe_upload_name = _safe_upload_filename(upload_name)
    if eml_path is None or eml_path.name == safe_upload_name:
        return safe_upload_name
    return f"{safe_upload_name}:{eml_path.name}"


def _utc_datetime(value: object) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=datetime.timezone.utc)
        return value.astimezone(datetime.timezone.utc)
    return datetime.datetime.now(datetime.timezone.utc)


def _fallback_message_id(content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    return f"import-{digest}@local.naruon"


def _message_id_for(parsed: EmailData, content: bytes) -> str:
    return normalize_message_id(parsed.get("message_id")) or _fallback_message_id(
        content
    )


def _email_fingerprint(parsed: EmailData, persisted_date: datetime.datetime) -> str:
    strong_fingerprint = strong_email_fingerprint(
        sender=parsed.get("sender"),
        subject=parsed.get("subject"),
        date=persisted_date,
        body=parsed.get("body"),
    )
    if strong_fingerprint:
        return strong_fingerprint
    return generate_email_fingerprint(
        parsed.get("subject"),
        persisted_date.isoformat(),
        parsed.get("sender"),
        parsed.get("recipients"),
    )


async def _find_existing_email(
    session: AsyncSession,
    *,
    user_id: str,
    organization_id: str,
    message_id: str,
    fingerprint: str,
) -> Email | None:
    message_lookup_values = {message_id, f"<{message_id}>"}
    result = await session.execute(
        select(Email).where(
            *email_owner_filters(user_id, organization_id),
            or_(
                Email.message_id.in_(message_lookup_values),
                Email.fingerprint == fingerprint,
            ),
        )
    )
    return result.scalar_one_or_none()


async def _owner_email_import_count(
    session: AsyncSession, *, user_id: str, organization_id: str
) -> int:
    count = await session.scalar(
        select(func.count(Email.id)).where(
            *email_owner_filters(user_id, organization_id)
        )
    )
    return int(count or 0)


def _session_uses_postgresql(session: AsyncSession) -> bool:
    try:
        bind = session.get_bind()
    except Exception:
        return False
    return getattr(getattr(bind, "dialect", None), "name", None) == "postgresql"


async def _acquire_owner_import_quota_lock(
    session: AsyncSession, *, user_id: str, organization_id: str
) -> bool:
    if not _session_uses_postgresql(session):
        return False
    lock_params = {
        "namespace_key": EMAIL_IMPORT_QUOTA_LOCK_NAMESPACE,
        "owner_key": f"{user_id}\x00{organization_id}",
    }
    await session.execute(
        select(
            func.pg_advisory_lock(
                func.hashtext(bindparam("namespace_key")),
                func.hashtext(bindparam("owner_key")),
            )
        ),
        lock_params,
    )
    return True


async def _release_owner_import_quota_lock(
    session: AsyncSession, *, user_id: str, organization_id: str
) -> None:
    lock_params = {
        "namespace_key": EMAIL_IMPORT_QUOTA_LOCK_NAMESPACE,
        "owner_key": f"{user_id}\x00{organization_id}",
    }
    await session.execute(
        select(
            func.pg_advisory_unlock(
                func.hashtext(bindparam("namespace_key")),
                func.hashtext(bindparam("owner_key")),
            )
        ),
        lock_params,
    )


async def _import_single_eml(
    session: AsyncSession,
    *,
    eml_path: Path,
    display_filename: str,
    user_id: str,
    organization_id: str,
    embedding_provider: EmailImportEmbeddingProvider | None = None,
) -> EmailImportItemResult:
    try:
        content, parsed = await asyncio.to_thread(_read_and_parse_eml, eml_path)
    except EmailParseError:
        return EmailImportItemResult(
            filename=display_filename,
            status="failed",
            reason_code="parse_failed",
        )

    message_id = _message_id_for(parsed, content)
    parsed["message_id"] = message_id
    persisted_date = _utc_datetime(parsed.get("date"))
    fingerprint = _email_fingerprint(parsed, persisted_date)

    existing_email = await _find_existing_email(
        session,
        user_id=user_id,
        organization_id=organization_id,
        message_id=message_id,
        fingerprint=fingerprint,
    )
    if existing_email is not None:
        return EmailImportItemResult(
            filename=display_filename,
            status="skipped_duplicate",
            reason_code="duplicate_email",
        )

    thread_id = await assign_thread_id(
        session,
        parsed,
        user_id=user_id,
        organization_id=organization_id,
    )
    attachment_payloads = list(parsed.get("attachments", []))
    embedding_texts = [str(parsed.get("body") or "")]
    embedding_texts.extend(
        str(attachment.get("content") or "") for attachment in attachment_payloads
    )
    fitted_embeddings = await _generate_import_embeddings(
        embedding_texts,
        embedding_provider=embedding_provider,
    )
    email_obj = Email(
        user_id=user_id,
        organization_id=organization_id,
        message_id=message_id,
        thread_id=thread_id,
        fingerprint=fingerprint,
        sender=parsed.get("sender", ""),
        reply_to=parsed.get("reply_to"),
        recipients=parsed.get("recipients"),
        subject=parsed.get("subject"),
        in_reply_to=parsed.get("in_reply_to"),
        references=parsed.get("references"),
        date=persisted_date,
        body=parsed.get("body", ""),
        embedding=fitted_embeddings[0] if fitted_embeddings else _zero_embedding(),
    )

    attachment_count = 0
    for attachment_index, attachment in enumerate(attachment_payloads, start=1):
        email_obj.attachments.append(
            Attachment(
                filename=str(attachment.get("filename") or "attachment.txt"),
                content=str(attachment.get("content") or ""),
                embedding=(
                    fitted_embeddings[attachment_index]
                    if attachment_index < len(fitted_embeddings)
                    else _zero_embedding()
                ),
            )
        )
        attachment_count += 1

    session.add(email_obj)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        return EmailImportItemResult(
            filename=display_filename,
            status="failed",
            reason_code="database_commit_failed",
        )

    return EmailImportItemResult(
        filename=display_filename,
        status="imported",
        attachment_count=attachment_count,
    )


def _read_and_parse_eml(eml_path: Path) -> tuple[bytes, EmailData]:
    content = _read_eml_bytes(eml_path)
    return content, parse_eml_bytes(content)


def _zero_embedding() -> list[float]:
    return [0.0] * EMBEDDING_DIMENSION


async def _generate_import_embeddings(
    texts: list[str],
    *,
    embedding_provider: EmailImportEmbeddingProvider | None,
) -> list[list[float]]:
    if embedding_provider is None:
        return [_zero_embedding() for _ in texts]
    try:
        provider_embeddings = await generate_embeddings(
            texts,
            embedding_provider.api_key,
            base_url=embedding_provider.base_url,
            model=embedding_provider.embedding_model,
        )
    except (EmbeddingGenerationError, ValueError) as exc:
        logger.warning(
            "Email import embedding generation failed; retrying imported content "
            "item by item before zero-vector fallback: "
            "error_type=%s text_count=%s",
            type(exc).__name__,
            len(texts),
        )
        recovered: list[list[float]] = []
        for index, text in enumerate(texts):
            try:
                single_embedding = await generate_embeddings(
                    [text],
                    embedding_provider.api_key,
                    base_url=embedding_provider.base_url,
                    model=embedding_provider.embedding_model,
                )
                if not single_embedding:
                    recovered.append(_zero_embedding())
                    continue
                recovered.append(
                    fit_embedding_vector(single_embedding[0], EMBEDDING_DIMENSION)
                )
            except (
                EmbeddingGenerationError,
                ValueError,
                TypeError,
                IndexError,
            ) as item_exc:
                logger.warning(
                    "Email import embedding item retry failed; falling back to zero "
                    "vector for imported content: error_type=%s embedding_index=%s",
                    type(item_exc).__name__,
                    index,
                )
                recovered.append(_zero_embedding())
        return recovered

    fitted: list[list[float]] = []
    for index in range(len(texts)):
        if index >= len(provider_embeddings):
            fitted.append(_zero_embedding())
            continue
        try:
            fitted.append(
                fit_embedding_vector(provider_embeddings[index], EMBEDDING_DIMENSION)
            )
        except ValueError as exc:
            logger.warning(
                "Email import embedding fit failed; falling back to zero vector "
                "for imported content: error_type=%s embedding_index=%s",
                type(exc).__name__,
                index,
            )
            fitted.append(_zero_embedding())
    return fitted


def _read_eml_bytes(eml_path: Path) -> bytes:
    no_follow_flag = getattr(os, "O_NOFOLLOW", None)
    if no_follow_flag is None:
        raise EmailParseError(
            "Email import requires O_NOFOLLOW support (unavailable on this platform)"
        )

    open_flags = os.O_RDONLY | no_follow_flag
    file_descriptor_transferred = False
    try:
        file_descriptor = os.open(eml_path, open_flags)
    except OSError as exc:
        raise EmailParseError("Failed to read email file") from exc

    try:
        file_stat = os.fstat(file_descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise EmailParseError("Failed to read email file")
        file_handle = os.fdopen(file_descriptor, "rb")
        file_descriptor_transferred = True
        with file_handle:
            return file_handle.read()
    except OSError as exc:
        raise EmailParseError("Failed to read email file") from exc
    finally:
        if not file_descriptor_transferred:
            os.close(file_descriptor)


async def _eml_paths_for_upload(
    *,
    upload: EmailImportUpload,
    upload_dir: Path,
) -> tuple[list[Path], str | None]:
    upload_name = _safe_upload_filename(upload.filename)
    upload_path = upload_dir / upload_name
    try:
        await asyncio.to_thread(upload_path.write_bytes, upload.content)
    except OSError:
        return [], "file_write_failed"

    suffix = upload_path.suffix.lower()
    if suffix == ".eml":
        return [upload_path], None
    if suffix == ".mbox":
        return _eml_paths_for_mbox_upload(upload_path, upload_dir)
    if suffix != ".zip":
        return [], "unsupported_file_type"

    extract_dir = upload_dir / "extracted"
    try:
        extracted_paths = await extract_backup_async(upload_path, extract_dir)
    except ArchiveError:
        return [], "archive_extract_failed"

    # _read_eml_bytes() performs the final no-follow regular-file validation.
    eml_paths = [path for path in extracted_paths if path.suffix.lower() == ".eml"]
    if not eml_paths:
        return [], "archive_contains_no_eml"
    if len(eml_paths) > MAX_IMPORT_EML_FILES:
        return [], "archive_too_many_eml_files"
    return eml_paths, None


def _eml_paths_for_mbox_upload(
    upload_path: Path,
    upload_dir: Path,
) -> tuple[list[Path], str | None]:
    extract_dir = upload_dir / "mbox"
    extract_dir.mkdir(parents=True, exist_ok=True)

    parsed_mailbox = None
    try:
        parsed_mailbox = mailbox.mbox(upload_path, create=False)
        eml_paths: list[Path] = []
        for index, message in enumerate(parsed_mailbox, start=1):
            if len(eml_paths) >= MAX_IMPORT_EML_FILES:
                return [], "mbox_too_many_eml_files"
            eml_path = extract_dir / f"message_{index:06d}.eml"
            eml_path.write_bytes(message.as_bytes(policy=email_policy.default))
            eml_paths.append(eml_path)
    except (OSError, mailbox.Error, UnicodeError, ValueError):
        return [], "mbox_parse_failed"
    finally:
        if parsed_mailbox is not None:
            parsed_mailbox.close()

    if not eml_paths:
        return [], "mbox_contains_no_eml"
    return eml_paths, None


async def import_email_uploads(
    session: AsyncSession,
    *,
    uploads: list[EmailImportUpload],
    user_id: str,
    organization_id: str,
    embedding_provider: EmailImportEmbeddingProvider | None = None,
) -> EmailImportResult:
    lock_acquired = await _acquire_owner_import_quota_lock(
        session, user_id=user_id, organization_id=organization_id
    )
    try:
        result = EmailImportResult()
        existing_email_count = await _owner_email_import_count(
            session, user_id=user_id, organization_id=organization_id
        )
        remaining_quota = MAX_IMPORT_EMAILS_PER_OWNER - existing_email_count
        if remaining_quota <= 0:
            raise EmailImportQuotaExceeded()

        with TemporaryDirectory(prefix="naruon-email-import-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            planned_imports: list[tuple[str, Path]] = []
            for index, upload in enumerate(uploads):
                upload_name = _safe_upload_filename(upload.filename)
                upload_dir = temp_dir / f"upload_{index}"
                upload_dir.mkdir(parents=True, exist_ok=True)
                eml_paths, failure_reason = await _eml_paths_for_upload(
                    upload=upload,
                    upload_dir=upload_dir,
                )
                if failure_reason is not None:
                    result.add_item(
                        EmailImportItemResult(
                            filename=upload_name,
                            status="failed",
                            reason_code=failure_reason,
                        )
                    )
                    continue

                planned_imports.extend(
                    (
                        _safe_item_filename(upload_name, eml_path),
                        eml_path,
                    )
                    for eml_path in eml_paths
                )

            if len(planned_imports) > remaining_quota:
                raise EmailImportQuotaExceeded()

            for display_filename, eml_path in planned_imports:
                result.add_item(
                    await _import_single_eml(
                        session,
                        eml_path=eml_path,
                        display_filename=display_filename,
                        user_id=user_id,
                        organization_id=organization_id,
                        embedding_provider=embedding_provider,
                    )
                )
    finally:
        if lock_acquired:
            await _release_owner_import_quota_lock(
                session, user_id=user_id, organization_id=organization_id
            )

    return result
