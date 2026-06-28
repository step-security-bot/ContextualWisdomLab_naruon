import datetime
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Email, TicketTask
from services.reply_tracking_service import check_missing_replies
from services.text_safety import contains_html_markup
from services.threading_service import normalize_message_id

REPLY_SLA_SOURCE_TYPE = "reply_sla"


class ReplySlaTaskConflict(Exception):
    pass


@dataclass(frozen=True)
class ReplySlaEscalatedTask:
    task: TicketTask
    source_email_id: str | None


@dataclass(frozen=True)
class ReplySlaEscalationResult:
    evaluated: int
    created: int
    overdue_hours: int
    tasks: list[ReplySlaEscalatedTask]


def canonical_reply_sla_thread_key(email: Email) -> str:
    return (
        normalize_message_id(email.thread_id)
        or normalize_message_id(email.message_id)
        or email.message_id
    )


def _safe_email_subject(subject: str | None) -> str:
    trimmed = (subject or "제목 없음").replace("\x00", " ").strip()
    if not trimmed or contains_html_markup(trimmed):
        return "제목 정리 필요"
    return " ".join(trimmed.split())[:120]


def _reply_sla_task_title(email: Email) -> str:
    return f"미답변 팔로업: {_safe_email_subject(email.subject)}"


def _email_date_utc(email: Email) -> datetime.datetime:
    message_date = email.date
    if message_date.tzinfo is None:
        return message_date.replace(tzinfo=datetime.timezone.utc)
    return message_date


async def _fetch_existing_tasks_by_email(
    db: AsyncSession,
    user_id: str,
    organization_id: str | None,
    email_ids: list[int]
) -> dict[int, TicketTask]:
    result = await db.execute(
        select(TicketTask)
        .where(
            TicketTask.user_id == user_id,
            TicketTask.organization_id == organization_id,
            TicketTask.related_email_id.in_(email_ids),
            TicketTask.source_type == REPLY_SLA_SOURCE_TYPE,
        )
        .order_by(TicketTask.updated_at.desc())
    )
    tasks_by_email = {}
    for task in result.scalars().all():
        if task.related_email_id not in tasks_by_email:
            tasks_by_email[task.related_email_id] = task
    return tasks_by_email


def _update_task_for_escalation(
    task: TicketTask, email: Email, now: datetime.datetime
) -> None:
    if task.status != "done":
        task.title = _reply_sla_task_title(email)
        task.status = "blocked"
        task.priority = "urgent"
        task.related_thread_id = canonical_reply_sla_thread_key(email)
        task.updated_at = now


def _create_task_for_escalation(
    user_id: str, organization_id: str | None, email: Email
) -> TicketTask:
    return TicketTask(
        user_id=user_id,
        organization_id=organization_id,
        title=_reply_sla_task_title(email),
        status="blocked",
        priority="urgent",
        source_type=REPLY_SLA_SOURCE_TYPE,
        related_email_id=email.id,
        related_thread_id=canonical_reply_sla_thread_key(email),
    )


async def _refresh_escalated_tasks(
    db: AsyncSession,
    user_id: str,
    organization_id: str | None,
    email_ids: list[int],
    escalated_tasks: list[tuple[TicketTask, str | None]]
) -> None:
    refreshed_tasks_by_email = await _fetch_existing_tasks_by_email(
        db, user_id, organization_id, email_ids
    )
    for i, (task, message_id) in enumerate(escalated_tasks):
        refreshed_task = refreshed_tasks_by_email.get(task.related_email_id)
        if refreshed_task is not None:
            escalated_tasks[i] = (refreshed_task, message_id)


async def _process_bulk_escalation(
    db: AsyncSession,
    user_id: str,
    organization_id: str | None,
    overdue_replies: list[Email],
    now: datetime.datetime,
) -> tuple[int, list[tuple[TicketTask, str | None]]]:
    email_ids = [email.id for email in overdue_replies]
    existing_tasks_by_email = await _fetch_existing_tasks_by_email(
        db, user_id, organization_id, email_ids
    )

    created_count = 0
    escalated_tasks: list[tuple[TicketTask, str | None]] = []

    for email in overdue_replies:
        if email.id in existing_tasks_by_email:
            task = existing_tasks_by_email[email.id]
            _update_task_for_escalation(task, email, now)
            escalated_tasks.append((task, email.message_id))
        else:
            task = _create_task_for_escalation(user_id, organization_id, email)
            db.add(task)
            created_count += 1
            escalated_tasks.append((task, email.message_id))

    if created_count > 0 or any(
        email.id in existing_tasks_by_email for email in overdue_replies
    ):
        await db.commit()

        if created_count > 0:
            await _refresh_escalated_tasks(
                db, user_id, organization_id, email_ids, escalated_tasks
            )

    return created_count, escalated_tasks


async def _process_fallback_escalation(
    db: AsyncSession,
    user_id: str,
    organization_id: str | None,
    overdue_replies: list[Email],
    now: datetime.datetime,
) -> tuple[int, list[tuple[TicketTask, str | None]]]:
    email_ids = [email.id for email in overdue_replies]
    existing_tasks_by_email = await _fetch_existing_tasks_by_email(
        db, user_id, organization_id, email_ids
    )

    created_count = 0
    escalated_tasks: list[tuple[TicketTask, str | None]] = []

    fallback_entries: list[tuple[Email, TicketTask | None]] = []
    conflicted_email_ids: list[int] = []
    new_tasks: list[tuple[int, Email, TicketTask]] = []

    for email in overdue_replies:
        if email.id in existing_tasks_by_email:
            task = existing_tasks_by_email[email.id]
            _update_task_for_escalation(task, email, now)
        else:
            task = _create_task_for_escalation(user_id, organization_id, email)
            new_tasks.append((len(fallback_entries), email, task))
        fallback_entries.append((email, task))

    if new_tasks:
        try:
            async with db.begin_nested():
                for _, _, task in new_tasks:
                    db.add(task)
                await db.flush()
            created_count += len(new_tasks)
        except IntegrityError:
            for index, email, task in new_tasks:
                task_or_none: TicketTask | None = task
                try:
                    async with db.begin_nested():
                        db.add(task)
                        await db.flush()
                    created_count += 1
                except IntegrityError:
                    conflicted_email_ids.append(email.id)
                    task_or_none = None
                fallback_entries[index] = (email, task_or_none)

    if conflicted_email_ids:
        conflicted_tasks_by_email = await _fetch_existing_tasks_by_email(
            db, user_id, organization_id, conflicted_email_ids
        )

        for index, (email, task) in enumerate(fallback_entries):
            if task is not None or email.id not in conflicted_email_ids:
                continue
            task = conflicted_tasks_by_email.get(email.id)
            if task is None:
                raise ReplySlaTaskConflict(
                    "reply_sla_task_conflict: "
                    f"user_id={user_id!r} organization_id={organization_id!r} "
                    f"scoped_email_key={email.id!r}"
                ) from None

            _update_task_for_escalation(task, email, now)
            fallback_entries[index] = (email, task)

    escalated_tasks.extend(
        (task, email.message_id)
        for email, task in fallback_entries
        if task is not None
    )

    if created_count > 0 or any(t.status != "done" for t, _ in escalated_tasks):
        await db.commit()
        await _refresh_escalated_tasks(
            db, user_id, organization_id, email_ids, escalated_tasks
        )

    return created_count, escalated_tasks


async def create_reply_sla_escalation_tasks(
    db: AsyncSession,
    *,
    user_id: str,
    organization_id: str | None,
    overdue_hours: int,
    limit: int,
) -> ReplySlaEscalationResult:
    pending_replies = await check_missing_replies(db, user_id, organization_id)
    now = datetime.datetime.now(datetime.timezone.utc)
    overdue_cutoff = now - datetime.timedelta(hours=overdue_hours)
    overdue_replies = sorted(
        [
            email
            for email in pending_replies
            if _email_date_utc(email) <= overdue_cutoff
        ],
        key=_email_date_utc,
    )[:limit]

    if not overdue_replies:
        return ReplySlaEscalationResult(
            evaluated=len(pending_replies),
            created=0,
            overdue_hours=overdue_hours,
            tasks=[],
        )

    try:
        created_count, escalated_tasks = await _process_bulk_escalation(
            db, user_id, organization_id, overdue_replies, now
        )
    except IntegrityError:
        await db.rollback()
        created_count, escalated_tasks = await _process_fallback_escalation(
            db, user_id, organization_id, overdue_replies, now
        )

    return ReplySlaEscalationResult(
        evaluated=len(pending_replies),
        created=created_count,
        overdue_hours=overdue_hours,
        tasks=[
            ReplySlaEscalatedTask(task=task, source_email_id=source_email_id)
            for task, source_email_id in escalated_tasks
        ],
    )
