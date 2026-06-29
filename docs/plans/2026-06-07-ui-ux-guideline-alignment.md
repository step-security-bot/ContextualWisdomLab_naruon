# 2026-06-07 UI/UX Guideline Alignment Plan

## Evidence Sources
- Vooster project `XIDB` design guide for Naruon.
- `docs/ui-ux/naruon-ui-ux-mapping.md`.
- `docs/ui-ux/mockups/mockup_01.png` through `mockup_41.png`.
- Current frontend implementation on `origin/develop`.

## Audit Summary
- The latest default branch contains the canonical `docs/ui-ux` guide and 41 mockups.
- The global shell already uses Korean-first GNB labels for 홈, 메일, 일정, 작업, 프로젝트, 맥락 검색, AI 허브, 데이터, 보안, 설정.
- Home and mail surfaces mostly follow the source-backed rule by calling signed `/api/*` routes and rendering loading, empty, and error states instead of fixed metrics.
- The largest visible mismatch is the 맥락 검색 surface. `mockup_03.png` defines source chips, confidence badges, evidence-bound result details, relation graph, timeline, and execution actions. The current screen has the basic search/list/detail flow, but the source/confidence/action treatment is thinner than the design reference.
- The AI 허브 surface already reads signed `/api/ai-hub/surface` evidence, but `mockup_05.png` emphasizes explicit execution actions. Static English operational labels such as `Provider`, `Credential`, and `source evidence` should be replaced with Korean-first labels and clear navigation/actions.
- The 데이터 surface is source-backed through `/api/data/quality-surface`, WebDAV accounts, and WebDAV folders, but `mockup_04.png` presents user-facing source chips, status badges, and intent actions rather than raw internal keys. Visible `asset_key`, `thread_key`, `source_id`, raw ETag strings, event UIDs, and `provider_write_executed` flags should be hidden behind safe Korean status labels while keeping the signed API payload contracts intact.
- The 프로젝트 surface already reads signed `/api/webdav/folders` and `/api/tasks`, but `mockup_02.png` expects project list/detail, milestones, decision logs, and explicit project actions. Visible raw evidence names, folder paths, thread/email ids, and provider-write flags should be replaced with user-facing source labels, while project actions should route to implemented surfaces or switch real detail tabs.
- The 설정 surface already has seven tabs and signed account/runner APIs, but `mockup_01.png` expects source-safe settings cards, action drawers, and clear connection states. Visible `source_id`, raw ETag values, audit event names, connector event UIDs, runner registration tokens, snake_case runner roles, and raw session claims should be replaced with user-facing status labels.
- The 보안 surface is source-backed through signed `/api/security/access-surface`, but `mockup_01`/`3.9 보안` require dashboard, access control, audit log, external sharing, and policy surfaces to read like governance controls rather than raw API dumps. Visible source ids, hosts, workspace ids, audit event names, connector event UIDs, resource UIDs, provider-write flags, and internal policy evidence keys should be replaced with source-safe governance labels.
- The 작업 surface reads signed `/api/tasks` data, reply SLA escalation, and WebDAV/Notes materialization intent APIs, but it still needed the `mockup_02` task-board treatment: source-backed ticket cards, implemented action targets, no static task fixtures, no raw source ids/thread ids/paths/provider flags, and plain-text task titles.

## Implementation Plan
1. Strengthen `SearchLayout` result cards with source chips and confidence badges derived from backend score evidence.
2. Replace raw technical detail labels with user-facing evidence labels such as `증거 바인딩`, `스레드 근거`, and `신뢰도`.
3. Add a compact source-backed detail tab area for `맥락 정보`, `관계 원본`, and `판단 보조` without inventing unavailable data.
4. Add explicit actions that navigate to implemented surfaces or run the existing source-backed relationship capture.
5. Align `NetworkGraph` error copy with Korean-first designed states.
6. Align `AIHubLayout` labels and card actions with mockup_05 while keeping all metrics and lists source-backed.
7. Align `DataLayout` labels with mockup_04 by showing source readiness, evidence state, write boundaries, and conflict state without exposing internal identifiers.
8. Align `ProjectsLayout` labels and actions with mockup_02 by adding project action controls, source-safe evidence labels, milestone/decision log actions, and hiding internal folder/thread/email identifiers.
9. Align `SettingsLayout` labels with mockup_01 by preserving signed account/runner APIs while hiding source ids, raw ETags, event ids, session claims, and registration tokens behind safe Korean readiness labels.
10. Align `SecurityLayout` labels with the security governance contract by hiding raw source ids, hosts, event ids, workspace ids, and provider-write booleans behind RBAC/ABAC, audit, sharing, and policy labels.
11. Align `TasksLayout` with the task-board design by deriving board/list/detail rows from signed `/api/tasks`, routing creation to implemented mail/search surfaces, and rendering writeback/materialization responses as intent-only state.
12. Update focused tests for changed surfaces and run targeted validation.

## Implementation Progress
- Vooster project `XIDB` was queried through MCP. The connected task tracker currently has 10 tasks, all marked `DONE`; no new tracker task was created because this run is implementing the requested audit directly.
- `SearchLayout` and `NetworkGraph` now expose source chips, confidence/evidence labels, detail tabs, relationship actions, and Korean error states without inventing data.
- `AIHubLayout` now uses Korean-first source/action labels and keeps evidence tied to signed `/api/ai-hub/surface` data.
- `DataLayout` hides raw asset/thread/source keys, ETags, event UIDs, provider URLs, and provider-write booleans behind repository, ingestion, embedding, quality, write-boundary, and conflict labels.
- `ProjectsLayout` hides raw folder/thread/email/path/provider-write fields, adds implemented project actions, and keeps folder scope filtered by decoded signed-session claims.
- `SettingsLayout` hides source ids, ETags, audit event names, connector event UIDs, registration tokens, runner tokens, raw session claims, and snake_case runner roles behind readiness and governance labels.
- `SecurityLayout` hides raw source ids, hosts, workspace ids, audit event names, connector/audit event UIDs, resource UIDs, provider-write flags, and internal policy evidence keys behind governance labels.
- `TasksLayout` now derives ticket board/list/detail rows from `/api/tasks`, routes creation to `/mail`, routes delegated follow-up to `/search`, performs PATCH status updates, renders reply SLA and self-sent knowledge materialization as signed API actions, and strips HTML-like title markup from visible and accessible labels.
- `WorkspaceHome` now keeps the Today dashboard source-backed while hiding raw calendar source ids, provider labels, ETag strings, and HTML-like task title markup behind source-safe readiness and conflict labels.
- `CalendarLayout` now preserves customer-owned writeback source selection and signed `/api/calendar/writeback-intent` requests while hiding raw source ids, provider labels, raw ETags, audit event names, and writeback mode constants behind Korean calendar-governance labels.
- `EmailDetail` now keeps the server-authoritative calendar writeback intent path and removes raw provider/source identifiers from the visible mail action status.
- `EmailList` and `EmailDetail` now render untrusted email subject, sender, reply-to, snippet, and body display fields as plain text without preserving HTML-like tag markers or script block content in the UI.
- Follow-up Korean-first polish now normalizes stale AI Hub `Provider`, `Credential`, and `source evidence` labels before rendering, changes Settings source-readiness accessibility text to Korean, and removes the remaining Calendar `source` empty-state copy.
- `AGENTS.md` now records the CodeGraph autonomous init rule and the OpenCode review contract: general-purpose, meticulous reviews, relevant MCP use across CodeGraph/DeepWiki/Context7/web search, read-only focused source inspection, and durable Review Overview comments.
- `.github/workflows/opencode-review.yml` now gives the OpenCode reviewer read-only file/hunk inspection permissions, removes stale subsystem-specific prompt focus, requires broader MCP-backed review coverage, and publishes `Review Overview` through an idempotent marker with PATCH updates instead of deleting the gate evidence after approval.

## Validation Evidence
- Focused Tasks unit test: `npm run test -- src/app/tasks/page.test.tsx`.
- Focused Tasks lint: `npm run lint -- src/components/TasksLayout.tsx src/app/tasks/page.test.tsx`.
- Real browser Tasks verification passed on desktop and mobile with screenshots at `/tmp/naruon-tasks-uiux.png` and `/tmp/naruon-tasks-uiux-mobile.png`.
- Focused Home/Calendar unit tests: `npm run test -- src/app/calendar/page.test.tsx src/components/WorkspaceHome.dashboard.test.tsx`.
- Focused Home/Calendar lint: `npm run lint -- src/components/CalendarLayout.tsx src/app/calendar/page.test.tsx src/components/WorkspaceHome.tsx src/components/WorkspaceHome.dashboard.test.tsx`.
- Focused Mail unit test: `npm run test -- src/components/EmailDetail.test.tsx`.
- Focused Mail lint: `npm run lint -- src/components/EmailDetail.tsx src/components/EmailDetail.test.tsx`.
- Real browser Home/Calendar/Mail verification passed with screenshots at `/tmp/naruon-home-uiux.png`, `/tmp/naruon-calendar-uiux.png`, and `/tmp/naruon-mail-uiux.png`.
- Focused Mail display field tests: `npm run test -- src/components/EmailList.test.tsx src/components/EmailDetail.test.tsx`.
- Focused Mail display lint: `npm run lint -- src/components/EmailList.tsx src/components/EmailList.test.tsx src/components/EmailDetail.tsx src/components/EmailDetail.test.tsx`.
- Korean-first label unit tests: `npm run test -- src/app/ai-hub/page.test.tsx src/app/calendar/page.test.tsx src/app/settings/page.test.tsx`.
- Korean-first label linting: `npm run lint -- src/components/AIHubLayout.tsx src/components/CalendarLayout.tsx src/components/SettingsLayout.tsx src/app/ai-hub/page.test.tsx`.
- Typecheck validation after Korean-first label polish: `npm run typecheck`.
- Clean browser AI Hub label verification: `env -u FORCE_COLOR -u NO_COLOR npm run test:e2e -- tests/e2e/ai-hub-source-surface.spec.ts --project=desktop`.
- Clean browser Settings label verification: `env -u FORCE_COLOR -u NO_COLOR npm run test:e2e -- tests/e2e/dashboard-branding.spec.ts --project=desktop --grep "source-backed mail account settings"`.
- Strix fallback gate follow-up: first strict provider/failure-signal fallback output now advances to the next configured fallback instead of stopping the loop; a focused harness verified the order `openai/gpt-5 -> deepseek/deepseek-r1-0528 -> deepseek/deepseek-v3-0324` with final clean success.
- OpenCode workflow syntax: `actionlint .github/workflows/opencode-review.yml`.
- OpenCode targeted contract assertions verified general-purpose MCP-backed prompts, read/grep read-only permissions, durable `<!-- opencode-review-overview -->` publication, PATCH update behavior, and absence of comment DELETE calls.
- Full frontend validation after final changes: `npm run test`, `npm run lint`, `npm run typecheck`, and `POSTCSS_WORKERS=1 DISABLE_POSTCSS_WORKERS=true npm run build`.
