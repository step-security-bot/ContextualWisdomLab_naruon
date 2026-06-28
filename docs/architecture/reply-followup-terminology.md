# ADR: Rename Reply SLA Wording to Overdue Reply Follow-Up

**Status:** Accepted
**Date:** 2026-06-22

## Context

Naruon uses `SLA` for one mail workflow: sent messages that still need an
external reply after a configured overdue threshold, currently 48 hours. The
backend stores those escalations as source-linked `reply_sla` ticket tasks and
exposes them through `POST /api/tasks/reply-sla-escalations`.

`SLA` is accurate for an internal policy threshold, but it is too formal for the
Home and Tasks surfaces. Users are not managing a provider service agreement
there; they are deciding whether to follow up on a sent email.

## Decision

Use **미답변 팔로업** for user-visible Korean task/action wording.

Keep the existing `reply_sla` source type, API path, unique index, scheduler
class names, and error code for compatibility. Treat those names as legacy
machine identifiers until a broader API migration is explicitly scheduled.

## Considered Options

| Option | Decision | Reason |
| --- | --- | --- |
| `SLA` | Reject for UI | Too much enterprise jargon for a mail follow-up action. |
| `답변 기한 초과` | Use as supporting policy wording | Clear for thresholds, but too stiff as a task title. |
| `미답변 팔로업` | Accept for UI and generated task titles | Describes the actual user action: follow up on an unanswered sent mail. |
| `답변 추적` | Keep for broader feature labels | Describes monitoring, not the overdue task escalation. |

## Consequences

- New and refreshed ticket titles use `미답변 팔로업: ...`.
- Home and Tasks buttons/status messages avoid `SLA`.
- API compatibility is preserved: existing clients can keep calling
  `/api/tasks/reply-sla-escalations`.
- Existing persisted task rows with old titles are not rewritten in this PR.

## Migration Notes

If Naruon later exposes a public API v2 for this feature, add an
`/api/tasks/overdue-reply-followups` alias first, keep the current endpoint until
clients migrate, and only then consider replacing `reply_sla` with
`overdue_reply` in stored source types.
