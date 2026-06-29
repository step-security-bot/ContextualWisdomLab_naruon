import { SurfaceStatusCode, QualityStatusCode, WebdavAccount, WebdavWritebackIntentResponse, DataQualitySurfaceResponse } from './types';

export function getApiErrorStatus(error: unknown) {
  const shapedError = error as { status?: unknown; response?: { status?: unknown } } | null;
  if (typeof shapedError?.status === 'number') return shapedError.status;
  if (typeof shapedError?.response?.status === 'number') return shapedError.response.status;
  return null;
}

export function getSafeErrorSummary(error: unknown) {
  const status = getApiErrorStatus(error);
  const errorName = error instanceof Error ? error.name : typeof error;
  return { status, error_name: errorName.slice(0, 40) };
}

export function formatCount(value: number) {
  return new Intl.NumberFormat('ko-KR').format(value);
}

export function formatDataTimestamp(value: string | null | undefined) {
  if (!value) return '기록 없음';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '기록 없음';
  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(parsed);
}

export function getSurfaceStatusLabel(status: SurfaceStatusCode | QualityStatusCode) {
  switch (status) {
    case 'ready':
    case 'pass':
      return '정상';
    case 'running':
      return '진행 중';
    case 'needs_attention':
      return '점검 필요';
    case 'pending':
      return '대기';
    case 'no_source':
      return '원본 없음';
    default:
      return '대기';
  }
}

export function getWriteBoundaryLabel(providerWriteExecuted: boolean) {
  return providerWriteExecuted ? '외부 쓰기 실행됨' : '의도만 기록';
}

export function getAssetEvidenceLabel(asset: DataQualitySurfaceResponse['repository_assets'][number]) {
  if (asset.asset_type === 'workspace_document') return '워크스페이스 문서 근거';
  if (asset.content_chars === 0) return '본문 추출 대기';
  return '원본 메일/스레드 근거 연결';
}

export function getDocumentTypeForFile(file: File) {
  const filename = file.name.toLowerCase();
  if (filename.endsWith('.md') || filename.endsWith('.markdown')) return 'text/markdown';
  if (filename.endsWith('.hwp')) return 'application/x-hwp';
  return file.type || 'text/plain';
}

export function isTextDocumentUploadType(documentType: string) {
  return documentType.startsWith('text/');
}

export function getSourceReadinessLabel(account: { writeback_enabled: boolean; etag?: string | null }) {
  if (!account.writeback_enabled) return '읽기 전용';
  return account.etag ? '쓰기 가능 · 충돌 검사용 ETag 준비' : '쓰기 가능 · ETag 확인 필요';
}

export function getWebdavAccountLabel(account: WebdavAccount, index: number) {
  const label = account.display_label.trim();
  if (!label || label.includes(account.source_id) || /^WebDAV source/i.test(label)) {
    return `WebDAV 저장소 ${index + 1}`;
  }
  return label;
}

export function getWritebackTargetLabel(result: WebdavWritebackIntentResponse, accounts: WebdavAccount[]) {
  const accountIndex = result.source_id ? accounts.findIndex((account) => account.source_id === result.source_id) : -1;
  if (accountIndex >= 0) {
    return getWebdavAccountLabel(accounts[accountIndex], accountIndex);
  }

  const label = result.target_label?.trim();
  if (!label || (result.source_id && label.includes(result.source_id)) || /^WebDAV source/i.test(label)) {
    return '선택된 원본';
  }
  return label;
}

export function getSurfaceStatusClass(status: SurfaceStatusCode | QualityStatusCode) {
  switch (status) {
    case 'ready':
    case 'pass':
      return 'bg-emerald-100 text-emerald-700';
    case 'running':
      return 'bg-blue-100 text-blue-700';
    case 'needs_attention':
      return 'bg-amber-100 text-amber-800';
    case 'no_source':
      return 'bg-slate-100 text-slate-700';
    case 'pending':
    default:
      return 'bg-secondary text-muted-foreground';
  }
}
