# DeepWiki Q&A Current-State Task Order

Baseline: 2026-06-21, `upstream/develop` `11cea8dd`

This note refreshes the DeepWiki Q&A gap review against current code. It
supersedes older gap notes where the item is now implemented.

## Scope

Naruon is a control plane over customer-owned mail, calendar, contact, and file
systems. It may index metadata, generate AI-assisted intent, and explicitly
dispatch connector commands. It must not silently become an SMTP/IMAP/MX host,
calendar provider, file store, or cross-tenant authority.

## Corrected Stale Findings

| Item | Current status | Evidence | Remaining boundary |
|---|---|---|---|
| `/dav` `PROPFIND` database backing | Implemented | `backend/api/dav.py`, `backend/services/webdav_service.py`, `backend/tests/test_dav_api.py` | Direct DAV mutations still fail closed with `501` until source/capability/credential/ETag execution is proven. |
| Alembic migrations | Implemented | `backend/alembic`, `backend/scripts/migrate_db.py`, `backend/tests/test_alembic_migrations.py` | Keep `bootstrap_db.py` local/dev only. |
| POP3 runtime sync | Implemented | `backend/services/pop3_worker.py`, `backend/main.py`, `backend/tests/test_pop3_worker.py` | Add production scheduling knobs and sync-lag telemetry. |
| Overdue reply follow-up scheduler | Implemented | `backend/services/reply_sla_scheduler.py`, `backend/main.py`, `backend/tests/test_reply_sla_scheduler.py` | Add tenant-configurable reply deadline policy and notification channels. |
| CalDAV/WebDAV provider execution | Implemented with guardrails | `backend/api/calendar.py`, `backend/api/data.py`, `backend/api/runner_ws.py`, `backend/services/provider_writeback_retry_service.py`, `backend/runner/local_dav_adapters.py` | Broader provider object types must add source-specific materialization APIs before execution. |
| OIDC browser route | Implemented with guardrails | `frontend/src/app/auth/oidc/login/route.ts`, `frontend/src/app/auth/oidc/callback/route.ts`, `backend/api/auth.py` | Production still needs selected IdP rollout, runbooks, key rotation, and mailbox-owner backfill. |

## Current Work Orders

### P0-01 PromptTemplate Tenant and Workspace Scope

Current state:

- `PromptTemplate` has only sequential `id`, `title`, `description`, `content`,
  `is_shared`, and `created_by`.
- `GET /api/prompts` and `/api/ai-hub/surface` return prompts created by the
  user or any globally shared prompt.
- This conflicts with the AI Hub source-backed plan, which says shared prompt
  rows need durable tenant/workspace scope before being returned.

Tasks:

1. Add opaque `prompt_uid`, `organization_id`, and `workspace_id` columns to
   `PromptTemplate`.
2. Create an Alembic migration and local bootstrap backfill.
3. Scope prompt reads by signed-session `user_id`, `organization_id`, and
   `workspace_id`.
4. Do not return `is_shared=true` rows unless organization and workspace scope
   matches.
5. Add tests proving an organization A shared prompt is not visible to
   organization B.

Done when:

- Prompt APIs and AI Hub prompt cards use only signed-session scoped rows.
- Cross-organization shared prompt exposure tests fail before the fix and pass
  after it.

### P0-02 Production OIDC and Mailbox Owner Migration

Current state:

- OIDC token verification and browser PKCE routes exist.
- Production multi-user access is still gated on verified IdP onboarding,
  key-rotation runbooks, and audited mailbox-owner/organization backfill.

Tasks:

1. Select the production IdP path, Keycloak first unless Casdoor is explicitly
   chosen.
2. Add operator runbooks for issuer/JWKS/client configuration and key rotation.
3. Add a dry-run migration report that maps historical email rows to verified
   mailbox owners and organizations.
4. Keep tenant-admin roles server-assigned; do not mint admin authority from
   external JWT claims.

Done when:

- A production-like OIDC session can read owner-scoped email/search/network data.
- The owner backfill report has no unmapped production rows.

### P1-01 RunnerAgent Packaging

Current state:

- `SelfHostedConnector` and local IMAP/SMTP/CalDAV/WebDAV adapters exist.
- No standalone connector package, Dockerfile, or CLI entrypoint exists.

Tasks:

1. Add a minimal `connector/` package with a `RunnerAgent` entrypoint.
2. Load registration token, WSS URL, local account registry, and DAV source
   registry from explicit environment/config files.
3. Publish a connector image through GHCR.
4. Fail closed with `adapter_not_configured` when an adapter is missing.

Done when:

- The connector image starts outside the backend container and connects outbound
  with a scoped registration token.

### P1-02 AI Hub Durable Workflow, Run, and Evaluation Stores

Current state:

- Workflow cards are derived from prompt cards.
- Run history is derived from audit/prompt update evidence.
- Evaluation metrics are readiness scores, not persisted benchmark results.

Tasks:

1. Add `WorkflowDefinition`, `AgentRunRecord`, and `EvaluationResult` tables.
2. Add signed CRUD/list APIs scoped by organization and workspace.
3. Wire AI Hub tabs to those APIs.
4. Keep empty/loading/error states honest; do not reintroduce static model-score
   fixtures.

Done when:

- Creating a workflow stores a durable row.
- Running/evaluating a workflow produces scoped run/evaluation rows visible only
  to the owning workspace.

### P1-03 Connector Observability Dashboards

Current state:

- Connector heartbeat and retry queue evidence exists.
- Sync lag, provider throttling, and writeback conflict metrics are still marked
  `instrumentation_pending` or `intent_only`.

Tasks:

1. Emit provider sync lag metrics from source-backed worker jobs.
2. Emit provider throttling and writeback conflict counters from adapter results.
3. Add a Grafana dashboard for connector status, sync lag, retry depth, and
   conflict rates.
4. Add redaction tests for email bodies, provider tokens, DSNs, and file paths.

Done when:

- Grafana shows live source-backed metrics without exposing payloads or secrets.

### P1-04 PostgreSQL Production HA

Current state:

- Streaming replication and manual promotion drills exist.
- Object-store WAL archive/restore and automated failover coordinator policy are
  still pending.

Tasks:

1. Select Patroni, repmgr, or another failover coordinator.
2. Add WAL-G or pgBackRest archive/restore scripts.
3. Extend the HA drill to prove restore and failover.
4. Record RPO/RTO and rollback procedure.

Done when:

- Primary failure promotes a replica and WAL restore succeeds in an isolated
  drill with documented RPO/RTO.

### P2-01 CardDAV Execution Path

Current state:

- Manifests mention CardDAV.
- `LocalDavSourceConfig` and connector actions only execute CalDAV/WebDAV.

Tasks:

1. Add `carddav` to connector registration schema.
2. Add `write_carddav` dispatch and local adapter support.
3. Add vCard content validation and ETag conflict tests.

Done when:

- `write_carddav` executes only with configured source, capability, credential,
  consent, and `If-Match` evidence.

### P2-02 Ontology LLM Classification

Current state:

- Sender classification uses a simple unsubscribe/domain heuristic.
- Source-backed capture and source/thread filtering exist.

Tasks:

1. Add optional LLM classifier with strict JSON output.
2. Isolate email bodies as untrusted input.
3. Store `classification_method` as `llm` or `heuristic`.
4. Fall back to heuristic when no provider is configured or LLM fails.

Done when:

- Source capture persists the classification method and tests cover LLM success,
  LLM failure fallback, and provider-absent heuristic mode.

## Verification Focus

- Backend: `tests/test_prompts_api.py`, `tests/test_ai_hub_api.py`,
  `tests/test_auth_real.py`, `tests/test_runner_connector.py`,
  `tests/test_runner_dav_adapters.py`, `tests/test_observability_api.py`.
- Frontend: AI Hub, Settings, Data, Calendar, and Search Vitest coverage plus
  route-level E2E where UI behavior changes.
- Operations: HA and connector packaging tasks require runnable smoke commands
  in addition to unit tests.
