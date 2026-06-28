# Pending Reply Follow-Up Task Escalation

Date: 2026-05-28

## Scope

Connect source-backed pending sent-mail replies to ticket-style task escalation.
This slice does not add database objects, does not host email, and does not
execute provider writes. It converts customer-mailbox reply waits that exceed a
workspace reply-deadline threshold into source-linked `reply_sla` tasks.

## Confirmed Inputs

- `docs/plans/2026-05-27-today-pending-replies-dashboard.md` left
  task-board escalation for pending replies as deferred work.
- `backend/api/emails.py` and `services.reply_tracking_service` already compute
  pending replies from configured user mailbox addresses, exclude self-sent
  notes, and exclude threads with later external replies.
- `frontend/branding` and workspace navigation require Tasks to be actionable,
  not placeholder-only.
- `AGENTS.md` requires signed-session task APIs, no public identity headers,
  opaque task ids, source-linked email/thread scope, and plain-text task titles.

## Implementation Plan

1. Add `POST /api/tasks/reply-sla-escalations` with a default 48-hour reply deadline and a
   bounded limit.
2. Reuse server-authoritative pending reply detection instead of inferring waits
   in the browser.
3. Create or update one source-linked `reply_sla` task per overdue pending
   sent-mail message, using `blocked` and `urgent` for escalated work.
4. Keep generated task titles plain text and replace active HTML-like subjects
   with a safe fallback label.
5. Add Home and Tasks workspace controls that call the endpoint with the stored
   `naruon_session_token` bearer session and show the updated board/status.
6. Verify desktop and mobile screenshots, horizontal overflow, and mobile scroll.

## Verification Targets

- `python3 -m pytest backend/tests/test_tasks_api.py -q -k reply_sla`
- `npx vitest run src/app/tasks/page.test.tsx src/components/WorkspaceHome.dashboard.test.tsx`
- `npm run lint -- src/components/TasksLayout.tsx src/components/WorkspaceHome.tsx src/app/tasks/page.test.tsx src/components/WorkspaceHome.dashboard.test.tsx tests/e2e/dashboard-branding.spec.ts tests/e2e/helpers.ts`
- `npm run test:e2e -- tests/e2e/dashboard-branding.spec.ts -g "pending reply follow-up task escalation" --project=desktop`

## Deferred Work

- Durable reminder notifications and workspace-configurable reply deadline policy storage.
- Provider-specific sent-folder sync completeness for OAuth, SMTP, POP3, and
  IMAP adapters.
- Calendar/task writeback execution after source-backed provider connectors are
  ready.
