export type WebdavWritebackIntentResponse = {
  intent: string;
  source_id: string | null;
  target_label: string | null;
  requires_if_match: boolean;
  if_match?: string | null;
  provenance: string;
  status?: string | null;
  message?: string | null;
};

export type WritebackStatus = 'idle' | 'loading' | 'success' | 'no_source' | 'fetch_error' | 'conflict' | 'auth' | 'error';
export type WebdavAccountStatus = 'loading' | 'ready' | 'error';

export type WebdavAccount = {
  source_id: string;
  display_label: string;
  writeback_enabled: boolean;
  etag?: string | null;
};

export type UniqueThreadIntentResponse = {
  status: string;
  candidates_checked: number;
  duplicates_found: number;
  provider_write_executed: boolean;
  provenance: string;
  audit_event: string;
  thread_updates: Array<{
    candidate_key: string;
    canonical_thread_id: string;
    dedupe_key: string;
    match_reason: 'message_id' | 'fingerprint';
    existing_message_id: string;
  }>;
};

export type UniqueThreadStatus = 'idle' | 'loading' | 'success' | 'auth' | 'error';
export type EmailImportStatus = 'idle' | 'loading' | 'success' | 'auth' | 'error';
export type DocumentActionStatus = 'idle' | 'loading' | 'success' | 'auth' | 'error';

export type DataSurfaceStatus = 'loading' | 'ready' | 'error';

export type SurfaceStatusCode = 'ready' | 'running' | 'needs_attention' | 'pending' | 'no_source';
export type QualityStatusCode = 'pass' | 'needs_attention' | 'pending';
export type RepositoryAssetState = 'ready' | 'needs_attention';

export type DataQualitySurfaceResponse = {
  workspace_id: string;
  organization_id: string | null;
  audit_event: string;
  provider_write_executed: boolean;
  repositories: Array<{
    source_id: string;
    repository_type: 'webdav_account' | 'project_folder' | 'email_repository' | 'attachment_repository' | 'document_repository';
    display_name: string;
    object_count: number;
    writeback_enabled: boolean | null;
    evidence_source: string;
    provider_write_executed: boolean;
  }>;
  repository_assets: Array<{
    asset_key: string;
    asset_type: 'email_attachment' | 'workspace_document';
    display_name: string;
    source_label: string;
    state_code: RepositoryAssetState;
    detail_text: string;
    content_chars: number;
    captured_at: string;
    evidence_source: string;
    thread_key: string;
    provider_write_executed: boolean;
  }>;
  pipeline_stages: Array<{
    stage_key: string;
    display_name: string;
    status_code: SurfaceStatusCode;
    progress_percent: number;
    evidence_source: string;
    detail_text: string;
    provider_write_executed: boolean;
  }>;
  embedding_collections: Array<{
    collection_key: string;
    display_name: string;
    object_count: number;
    embedded_count: number;
    embedding_model: string;
    vector_dimensions: number;
    status_code: SurfaceStatusCode;
    evidence_source: string;
    provider_write_executed: boolean;
  }>;
  quality_checks: Array<{
    check_key: string;
    display_name: string;
    status_code: QualityStatusCode;
    issue_count: number;
    total_count: number;
    evidence_source: string;
    detail_text: string;
    provider_write_executed: boolean;
  }>;
  connector_events: Array<{
    event_uid: string;
    signal_key: string;
    state_code: string;
    detail_text: string | null;
    observed_at: string;
  }>;
};

export type EmailFileImportResponse = {
  status: 'completed';
  imported_count: number;
  skipped_count: number;
  failed_count: number;
  attachment_count: number;
  provider_write_executed: boolean;
  provenance: 'server-authoritative';
  audit_event: 'email.file_import.completed';
  items: Array<{
    filename: string;
    status: 'imported' | 'skipped_duplicate' | 'failed';
    reason_code?: string | null;
    attachment_count: number;
  }>;
};

export type DataDocumentActionResponse = {
  document_id: string;
  workspace_id: string;
  document_name: string;
  document_type: string;
  document_status: string;
  content_chars: number;
  provider_write_executed: boolean;
  provenance: 'server-authoritative';
  audit_event: string;
  message: string;
};

export const duplicateImportCandidates = [
  {
    candidate_key: 'zip-q2-root',
    message_id: 'q2-root@example.com',
    sender: 'partner@example.com',
    recipients: 'user@naruon.net',
    subject: 'Q2 출시 계획',
    date: '2026-05-27T09:30:00Z',
    body: 'Forwarded launch plan body',
  },
  {
    candidate_key: 'forwarded-copy',
    sender: 'partner@example.com',
    recipients: 'user@naruon.net',
    subject: 'Q2 출시 계획',
    date: '2026-05-27T09:30:00Z',
    body: 'Forwarded launch plan body',
  },
];
