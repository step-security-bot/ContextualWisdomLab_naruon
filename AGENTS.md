# AGENTS.md

## Release governance defaults

- GitHub Actions used by governed workflows must be pinned to full commit SHAs
  with a trailing version comment, for example `# v6`; major-only refs such as
  `@v6` are not allowed in release or security workflows.
- Security scanners are required gates. Do not use `continue-on-error: true` to
  hide Bandit, Strix, CodeQL, or dependency findings; preserve artifacts with
  explicit `if: ${{ always() }}` upload steps when needed.
- Repository rulesets that require code-scanning tools such as Scorecard or
  Trivy must have matching PR and default-branch workflows that upload those
  tools' SARIF results. If merge is blocked with "Code scanning is waiting for
  results from Scorecard" or another ruleset-required tool, restore the missing
  SARIF workflow and rerun it instead of bypassing or weakening the ruleset.
- Required OpenCode Review, Strix Security Scan, and PR Review Merge Scheduler
  are central required workflows supplied by `ContextualWisdomLab/.github`.
  Naruon must not carry repo-local OpenCode, Strix, Strix self-test,
  quick-gate, or PR review merge scheduler workflow copies. Change their
  behavior in the central `.github` repository, then let the organization
  required workflow ruleset run them in this repository.
- Prefer upgrading or removing vulnerable dependencies over downgrading patched
  packages unless compatibility evidence is recorded in the PR.
- Strix provider selection, model fallback, retry policy, report parsing, and
  failed-check review behavior are owned by the central workflow. If a Naruon PR
  exposes false approval, missing failed-check explanation, malformed Mermaid,
  stale branch, or missing update-branch behavior, patch the central workflow and
  use this repository only as live evidence for the organization-level contract.
- HMAC fallback sessions are local/control-plane compatibility credentials, not
  authoritative workspace-membership evidence. Sensitive tenant security posture
  surfaces must require OIDC/JWKS-backed membership or an explicit dependency
  override in tests; do not allow a signed HMAC `workspace` claim alone to open
  cross-workspace security data.

## PR automation and review defaults

- Follow `docs/development/merge-gate-policy.md` for PR gate interpretation.
- PR Governance must stay metadata-only: no PR-head checkout, no admin merge, no
  review dismissal, and no security-check suppression.
- Pending/queued checks and pending CodeRabbit evidence are wait states, not hard
  failures. Hard blockers should be reported through the idempotent
  `<!-- pr-governance:metadata-gate -->` comment path.
- Missing current-head CodeRabbit evidence is a wait state until bounded polling
  or authoritative skip/review evidence resolves it; do not post a hard blocker
  only because the current head has not been reviewed yet.
- OpenCode Agent approvals must be gated on current-head GitHub Checks. If a
  completed check run or status context failed, or the check rollup cannot be
  verified, the OpenCode review must request changes or explain the verification
  failure instead of approving.
- When OpenCode requests changes because Strix or another GitHub Check failed,
  it must access the failed check logs and annotations, cite the exact failure
  phrase, map each actionable failure to a concrete repository `path:line`, and
  provide root cause, fix direction, regression-test direction, and a
  source-backed suggested diff. A review that only cites a workflow URL, check
  name, or generic failure summary is not sufficient. If Strix output contains
  multiple model vulnerability reports, include every model-reported
  vulnerability separately with the model name, title, severity, endpoint, and
  Code Locations/path:line evidence when present.
- Strix logs may print the report's `Model ...` line after the title, endpoint,
  and Code Locations block. Failed-check evidence parsers and OpenCode review
  validators must attribute each vulnerability to that in-report model line, not
  to a previous retry attempt such as a failed primary `openai/gpt-5` run.
- OpenCode Agent PR reviews must be general-purpose and meticulous rather than
  narrowly scenario-specific. Configure the review prompt to use all relevant
  MCP sources: CodeGraph for structural source evidence, DeepWiki for repo docs,
  Context7 for current library/API behavior, and web search only for bounded
  external lookups. The agent may directly read changed files and focused hunks
  in read-only mode when MCP evidence is insufficient, but must not edit files
  or execute project code during the review.
- OpenCode Agent findings should be concrete and directly usable: each blocking
  finding should name the observable impact, the trigger condition or affected
  workflow, the smallest source-backed fix, and an exact verification command or
  test target when the repository already has one. Avoid generic architecture
  advice unless it maps to the cited `path:line`.
  When GitHub reports a merge conflict, include a concrete conflict-resolution
  direction instead of only saying the PR is blocked: name the base/head branch,
  tell the author to merge or rebase the latest base branch into the PR branch,
  resolve conflict markers in the changed files, rerun the focused checks, and
  push the same branch.
  For Greptile-style specificity, carry a P1/P2/P3 priority in each finding,
  cite the evidence type that justifies it (nearby implementation, matching
  existing example, cross-file counterpart, current official docs, or failed
  check/log evidence), flag unrelated PR scope drift as scope risk instead of
  burying it in style notes, and make `suggested_diff` a GitHub
  suggestion-ready minimal diff when possible. Include one compact Mermaid
  graph in the human-readable review body that maps the changed surface to the
  main risk, fix, and verification path.
- OpenCode `Review Overview` comments are durable gate evidence. Publish them
  through an idempotent marker such as `<!-- opencode-review-overview -->` and
  update the existing comment instead of deleting it after approval, failed
  checks, or check-rollup lookup failures.
- Keep CodeRabbit `request_changes_workflow` enabled for robot approval, but
  keep CodeRabbit GitHub Checks integration disabled. GitHub Actions are already
  evaluated by required checks and PR Governance; letting CodeRabbit also gate
  on Actions can strand a stale GitHub `CHANGES_REQUESTED` review when an
  external scanner such as direct-OpenAI Strix is quota-blocked after comments
  are fixed.
- `STARTUP_FAILURE` in required PR governance/check metadata is a hard blocker
  and should use the same idempotent metadata-gate comment path.
- Trusted-base governance materialization must tolerate transient GitHub API
  truncation such as `unexpected end of JSON input` with bounded retries and
  archive validation; do not convert that infrastructure flake into a CodeRabbit
  or review blocker.

## Workspace and task tracking defaults

- First-run frontend sessions should open the Today execution dashboard while
  preserving explicit Dashboard, Email, and Calendar startup choices.
- Workspace navigation changes must keep the desktop primary nav and the
  tablet/mobile drawer in sync for Mail, Calendar, Tasks, Projects, Context
  Search, AI Hub, Data, Security, and Settings; add route and responsive E2E
  coverage instead of documenting unavailable destinations as implemented.
- Workspace destination pages must show actionable detail surfaces, not inert
  marketing placeholders. Calendar needs month/week/detail/coordination and
  CalDAV writeback states; Tasks needs source-linked ticket boards/details;
  Search needs result/detail graph/timeline states; Projects needs decision logs;
  Data needs repository/ingestion/embedding/quality/WebDAV queues; Security and
  Settings need governance and operational control surfaces. Keep provider writes
  labeled as future work until source-backed integrations exist.
- Browser frontend writes to signed backend routes must use the HttpOnly
  `naruon_session` cookie through the same-origin Next.js `/api/*` proxy, which
  translates the server-readable cookie into backend `Authorization: Bearer`.
  Browser code must not store bearer/session tokens in `localStorage` or
  `sessionStorage`, and must not emit or forward public identity headers such as
  `X-User-Id`, `X-Organization-Id`, `X-Group-Id`, `X-Group-Ids`, `X-User-Role`,
  or `X-Dev-Auth-Token`; tests/mocks must exercise the signed-session cookie
  path.
- Frontend Docker, Compose, and publish workflows must not compile or inject a
  public `NEXT_PUBLIC_API_URL` into browser bundles. Browser API calls stay on
  same-origin `/api/*`; only server-side Next.js route handlers should read
  runtime `BACKEND_INTERNAL_URL`, with the exact Docker-network opt-in when
  running local Compose.
- JWT/session verification must reject unsupported critical headers (`crit`)
  before trusting payload claims; do not rely only on library defaults for this
  boundary.
- Session authority is a server-side verification result, not a token payload
  claim. HMAC and OIDC paths must pass `session_verifier` from the code path that
  validated the signature/key; never derive it from `_session_verifier` or a
  similar user-controlled JWT claim.
- Private backend `/api/*` routers must be registered with the default
  `get_auth_context` signed-session dependency; only explicitly documented
  public endpoints such as `/` may omit it. Keep runtime feature/configuration
  endpoints signed-session protected; if the browser needs unauthenticated
  bootstrap data, add a narrowly scoped non-`/api` endpoint that cannot reveal
  operational feature flags or provider state.
  Prometheus `/metrics` must stay disabled by default and, when enabled, sit
  behind a trusted scrape path or reverse proxy access policy. Admin/provider
  registry endpoints must enforce role checks in addition to authentication. LLM
  provider `base_url` values must fail closed unless they are HTTPS, exact-host
  allowlisted by `ALLOWED_LLM_BASE_URL_HOSTS`, and resolve only to global
  addresses. Runtime LLM calls that use a custom provider `base_url` must build
  their `httpx` client through `build_llm_provider_http_client` so TCP connects
  only to prevalidated global IP addresses while TLS/SNI still uses the
  allowlisted hostname; do not hand a freshly validated URL to a generic client
  that can resolve DNS again at connect time.
- OIDC issuer and JWKS URLs are outbound identity-provider fetch surfaces. They
  must use HTTPS, must not include userinfo or fragments, must reject localhost
  and non-global IP literals, and must be exact-host allowlisted by
  `ALLOWED_OIDC_HOSTS` before any JWKS preload or token verification path can
  use them. Allowlisted OIDC hostnames must also resolve only to global
  addresses, and JWKS retrieval must connect to the already validated pinned
  address while preserving TLS/SNI for the allowlisted hostname.
- Email-derived tasks must stay source-linked to the email/thread and tenant
  owner scope. Do not expose new sequential database ids through task APIs; use
  opaque public ids for user-visible ticket tasks. Task titles are plain text:
  reject HTML-like execution item markup at the backend boundary rather than
  storing user-supplied tags for later UI rendering. Parsed email display fields
  must not persist active HTML/script markup, and email API list/detail/thread
  responses must sanitize stored subject/body/snippet/address display fields
  before returning them. Preserve message/thread identifiers separately from
  UI-safe subject/body, address, and attachment display text.
- Email file import must keep frontend file pickers, `/api/emails/import-files`,
  and `services.email_import_service` in the same source-backed contract:
  supported uploads are `.eml`, `.zip`, and `.mbox`; imported email and
  attachment vectors must use the active organization LLM provider's
  `embedding_model` and `base_url` when configured, fit provider vector
  dimensions to storage, and fall back to zero vectors only when provider
  embedding generation is unavailable. Tests must cover the local
  `embeddinggemma` path so Data workspace imports do not silently bypass the
  selected embedding model.
- Home/Today dashboard reply-wait surfaces must read signed
  `/api/emails/pending-replies` data instead of inferring pending replies from
  generic inbox fixtures or static copy. Tests and E2E mocks must verify the
  HttpOnly `naruon_session` cookie proxy path and must not add public identity
  headers.
- TenantConfig/provider account settings must be scoped by signed-session
  `user_id` and `organization_id`; do not query provider credentials or API keys
  by `user_id` only. Frontend Settings onboarding must use bearer-session API
  calls for account config, CalDAV/WebDAV source readiness, and runner token
  rotation, and mocks must not reintroduce public identity headers.
- Self-service mailbox configuration routes must enforce owner-required
  RBAC/ABAC through `services.access_policy`; system/platform admins may not use
  user-facing `/api/config` routes to read or mutate another user's mailbox
  credentials. Cross-user administration needs a dedicated audited admin route.
- Workspace-scoped resources must carry `workspace_id` through both
  `AccessRequest` and `ResourcePolicy`, and SQL scopes for WebDAV/Data/Security
  surfaces must filter the current workspace in addition to owner and
  organization. Do not expose same-organization cross-workspace records.
- User-owned mailbox/provider account endpoints must not treat `system_admin`
  or `platform_admin` JWT roles as an owner session. Elevated operators need
  separate audited support flows; `/api/accounts/config` must reject forged or
  orgless privileged sessions before credential lookup, and tests must exercise
  the real signed bearer path rather than only dev public-header overrides.
- HMAC fallback sessions must not authorize `system_admin` or `platform_admin`
  roles. Platform-wide operators require the OIDC/JWKS path or a separately
  audited support flow so compromise of an HMAC session secret cannot mint
  platform administrator claims.
- `AUTH_SESSION_HMAC_SECRET` validation must enforce byte length, distinct
  character count, character-class diversity, placeholder/public-fixture
  rejection, and an explicit estimated entropy floor; keep runtime-secret tests
  aligned so long low-entropy strings cannot pass by length alone.
- Reply-wait task escalation must reuse the server-authoritative pending reply
  path, create or update source-linked `reply_sla` ticket tasks by opaque task
  id, and sanitize generated task titles from email subjects before persistence.
  Do not create duplicate reminder tasks for the same pending sent-mail message.
- Mail connection updates and workers must validate server-side SMTP, POP3,
  IMAP, and relay destinations before persistence or network connection. POP3
  credentials are required for POP3 sync;
  missing credentials must fail the sync path instead of logging a successful
  no-op. Do not place sensitive credential values, secret-derived values, or
  password-shaped field names in logs or raised exception text; use generic
  operation phrases such as "account configuration incomplete" instead of
  credential-type labels.
- SMTP, IMAP, and POP3 host validation must reject legacy numeric IP literal
  forms such as decimal integers, hexadecimal integers, and octal dotted forms
  before DNS or socket connection; `socket.getaddrinfo` may resolve those forms
  to loopback/private addresses even when `ipaddress.ip_address` rejects them.
- GitHub Actions `run:` blocks must not directly interpolate `${{ github.* }}`,
  `${{ inputs.* }}`, or other expression data into shell conditions or commands.
  Pass expression values through step `env:` keys first, then quote shell
  variables such as `"$IS_PR_EVIDENCE_RUN"` inside the script. PR base/head
  SHA values from manual workflow inputs must be regex-validated as git SHAs
  before any fetch, diff, or artifact metadata use.
- Privileged `pull_request_target` scanner jobs must treat PR-head blobs as
  non-executable input data. When copying PR-head files into temporary scan
  scopes, strip executable bits instead of preserving `100755` modes. PR-scoped
  Strix workflow runs should use the explicit `STRIX_TARGET_PATH=__PR_SCOPE__`
  sentinel so the trusted base checkout is never presented as the PR scan
  target. Strix child processes that inspect untrusted PR scope data must set
  package-manager lifecycle script guards such as `NPM_CONFIG_IGNORE_SCRIPTS`,
  `PNPM_CONFIG_IGNORE_SCRIPTS`, and `YARN_ENABLE_SCRIPTS=false`; do not allow a
  scanner dependency install to execute PR-provided `package.json` scripts.
- Test harness HTTP smoke helpers must not use broad URL opener APIs such as
  `urllib.request.urlopen`; keep URL scheme validation and use explicit HTTP or
  HTTPS clients so Bandit/Strix do not normalize test-only SSRF patterns into
  production examples.
- Screenshot and browser-capture helper scripts must build navigation targets
  from a fixed localhost origin and an explicit route allowlist before calling
  Playwright `page.goto`; do not concatenate raw route or URL strings, and log
  capture failures with fixed message templates plus sanitized fields.
- Alembic migrations must use structured Alembic/SQLAlchemy operation APIs such
  as `op.create_index` and `op.drop_index` for schema objects. Do not build DDL
  with `sa.text(f"...")` or interpolated identifier strings, even when the
  current identifiers are static.
- Infrastructure Docker Compose services must inherit the repo hardening
  contract: `no-new-privileges:true`, `read_only: true`, read-only config
  mounts, and explicit `tmpfs` entries for the few runtime paths that must be
  writable.
- Settings account screens must be source-backed by signed-session APIs rather
  than static provider examples. Display only masked secret presence flags, keep
  blank secret fields out of save payloads so stored values are preserved, and
  do not reintroduce public identity headers in frontend account mocks.
- New database tables and columns must use at least two-word `snake_case` names;
  avoid single-token columns such as `id`, `title`, `status`, or `priority` on
  newly introduced objects.
- Public audit/event identifiers that may use human-readable prefixes must not
  be stored in artificially short `varchar(n)` columns; use opaque source UIDs
  that fit seeded smoke data and provider evidence without truncation.
- When reviews find public/private identifier leaks, stale API fixture shapes, or recurring bug patterns, update tests, frontend mocks, E2E mocks, README examples, architecture docs, and explicitly record the anti-pattern in `AGENTS.md` so the same bug pattern does not reappear in copied examples.
- When reviews find missing browser security headers or tabnabbing hardening,
  update both backend header tests and frontend link tests. Global backend
  responses must include `Referrer-Policy`, and `target="_blank"` links must
  use explicit `rel="noopener noreferrer"`.
- When robot review cites an obsolete Strix provider policy, update the docs and
  tests to the current GitHub Models default contract before accepting a
  rollback suggestion; do not reintroduce generic `LLM_API_KEY` or
  cross-provider credential forwarding while trying to satisfy old comments.
- When reviews find inert navigation/dead-space controls, either wire them to an
  implemented workspace route/API or remove the control; do not leave
  high-traffic drawer/sidebar entries as permanent `준비 중` copy.
- AI Hub tabs must be backed by signed source evidence from `/api/ai-hub/surface`
  or a narrower signed API. Do not reintroduce static model-score fixtures,
  fake workflow logs, or provider names that are not derived from prompt,
  provider, or audit data.
- Data document repository assets must be backed by signed
  `/api/data/quality-surface` evidence from scoped email and attachment rows.
  Do not reintroduce static file lists, sequential attachment/email ids, raw
  message ids, raw thread ids, message bodies, provider URLs, usernames,
  credentials, or claims that Naruon itself stores customer file capacity.
- Icon-only workspace controls must carry localized `aria-label` text matching
  the visible app language; do not rely on the SVG icon alone for Calendar,
  Tasks, drawer, modal, or toolbar actions.
- Execution steps resulting in `Timeout`, `Fatal`, `Warn`, or `Denied` outputs are considered hard failures. Tests must run without these warnings to be considered passing.
- Strix success artifacts must also be scanned for `Timeout`, `Fatal`, `Warn`,
  or `Denied` output before accepting clean evidence. Filter only narrowly known
  third-party Strix internal warnings, such as the
  `strix.core.execution` non-lifecycle continuation line, before artifact upload;
  fail closed on any remaining warning-class report log output.
- DB-affecting API slices need both mocked fast tests and a real PostgreSQL
  bootstrap/smoke path before PR merge evidence is considered complete.
- When a backend container reports missing `DATABASE_URL` or
  `AUTH_SESSION_HMAC_SECRET`, verify the runtime path injects the operator env
  through `scripts/naruon_compose.sh`, Kubernetes secrets, or an explicit
  orchestrator secret. Do not add code defaults, and do not mount or declare the
  full `~/.env` as a Compose `env_file` because unrelated local secrets may leak
  into the backend container.
- Backend container entrypoints must pass through `python scripts/start_backend.py`
  before `uvicorn` imports `main:app`. Do not reintroduce Dockerfile, Compose,
  live-E2E, or gateway commands that call `uvicorn main:app` directly and expose
  Pydantic import tracebacks for missing runtime settings.
- DAV/WebDAV/CalDAV routes are private integration surfaces unless explicitly
  documented otherwise. Register them with the default signed-session dependency,
  require the signed-session dependency in handler signatures, enforce route
  owner scope before capability/discovery/read/writeback responses, reject
  ownerless DAV paths instead of treating them as shared roots, escape XML
  response fields before interpolation, and keep path values separate from
  log-safe display values.
- Self-hosted runner WebSocket routes must validate both a signed bearer session
  and a server-side WorkspaceRunnerConfig registration token before accepting the
  socket. Do not use the raw path token as identity, a log value, or the sole
  active-connection key.
- Self-hosted connector command handlers must never return placeholder or mock
  success for IMAP/SMTP execution. If no local customer-network adapter is
  configured, fail closed with `adapter_not_configured` and
  `provider_write_executed=false`; if an adapter is configured, wrap only the
  adapter's actual result in the standard runner response envelope.
- Calendar UI actions must request `/api/calendar/writeback-intent` with
  server-authoritative source selection and provenance. Do not wire browser
  actions back to legacy `/api/calendar/sync` unless a trusted backend credential
  dependency and source-owner contract are explicitly in scope.
- Calendar writeback UI must fail closed while the signed source registry is
  loading or errored; do not emit intent POSTs without a confirmed opaque
  `target_source_id`, and keep tests covering the loading/error boundary.
- Calendar and WebDAV workspaces must expose the current opaque writeback source
  as a deliberate user selection with capability and ETag/If-Match state.
  Automatic first-source fallback may initialize the control, but intent POSTs
  must use the selected opaque source and `409` responses must render as
  conflicts, not generic errors or completed writes.
- Calendar and WebDAV writeback source selection must resolve through opaque
  `source_uid` values, signed-session organization scope, and persisted
  writeback eligibility, not sequential CalDAV or WebDAV account ids.
  Missing writeback eligibility must fail closed. Browser-visible source ids
  must not reveal or be deterministically derived from account primary keys.
  WebDAV account readiness may expose only source-safe labels and ETag/If-Match
  evidence, never provider URLs, usernames, credentials, or sequential account
  ids. Provider mutations remain future work until connector execution can
  enforce capability, consent, and ETag/If-Match checks.
- DAV/WebDAV folder and write paths must not expose sequential folder primary
  keys or claim provider write success from skeleton endpoints. Browser-visible
  project folders use opaque `folder_uid` values, and `/dav` mutation methods
  must fail closed until source, capability, credential, and ETag/If-Match
  execution exists.
- WebDAV folder listings must stay tenant-scoped by both `user_id` and signed
  session `organization_id`; do not reintroduce user-only folder queries because
  the same principal can exist in multiple B2B tenants.
- Mobile workspace drawers must lock background body scroll while open and keep
  the drawer itself scrollable; responsive E2E screenshots should cover the open
  hamburger state after scrolling the drawer.
- Self-sent knowledge extraction must first prove true self-to-self addressing,
  stay idempotent per source email, preserve email/thread provenance, and store
  only plain-text task titles. Do not create unlinked knowledge tasks from raw
  dict payloads when the source email row is unavailable.
- Self-sent knowledge WebDAV/Notes materialization requests must start from an
  opaque task uid, re-check owner and organization scope server-side, reject
  non-`self_sent_knowledge` tasks, and return intent metadata only until the
  connector/provider write path has source-backed ETag conflict handling.
- Private API services should return deterministic `error_code` values for
  expected failures; route layers must not derive HTTP status from human-readable
  message substrings.
- UI async state for repeated task/action rows must be keyed by the row's opaque
  public id so one row's loading, error, or result state cannot overwrite another
  row.
- Sender ontology and relationship DAG APIs must stay scoped to the signed
  session owner and organization. Source-backed UI panels must request
  `source_message_id` and `source_thread_id` filters instead of presenting a
  global relationship graph as if it were current-thread evidence.
- Sender DAG capture must start from a signed source email lookup, not
  browser-submitted relationship classifications. Route layers should derive the
  thread provenance server-side, persist only scoped ontology metadata, and keep
  provider writes out of relationship capture.
- Unique email and forwarded-import dedupe must use strong scoped signals:
  normalized Message-ID, References/In-Reply-To, persisted duplicate provenance,
  or exact body/attachment fingerprints. Do not merge threads from subject-only
  `Fwd:` or `Re:` similarity, and keep duplicate cleanup intent-only until
  provenance persistence and source-backed import rewiring are implemented.
- Operational dashboards must distinguish live server-observed state from
  planned instrumentation. Show connector registration and active outbound
  runner socket state when available, but label sync lag, provider throttling,
  queue depth, and writeback conflict dashboards as pending until source-backed
  connector events exist.
- Security governance screens must be source-backed by signed
  `/api/security/access-surface` data. Do not ship static RBAC/ABAC rows, fake
  blocked-login logs, unsupported TLS/TDE claims, or permanent Security tab
  placeholders as implemented features. The browser-facing Security API and UI
  must not expose source ids, event ids, decision ids, review ids,
  workspace/org/user/group claims, provider execution flags, raw hosts, or
  resource UIDs; render scoped governance labels instead. New Security mocks and
  E2E fixtures must preserve bearer-session calls and omit public identity
  headers.
- Data workspace repository, ingestion, embedding, and quality surfaces must be
  source-backed by signed `/api/data/quality-surface` data or explicitly labeled
  pending. Do not ship static ingestion logs, fake progress percentages, fake
  vector counts, unsupported embedding model names, static quality totals, or
  provider-write success claims; Data mocks and E2E fixtures must preserve the
  bearer-session call and omit public identity headers.
- Project workspace lists, milestones, task links, and decision logs must be
  source-backed by signed `/api/webdav/folders` and `/api/tasks` data or
  explicitly labeled pending. Do not reintroduce static project names, inert
  report/filter buttons, provider write success claims, or sequential database
  ids in project UI/tests.
- Project workspace folder rendering must prove owner scope before display:
  `/api/webdav/folders` includes server-scoped `owner_user_id` and
  `organization_id`, and the browser filters those folders against decoded
  signed-session claims before building project cards. Keep `folder_uid` as an
  internal opaque key only; do not render it as visible UI text.
- Self-hosted connector APM history must be persisted as scoped control-plane
  signal events before the UI claims durable heartbeat evidence. Do not expose
  runner registration tokens, path tokens, or raw provider credentials in event
  ids, details, logs, Settings mocks, or E2E fixtures.

## Development environment and tooling defaults

- If CodeGraph is not initialized for this repository, agents may run
  `codegraph init -i` autonomously without asking first; keep generated
  `.codegraph/` and `.cursor/rules/codegraph.mdc` artifacts local unless a
  future repository policy explicitly says to commit them. OpenCode PR review
  uses the project `opencode.jsonc` MCP servers for CodeGraph, DeepWiki,
  Context7, and web search. It must initialize CodeGraph before review so
  structural findings cite graph-backed evidence instead of relying only on grep
  or raw file reads; use Context7 for current library docs, DeepWiki for
  repository documentation, and web search only for bounded external lookups.
- StepSecurity `harden-runner` will trigger false-positive `suspicious_file_access` lockouts on Next.js build and dev server executions (e.g., `router_init.js` checksum matches). Configure `disable-file-monitoring: true` in the `harden-runner` step rather than disabling the workflow or using `continue-on-error`.
- Next.js 15+ Turbopack resolves workspace roots by scanning upward for `package-lock.json`. Do not create or leave a `package-lock.json` in the user's home directory (`~/`), as it will cause Turbopack to spawn infinite background worker node processes attempting to compile the entire home directory.
- `pydantic-settings` strictly rejects unexpected environment variables by default. When sharing a common `.env` file between frontend and backend services, you must explicitly set `extra="ignore"` in the `SettingsConfigDict` to prevent fatal startup crashes.
- Backend startup must not add code defaults for `DATABASE_URL` or
  `AUTH_SESSION_HMAC_SECRET`. Support explicit env files from the operator,
  repository root, and backend working directory, and require Compose/Kubernetes
  to inject the mandatory values so missing runtime configuration fails before
  deployment rather than during `uvicorn main:app` import.
- Python standard library `re` flags (`re.IGNORECASE`) must be passed via the `flags=` keyword argument. Do not use inline `(?i)` at the start of the expression, as it will trigger `DeprecationWarning` regressions in Python 3.11+ test suites.
- Next.js builds in memory-constrained CI environments (e.g., GitHub Actions) can fail with OOM errors due to PostCSS worker explosion. Set `POSTCSS_WORKERS: "1"` and `DISABLE_POSTCSS_WORKERS: "true"` in the build environment to limit memory usage.
- Release version bumps must keep `VERSION`, `CHANGELOG.md`,
  `frontend/package.json`, FastAPI app metadata, runtime-config responses, and
  Docker runtime packaging synchronized. The backend should read the release
  version from `VERSION`; do not add a new hardcoded API version string.
- Before opening a PR, new committers should run the focused tests that cover
  the changed contract and include exact commands in the PR body. For release
  and Docker changes, at minimum verify `python -m pytest
  backend/tests/test_release_governance.py backend/tests/test_runtime_config_api.py
  -q`, `corepack pnpm@11.5.3 --dir frontend test --runInBand` when frontend
  behavior changes, and a Docker build of the affected image.
- GHCR publishing evidence for the combined `naruon` image must include the
  exact image name, tag, local image ID, push result, and registry verification
  from GitHub Packages or an equivalent manifest/API query. Publish the package
  with public visibility unless a repository policy explicitly says otherwise.
  Do not treat a local tag as published evidence. GitHub's REST Packages API and
  GraphQL package mutations currently do not expose a supported package
  visibility change operation for GHCR container packages; when API checks show
  `visibility: private`, complete the public conversion through the logged-in
  GitHub package settings UI (`Package settings` -> `Danger Zone` -> `Change
  visibility`) and then verify anonymous pull/token access before declaring the
  image public.
- Docker image security inspection is part of release evidence. Use a current
  container scanner such as Trivy or Grype against the exact pushed image tag
  and treat high/critical actionable findings as blockers until fixed or
  documented with precise non-applicability evidence.
- Docker Compose and Podman live-E2E work must clean up after itself. Stop
  stale `naruon*` containers, remove unused volumes/layers with
  `podman system prune --all --volumes --force` when safe, and verify
  `podman ps` has no stale Naruon services. If Podman reports broken storage
  metadata such as missing overlay layers or `readlink ... overlay: invalid
  argument`, run `podman system check --repair --force` before relying on
  `podman system df` or additional image scans.
- Keep contributor setup friction low: document any new required environment
  variables, model tags, package-manager version pins, or live-E2E ports in the
  same PR that introduces them, and avoid hidden local-only defaults that make
  another committer's PR fail after checkout.

## Phase 10 development rules

- **Stepwise execution**: Each phase requires an atomic PR, GitHub PR Tracking, Push, and Robot Review. A phase only ends when merged. Do not proceed without merge.
- **TDD + DDD**: Practice TDD, micro TDD, nano TDD, Domain Driven Development, and Context Driven Development.
- **API Wiring**: Always work with API wiring completed.
- **Collaboration**: Respect other agents' concurrent work; do not overwrite or dismiss unfamiliar changes.
- **Subagent Delegation**: Actively delegate tasks to Subagents.
- **UI/Browser Testing**: Use a real browser for testing (do not rely on assumptions).
- **Strict Errors**: Treat `Timeout`, `Fatal`, `Warn`, and `Denied` outputs as hard failures.
- **Goal**: Actively manage tasks to ensure open PR counts converge to 0.

- When the gate exhausts fallbacks after the primary model produces a finding at or above threshold and then fails with a retryable error (like `NOT_FOUND`), ensure the final output explicitly reports `Strix quick scan failed with a non-recoverable error.` to prevent downgrading the finding to pass or misleadingly reporting an unavailability error.
