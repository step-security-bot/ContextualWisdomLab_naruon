# Source-of-Truth and Writeback Sovereignty

## 핵심 원칙 / Core contract

- Customer-owned mail, CalDAV/CardDAV, and WebDAV systems remain the source of
  truth. Naruon indexes, summarizes, and proposes actions, but it must not become
  the only durable mailbox, calendar, contact, or file store.
- Naruon-created objects must choose an owned external account/calendar/folder or
  return an explicit no-writeback state. Local cache-only storage is not a
  sovereignty-compliant write path.
- Writeback requests must use server-authoritative source records. Client requests
  may choose a target source id, but they must not supply ownership, capability,
  credential, or region claims.
- Updates must preserve provider conflict semantics: ETag/If-Match for CalDAV and
  WebDAV, provider-specific revision ids where available, and auditable conflict
  outcomes when a remote object changed first.
- ZIP imports and forwarded mail are provenance sources, not new mailbox owners.
  Dedupe uses mailbox/source keys, Message-ID, content fingerprints, forwarded
  chain metadata, and attachment hashes to link duplicates to a canonical thread.

## Connector boundary

- Private-network protocols are reached by an outbound-only self-hosted connector
  running in the customer's network or VPC.
- The connector opens a control-plane channel to `naruon.net`; Naruon does not
  require inbound firewall holes, public MX records, or public IMAP/SMTP listener
  ports in the customer network.
- GitHub self-hosted runners remain CI smoke infrastructure. They can validate
  internal connectivity, but they are not the production relay component.

## Source registry contract

Every writeback-capable account should resolve through a server-authoritative
source registry before any provider mutation is attempted. The registry record
must include an opaque `source_id`, tenant/workspace owner scope, protocol
(`imap`, `smtp`, `pop3`, `caldav`, `carddav`, `webdav`), provider host, capability
flags, consent state, data region, connector route, credential reference, and
conflict metadata such as remote ids or ETags. Browser requests may reference
`source_id`, but must never supply ownership, credential, region, or capability
claims.

Implemented slices currently cover signed task/mail provenance, dedupe/threading
contracts, source-linked ticket tasks, self-sent knowledge capture into
idempotent ticket tasks, deterministic sender ontology action hints, generic
WebDAV writeback intent, source-backed Today dashboard pending reply reads from
`/api/emails/pending-replies`, self-sent knowledge WebDAV/Notes materialization
intent, overdue-reply follow-up into idempotent source-linked `reply_sla`
ticket tasks, DB-backed CalDAV intent source selection through opaque
`calendar_writeback_sources.source_uid` rows exposed to the Calendar workspace
through a signed source-registry read, and WebDAV intent selection through
opaque, organization-scoped `webdav_accounts.source_uid` rows with persisted
writeback eligibility; sequential `webdav_accounts.account_id` values remain
internal and are not browser-visible source identifiers. WebDAV project folders
now expose opaque `project_folders.folder_uid` values, scope listing by the
signed-session `user_id` and `organization_id`, and keep sequential folder
primary keys internal. `/dav` mutation methods fail closed until provider
execution can enforce source, capability, credential, and ETag/If-Match checks.
The Data workspace can create scoped workspace document rows through signed
`POST /api/data/documents` and can request reparse, embedding regeneration
intent, and HWP conversion intent for the selected opaque `document_id`; these
actions update control-plane document status only and return
`provider_write_executed=false`. Selected workspace documents can also request
signed WebDAV materialization through
`POST /api/data/documents/{document_id}/webdav-materialization-intent`: the
backend re-reads the document from the signed `workspace_id`, derives the target
path and Markdown content server-side, validates the selected opaque WebDAV
`source_uid` through the scoped source registry, and dispatches `write_webdav`
only when the user explicitly sets `execute_provider=true`.
The Python connector now has local CalDAV/WebDAV PUT adapters that enforce
configured opaque source ids, source writeback enablement, safe target paths, and
`If-Match` before provider execution. The Calendar writeback intent endpoint and
the WebDAV materialization endpoint can dispatch signed commands to an active
outbound runner when the caller explicitly sets `execute_provider=true`; Calendar
dispatch additionally fails closed before runner dispatch unless the selected
source has If-Match evidence. Runner command dispatch, response success, timeout,
connection failure, and adapter failure outcomes persist scoped
`ConnectorSignalEvent` rows without storing provider credentials or command
payloads. Transient writeback dispatch failures (`runner_not_connected`,
`runner_response_timeout`, and `runner_dispatch_failed`) also enqueue scoped
`provider_writeback_retry_items` rows with encrypted command payloads so a later
worker can retry without treating Naruon as the provider source of truth. The
backend starts a scoped retry worker that dispatches due retry items with retry
enqueue disabled, marks successful provider writes as `succeeded`, reschedules
retryable transient failures with exponential backoff, and marks exhausted
items as `failed_exhausted`. Organization-admin observability reads surface only
aggregate queue depth by state from `provider_writeback_retry_items`, not queued
payloads, provider credentials, or retry item identifiers. The Calendar
workspace now exposes an explicit ETag-guarded execution request control that
sends `execute_provider=true` only for selected customer-owned sources and
redacts runner/retry/audit identifiers from the browser UI. Self-sent knowledge
tasks expose the same deliberate execution boundary for WebDAV/Notes
materialization: users can create intent-only evidence or explicitly request
connector execution, and the UI shows execution/retry state without exposing
target paths, opaque source ids, runner ids, retry ids, or audit event names.
Data workspace document materialization follows the same deliberate execution
boundary for uploaded workspace documents. Configurable reply deadline policy storage and
any remaining source-registry expansion remain episode work and must preserve
this registry boundary.

## Policy and audit requirements

- RBAC grants are necessary but never sufficient when ABAC denies apply. Region,
  consent, workspace, group, source capability, customer policy, and
  data-residency denials take precedence over broad roles.
- A permitted `platform_admin` can cross organization and resource ownership
  boundaries in Naruon's pure access-policy evaluator, but writeback still must
  use server-authoritative source records, provider capabilities, consent, and
  conflict-aware revisions before any customer-owned system is changed.
- Every writeback intent should record `actor`, `workspace`, `source_id`,
  `protocol`, `remote_id`/`etag` where available, `action`, and conflict result.
- Observability must redact email body, secrets, provider tokens, DSNs, contact
  details, and calendar descriptions unless an explicit tenant policy permits a
  narrower diagnostic sample.
