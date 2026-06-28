# DeepWiki Q&A Gap Execution Track

Baseline: 2026-06-15

This tracker converts the DeepWiki Q&A review into executable development
goals. It is intentionally evidence-first: every item lists the current status,
source files, tests, and the next remaining_executable_goal when the item is not
fully implemented.

## Scope Contract

Naruon is a customer-owned mail, calendar, file, and governance control plane.
It may index metadata, generate AI-assisted action intent, and dispatch
explicit connector commands, but it must not silently become the authoritative
mailbox, calendar, MX host, or file-storage provider.

## Item Tracker

| item_id | status | current evidence | remaining_executable_goal |
|---|---|---|---|
| dav-propfind-db-backed | implemented | `backend/api/dav.py`, `backend/services/webdav_service.py`, `backend/tests/test_dav_api.py`, `docs/operations/source-of-truth-and-writeback-sovereignty.md` | Keep `/dav` mutation methods fail-closed until source, capability, credential, and ETag/If-Match provider execution exists. |
| alembic-migrations | implemented | `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/0001_initial_control_plane.py`, `backend/scripts/migrate_db.py`, `backend/tests/test_alembic_migrations.py`, `backend/tests/test_release_governance.py`, `backend/README.md` | Use Alembic for managed environments and keep `bootstrap_db.py` as local/dev compatibility only. |
| oidc-production-multi-user | implemented_with_guardrails | `backend/api/auth.py`, `backend/tests/test_auth_real.py`, `docs/operations/auth-key-management.md`, `README.md` | Production rollout still requires operator JWKS/OIDC configuration and audited tenant mailbox-owner backfill before real multi-tenant data is mixed. |
| self-hosted-connector-adapters | implemented | `backend/runner/connector.py`, `backend/runner/local_mail_adapters.py`, `backend/runner/local_dav_adapters.py`, `backend/tests/test_runner_connector.py`, `backend/tests/test_runner_mail_adapters.py`, `backend/tests/test_runner_dav_adapters.py`, `docs/architecture/self-hosted-runner-design.md` | Add customer deployment packaging and secrets injection guidance for production connector hosts. |
| caldav-webdav-provider-write | implemented_with_guardrails | `backend/api/calendar.py`, `backend/api/webdav.py`, `backend/api/data.py`, `backend/api/runner_ws.py`, `backend/api/observability.py`, `backend/services/provider_writeback_retry_service.py`, `backend/main.py`, `backend/db/models.py`, `backend/alembic/versions/0002_provider_writeback_retry_queue.py`, `backend/runner/local_dav_adapters.py`, `backend/tests/test_calendar_api.py`, `backend/tests/test_webdav_api.py`, `backend/tests/test_data_api.py`, `backend/tests/test_runner_ws_api.py`, `backend/tests/test_provider_writeback_retry_service.py`, `backend/tests/test_observability_api.py`, `backend/tests/test_main.py`, `backend/tests/test_runner_dav_adapters.py`, `frontend/src/components/CalendarLayout.tsx`, `frontend/src/app/calendar/page.test.tsx`, `frontend/src/components/TasksLayout.tsx`, `frontend/src/app/tasks/page.test.tsx`, `frontend/src/components/DataLayout.tsx`, `frontend/src/app/data/page.test.tsx`, `frontend/src/components/SettingsLayout.tsx`, `frontend/src/components/SettingsLayout.test.tsx`, `docs/operations/source-of-truth-and-writeback-sovereignty.md` | Calendar, self-sent knowledge materialization, and Data workspace document materialization now expose explicit provider execution controls. Additional object types must add source-specific materialization endpoints before they can execute provider writes. |
| ready-soon-ui-removal | implemented | `frontend/src/components/DataLayout.tsx`, `frontend/src/app/data/page.test.tsx`, `frontend/tests/e2e/dashboard-branding.spec.ts`, `frontend/tests/e2e/helpers.ts` | Keep future workspace controls either wired to signed APIs or represented as non-clickable status evidence outside primary action controls. |
| postgresql-ha-physical-replication | implemented_with_guardrails | `backend/core/config.py`, `backend/db/session.py`, `backend/tests/test_db_session.py`, `backend/tests/test_infra_evaluations.py`, `scripts/postgres_ha_drill.sh`, `scripts/postgres-ha/init-primary-replication.sh`, `docs/operations/postgresql-physical-replication.md`, `docs/operations/postgresql-ha-drill-20260615.md`, `ARCHITECTURE.md`, `docker-compose.yml`, `docker-compose.postgres-ha.yml` | Local pg_basebackup streaming replication, read-only DSN routing, marker replay, vector extension replay, and manual promotion were drilled on 2026-06-15; production still needs operator WAL archive/restore drills and HA coordinator policy before claiming fully automated HA. |
| pop3-runtime-sync | implemented | `backend/services/pop3_worker.py`, `backend/services/email_parser.py`, `backend/main.py`, `backend/tests/test_pop3_worker.py`, `backend/tests/test_main.py`, `docs/operations/email-relay-proxy-boundary.md` | Add operator scheduling knobs and production observability thresholds after customer POP3 hosts are configured. |
| reply-sla-scheduler | implemented | `backend/services/reply_sla_escalation_service.py`, `backend/services/reply_sla_scheduler.py`, `backend/api/tasks.py`, `backend/main.py`, `backend/tests/test_reply_sla_scheduler.py`, `backend/tests/test_tasks_api.py`, `README.md` | Add configurable reply deadline policies and notification channels after the scheduler path has production tenant settings. |
| data-workspace-documents | implemented | `backend/api/data.py`, `backend/db/models.py`, `backend/tests/test_data_api.py`, `frontend/src/components/DataLayout.tsx`, `frontend/src/app/data/page.test.tsx`, `frontend/tests/e2e/dashboard-branding.spec.ts`, `backend/README.md` | Replace intent-only HWP and embedding actions with source-backed worker execution only when conversion/embedding jobs have provenance and retry evidence. |
| connector-apm-history | implemented | `backend/api/observability.py`, `backend/db/models.py`, `backend/tests/test_observability_api.py`, `frontend/src/components/SettingsLayout.tsx`, `frontend/src/components/SettingsLayout.test.tsx`, `docs/operations/open-source-apm.md` | Continue showing only durable `ConnectorSignalEvent` evidence; do not expose raw runner tokens or credentials. |
| sender-dag-source-filtering | implemented | `backend/api/ontology.py`, `backend/services/ontology_service.py`, `backend/tests/test_ontology_api.py`, `frontend/src/app/search/page.test.tsx`, `README.md` | Keep Search panels tied to `source_message_id` and `source_thread_id`; do not present global sender graphs as current-thread evidence. |

## DAV PROPFIND Acceptance Evidence

The `/dav` slice is the first explicit DeepWiki Q&A implementation target.
Acceptance is covered by `backend/tests/test_dav_api.py`:

- source-backed `ProjectFolder` rows are read through `WebDavService`;
- signed session owner and organization scope is enforced;
- browser hrefs use opaque `folder_uid` values rather than sequential primary
  keys;
- `Depth: 0` and `Depth: 1` behavior is covered;
- missing folders return `404` while empty collection listings return a valid
  empty multistatus;
- XML fields are escaped before interpolation;
- log-safe path handling and mutation fail-closed behavior remain intact.

## Verification Commands

verification_command:

```bash
cd backend
python3 -m pytest tests/test_release_governance.py -q -k deepwiki
python3 -m pytest tests/test_dav_api.py tests/test_calendar_api.py tests/test_webdav_api.py tests/test_data_api.py -q
python3 -m ruff check api/dav.py api/calendar.py api/webdav.py api/data.py tests/test_dav_api.py tests/test_calendar_api.py tests/test_webdav_api.py tests/test_data_api.py

cd ../frontend
corepack pnpm vitest run src/app/data/page.test.tsx src/app/calendar/page.test.tsx src/app/search/page.test.tsx
corepack pnpm eslint src/components/DataLayout.tsx src/components/CalendarLayout.tsx src/app/data/page.test.tsx src/app/calendar/page.test.tsx src/app/search/page.test.tsx
```

## Completion Rules

Do not mark this DeepWiki Q&A goal complete only because the tracker exists.
Completion requires current-state verification of every item above. Items marked
`tracked_future_work` or `partially_implemented` remain open development goals.
