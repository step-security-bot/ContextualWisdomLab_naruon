"use client";

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, Settings, Plus, Users, Video, Paperclip, Clock, CalendarDays, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { apiClient } from '@/lib/api-client';

type CalendarWritebackIntentResponse = {
  workspace_id: string;
  target_source_id: string;
  protocol: string;
  writeback_mode: 'customer_owned';
  requires_if_match: boolean;
  if_match: string | null;
  provenance: Record<string, string>;
  audit_event: string;
  provider_write_executed: boolean;
  status: string;
  runner_request_id: string | null;
  provider_status: number | null;
  error_code: string | null;
  retry_item_uid?: string | null;
};

type CalendarWritebackSource = {
  source_id: string;
  provider: string;
  protocol: 'caldav' | 'carddav' | 'webdav' | 'local';
  owner_id: string;
  organization_id: string | null;
  capabilities: string[];
  writeback_enabled: boolean;
  etag: string | null;
};

type WritebackStatus = 'idle' | 'loading' | 'success' | 'no_source' | 'conflict' | 'auth' | 'error';

const calendarDefinitions = [
  { id: 'personal', name: '김나루 (나)', colorClass: 'bg-primary' },
  { id: 'pm-team', name: 'Naruon PM 팀', colorClass: 'bg-red-500' },
  { id: 'product-team', name: '제품 개발팀', colorClass: 'bg-green-500' },
  { id: 'marketing', name: '마케팅팀', colorClass: 'bg-purple-500' },
  { id: 'company', name: '회사 공용', colorClass: 'bg-indigo-500' },
  { id: 'holiday', name: '공휴일', colorClass: 'bg-slate-400' },
];

const calendarMonthEvents = [
  {
    id: 'product-review',
    calendarId: 'product-team',
    dayIndex: 15,
    time: '10:00',
    title: '제품 리뷰',
    source: '제품 개발팀',
    description: '제품 개발팀 일정 원본의 리뷰 일정입니다.',
    monthClassName: 'bg-green-100 text-green-700',
    dotClassName: 'bg-green-500',
    badgeClassName: 'bg-green-100 text-green-700',
    badgeLabel: '팀 일정',
    duration: '1시간',
    location: '회의실 B (3층)',
  },
  {
    id: 'launch-meeting',
    calendarId: 'pm-team',
    dayIndex: 22,
    time: '09:30',
    title: '출시 회의',
    source: 'Naruon PM 팀',
    description: 'Naruon 2.0 출시 준비 및 일정 공유',
    monthClassName: 'bg-orange-100 text-orange-700',
    dotClassName: 'bg-orange-500',
    badgeClassName: 'bg-orange-100 text-orange-700',
    badgeLabel: '중요',
    duration: '1시간 30분',
    location: '회의실 A (4층)',
  },
];

const calendarWeekEvents = [
  { id: 'week-product-review', calendarId: 'product-team', day: '월', title: '제품 리뷰', source: '제품 개발팀' },
  { id: 'week-partner-meeting', calendarId: 'personal', day: '화', title: '파트너 미팅 후보', source: '김나루 (나)' },
  { id: 'week-resource-review', calendarId: 'company', day: '수', title: '리소스 배정 검토', source: '회사 공용' },
  { id: 'week-launch-meeting', calendarId: 'pm-team', day: '목', title: '출시 회의', source: 'Naruon PM 팀' },
  { id: 'week-marketing-kickoff', calendarId: 'marketing', day: '금', title: '마케팅 캠페인 오프', source: '마케팅팀' },
];

const calendarCandidateEvents = [
  { id: 'candidate-partner', calendarId: 'personal', title: '파트너 미팅 일정 확정', source: '김나루 (나)', mode: '새 일정 반영 의도' },
  { id: 'candidate-launch', calendarId: 'pm-team', title: '출시 회의 시간 변경', source: 'Naruon PM 팀', mode: '충돌 검사 후 변경 의도' },
  { id: 'candidate-company', calendarId: 'company', title: '개인 메일에서 발견된 회사 일정', source: '회사 공용', mode: '원본 재지정 검토' },
];

function buildInitialCalendarVisibility() {
  return Object.fromEntries(calendarDefinitions.map((calendar) => [calendar.id, true]));
}

function isCustomerOwnedWritableSource(source: CalendarWritebackSource) {
  return source.writeback_enabled
    && source.protocol !== 'local'
    && source.capabilities.includes('write');
}

function getCalendarSourceLabel(index: number) {
  return `일정 원본 ${index + 1}`;
}

function getProtocolLabel(protocol: string) {
  switch (protocol) {
    case 'caldav':
      return 'CalDAV 원본';
    case 'carddav':
      return 'CardDAV 원본';
    case 'webdav':
      return 'WebDAV 원본';
    default:
      return '원본 계정';
  }
}

function getCapabilityLabel(capability: string) {
  switch (capability) {
    case 'read':
      return '읽기';
    case 'write':
      return '일정 반영';
    case 'etag':
      return '충돌 검사';
    default:
      return '원본 기능';
  }
}

function getEtagLabel(value: string | null) {
  return value ? '충돌 토큰 있음' : '충돌 토큰 대기';
}

function getIntentProtocolLabel(protocol: string) {
  return `${getProtocolLabel(protocol)} 선택됨`;
}

function getWritebackModeLabel(mode: CalendarWritebackIntentResponse['writeback_mode']) {
  return mode === 'customer_owned' ? '고객 원본 계정 반영' : '원본 계정 확인 필요';
}

function getProviderExecutionLabel(result: CalendarWritebackIntentResponse) {
  if (result.provider_write_executed) return '외부 원본 쓰기 완료';
  if (result.retry_item_uid || result.status === 'queued') return '커넥터 실행 요청 접수';
  if (result.error_code) return '커넥터 실행 실패';
  return '의도만 기록';
}

function getProviderRetryLabel(result: CalendarWritebackIntentResponse) {
  if (result.retry_item_uid || result.status === 'queued') return '재시도 대기';
  if (result.provider_write_executed) return '재시도 없음';
  return '실행 요청 없음';
}

function getApiErrorStatus(error: unknown) {
  const shapedError = error as { status?: unknown; response?: { status?: unknown } } | null;
  if (typeof shapedError?.status === 'number') return shapedError.status;
  if (typeof shapedError?.response?.status === 'number') return shapedError.response.status;
  return null;
}

export function CalendarLayout() {
  const [viewMode, setViewMode] = useState<'월간 캘린더' | '주간 캘린더' | '일정 상세' | '회의 조율' | '일정 후보'>('월간 캘린더');
  const [writebackStatus, setWritebackStatus] = useState<WritebackStatus>('idle');
  const [writebackResult, setWritebackResult] = useState<CalendarWritebackIntentResponse | null>(null);
  const [writebackSources, setWritebackSources] = useState<CalendarWritebackSource[]>([]);
  const [sourceLoadStatus, setSourceLoadStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [calendarVisibility, setCalendarVisibility] = useState<Record<string, boolean>>(() => buildInitialCalendarVisibility());

  const visibleCalendarIds = useMemo(() => {
    return new Set(
      calendarDefinitions
        .filter((calendar) => calendarVisibility[calendar.id] ?? false)
        .map((calendar) => calendar.id),
    );
  }, [calendarVisibility]);

  const visibleMonthEvents = useMemo(
    () => calendarMonthEvents.filter((event) => visibleCalendarIds.has(event.calendarId)),
    [visibleCalendarIds],
  );
  const visibleWeekEvents = useMemo(
    () => calendarWeekEvents.filter((event) => visibleCalendarIds.has(event.calendarId)),
    [visibleCalendarIds],
  );
  const visibleCandidateEvents = useMemo(
    () => calendarCandidateEvents.filter((event) => visibleCalendarIds.has(event.calendarId)),
    [visibleCalendarIds],
  );
  const selectedDetailEvent = visibleMonthEvents.find((event) => event.id === 'launch-meeting') ?? visibleMonthEvents[0] ?? null;

  const toggleCalendarVisibility = useCallback((calendarId: string) => {
    setCalendarVisibility((currentVisibility) => ({
      ...currentVisibility,
      [calendarId]: !(currentVisibility[calendarId] ?? false),
    }));
  }, []);

  useEffect(() => {
    let isMounted = true;
    void apiClient.get<CalendarWritebackSource[]>('/api/calendar/writeback-sources')
      .then((sources) => {
        if (!isMounted) return;
        setWritebackSources(sources);
        setSelectedSourceId(sources.find(isCustomerOwnedWritableSource)?.source_id ?? null);
        setSourceLoadStatus('ready');
      })
      .catch(() => {
        if (!isMounted) return;
        setWritebackSources([]);
        setSourceLoadStatus('error');
        setSelectedSourceId(null);
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const selectedWritebackSource = useMemo(() => {
    const selectedSource = writebackSources.find((source) => source.source_id === selectedSourceId);
    if (selectedSource && isCustomerOwnedWritableSource(selectedSource)) return selectedSource;
    return writebackSources.find(isCustomerOwnedWritableSource) ?? null;
  }, [selectedSourceId, writebackSources]);
  const isSourceRegistryReady = sourceLoadStatus === 'ready';

  const requestWritebackIntent = useCallback(async (action: 'create' | 'update', executeProvider = false) => {
    if (!isSourceRegistryReady) {
      setWritebackResult(null);
      setWritebackStatus(sourceLoadStatus === 'error' ? 'error' : 'loading');
      return;
    }
    if (selectedWritebackSource === null) {
      setWritebackResult(null);
      setWritebackStatus('no_source');
      return;
    }
    setWritebackStatus('loading');
    setWritebackResult(null);
    try {
      const result = await apiClient.post<CalendarWritebackIntentResponse>('/api/calendar/writeback-intent', {
        action,
        summary: action === 'create'
          ? 'Naruon 일정 후보 writeback intent 점검'
          : 'Naruon 기존 일정 ETag/If-Match 충돌 점검',
        ...(selectedWritebackSource ? { target_source_id: selectedWritebackSource.source_id } : {}),
        ...(executeProvider ? { execute_provider: true } : {}),
      });
      setWritebackResult(result);
      setWritebackStatus('success');
    } catch (error: unknown) {
      const status = getApiErrorStatus(error);
      if (status === 422) {
        setWritebackStatus('no_source');
      } else if (status === 409) {
        setWritebackStatus('conflict');
      } else if (status === 401 || status === 403) {
        setWritebackStatus('auth');
      } else {
        setWritebackStatus('error');
      }
    }
  }, [isSourceRegistryReady, selectedWritebackSource, sourceLoadStatus]);

  const isWritebackLoading = writebackStatus === 'loading';
  const isWritebackActionDisabled = isWritebackLoading || !isSourceRegistryReady;
  const isProviderExecutionDisabled = isWritebackActionDisabled || !selectedWritebackSource?.etag;

  return (
    <div className="flex h-full min-h-0 bg-background text-foreground">
      {/* Left Sidebar - Calendar List */}
      <aside className="w-64 shrink-0 flex-col overflow-y-auto border-r border-border bg-card p-4 hidden lg:flex">
        <Button type="button" className="h-10 w-full">
          <Plus className="size-4" aria-hidden="true" />새 일정
        </Button>

        <div className="mt-8">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-xs font-bold text-muted-foreground">캘린더 목록</h2>
          </div>
          <ul className="space-y-3">
            {calendarDefinitions.map((cal) => (
              <li key={cal.name} className="text-sm">
                <label className="flex cursor-pointer items-center gap-3 group">
                  <input
                    type="checkbox"
                    checked={calendarVisibility[cal.id] ?? false}
                    onChange={() => toggleCalendarVisibility(cal.id)}
                    className="size-4 cursor-pointer rounded border-border text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                    aria-label={`${cal.name} 캘린더 표시 토글`}
                  />
                  <span className={`size-3 rounded-full ${cal.colorClass}`} aria-hidden="true" />
                  <span className="font-medium text-foreground transition-colors group-hover:text-primary">{cal.name}</span>
                </label>
              </li>
            ))}
          </ul>
          <Button type="button" variant="ghost" className="mt-4 w-full justify-start text-primary hover:text-primary">
            <Plus className="size-4" aria-hidden="true" /> 캘린더 추가
          </Button>
        </div>
      </aside>

      {/* Main Calendar Area */}
      <main className="flex min-w-0 flex-1 flex-col bg-background">
        <header className="flex h-auto min-h-16 shrink-0 flex-col items-start gap-3 border-b border-border bg-card px-4 py-3 lg:px-6">
          <div className="flex min-w-0 flex-wrap items-center gap-3 lg:gap-4">
            <Button type="button" variant="outline" size="sm" className="h-8 rounded-md text-xs font-semibold">오늘</Button>
            <div className="flex items-center gap-1">
              <Button type="button" variant="ghost" size="icon-sm" aria-label="이전 달" className="rounded-md"><ChevronLeft className="size-5" aria-hidden="true" /></Button>
              <Button type="button" variant="ghost" size="icon-sm" aria-label="다음 달" className="rounded-md"><ChevronRight className="size-5" aria-hidden="true" /></Button>
            </div>
            <h1 className="text-xl font-bold">일정 관리</h1>
            <h2 className="text-sm font-bold text-muted-foreground lg:ml-2">2026년 5월</h2>
          </div>
          <div className="flex w-full min-w-0 items-center gap-3">
            <div className="flex min-w-0 overflow-x-auto rounded-md border border-border">
              {['월간 캘린더', '주간 캘린더', '일정 상세', '회의 조율', '일정 후보'].map((mode) => (
                <button type="button"
                  key={mode}
                  aria-pressed={viewMode === mode}
                  onClick={() => setViewMode(mode as '월간 캘린더' | '주간 캘린더' | '일정 상세' | '회의 조율' | '일정 후보')}
                  className={`shrink-0 px-4 py-1.5 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:ring-offset-1 focus-visible:ring-offset-background ${viewMode === mode ? 'bg-primary text-primary-foreground' : 'bg-background hover:bg-secondary'}`}
                >
                  {mode}
                </button>
              ))}
            </div>
            <Button type="button" variant="outline" size="icon-sm" className="size-9 rounded-md" aria-label="설정">
              <Settings className="size-5" aria-hidden="true" />
            </Button>
          </div>
        </header>

        <div className="flex-1 space-y-5 overflow-y-auto p-4 pb-[calc(7rem+env(safe-area-inset-bottom))] md:p-6 lg:pb-6">
          <p className="sr-only">원본 계정 일정 반영 흐름</p>
          <section aria-label="일정 반영 의도 점검" className="rounded-2xl border border-border bg-card p-4 shadow-sm md:p-5">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
              <div className="min-w-0">
                <p className="text-xs font-black text-primary">고객 원본 일정</p>
                <h2 className="mt-1 text-lg font-black text-foreground">고객 원본 일정 반영 의도</h2>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                  Naruon은 캘린더 서버가 아니라 고객 원본 계정에 반영할 의도를 기록합니다.
                  실제 외부 쓰기는 원본 기능, 출처 근거, 충돌 토큰, 감사 기록을 통과해야 합니다.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void requestWritebackIntent('create')}
                  disabled={isWritebackActionDisabled}
                  className="rounded-xl bg-primary px-4 py-2 text-sm font-bold text-primary-foreground hover:bg-primary/90 disabled:cursor-wait disabled:opacity-60"
                >
                  새 일정 intent 점검
                </button>
                <button
                  type="button"
                  onClick={() => void requestWritebackIntent('update')}
                  disabled={isWritebackActionDisabled}
                  className="rounded-xl border border-border bg-background px-4 py-2 text-sm font-bold hover:bg-secondary disabled:cursor-wait disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                >
                  ETag 업데이트 점검
                </button>
                <button
                  type="button"
                  onClick={() => void requestWritebackIntent('update', true)}
                  disabled={isProviderExecutionDisabled}
                  className="rounded-xl border border-primary/40 bg-primary/10 px-4 py-2 text-sm font-bold text-primary hover:bg-primary/15 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                >
                  ETag 실행 요청
                </button>
              </div>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {writebackSources.map((source, index) => {
                const sourceWritable = isCustomerOwnedWritableSource(source);
                const sourceSelected = selectedWritebackSource?.source_id === source.source_id;
                const sourceLabel = getCalendarSourceLabel(index);
                return (
                  <button
                    key={source.source_id}
                    type="button"
                    aria-label={`${sourceLabel} ${sourceWritable ? '일정 반영 가능' : '읽기 전용'} 선택`}
                    disabled={!sourceWritable}
                    aria-pressed={sourceSelected}
                    onClick={() => setSelectedSourceId(source.source_id)}
                    className={`rounded-xl border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-70 ${
                      sourceSelected
                        ? 'border-primary bg-primary/10 shadow-sm'
                        : 'border-border bg-background/70 hover:border-primary/40'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-xs font-bold text-primary">{sourceLabel}</p>
                        <p className="mt-1 break-words text-sm font-bold">{getProtocolLabel(source.protocol)}</p>
                      </div>
                      <span className={`rounded-full px-2 py-1 text-xs font-black ${sourceWritable ? 'bg-green-100 text-green-700' : 'bg-secondary text-muted-foreground'}`}>
                        {sourceSelected ? '선택됨' : sourceWritable ? '반영 가능' : '읽기 전용'}
                      </span>
                    </div>
                    <p className="mt-2 text-xs font-semibold text-muted-foreground">
                      {source.capabilities.map(getCapabilityLabel).join(' · ')}
                    </p>
                    <p className="mt-2 text-xs font-semibold text-muted-foreground">
                      {getEtagLabel(source.etag)} · {sourceWritable ? '외부 쓰기 전 의도 점검 가능' : '외부 쓰기 차단'}
                    </p>
                  </button>
                );
              })}
              {sourceLoadStatus === 'ready' && writebackSources.length === 0 && (
                <p className="rounded-xl border border-border bg-background/70 p-3 text-sm font-bold text-amber-700">
                  연결된 CalDAV/CardDAV/WebDAV 원본이 없습니다.
                </p>
              )}
              {sourceLoadStatus === 'loading' && (
                <p className="rounded-xl border border-border bg-background/70 p-3 text-sm font-bold text-primary">
                  일정 원본 목록을 확인하는 중입니다.
                </p>
              )}
              {sourceLoadStatus === 'error' && (
                <p className="rounded-xl border border-border bg-background/70 p-3 text-sm font-bold text-amber-700">
                  서명 세션으로 일정 원본 목록을 확인할 수 없습니다.
                </p>
              )}
            </div>

            <div role="status" aria-live="polite" className="mt-4 rounded-xl border border-border bg-background/70 p-4 text-sm">
              {writebackStatus === 'idle' && (
                <p className="text-muted-foreground">아직 외부 일정 쓰기는 실행하지 않았습니다. 반영 의도 점검으로 원본 계정과 충돌 조건만 확인합니다.</p>
              )}
              {writebackStatus === 'loading' && <p className="font-bold text-primary">일정 반영 의도 요청 중입니다.</p>}
              {writebackStatus === 'no_source' && (
                <p className="font-bold text-amber-700">원본 CalDAV/CardDAV/WebDAV 계정이 없어 일정 반영 의도를 만들 수 없습니다.</p>
              )}
              {writebackStatus === 'conflict' && (
                <p className="font-bold text-red-700">ETag/If-Match 충돌이 감지되어 원본 일정을 덮어쓰지 않았습니다.</p>
              )}
              {writebackStatus === 'auth' && (
                <p className="font-bold text-red-700">서명 세션이 필요합니다. 공개 헤더로는 일정 반영 의도를 만들 수 없습니다.</p>
              )}
              {writebackStatus === 'error' && (
                <p className="font-bold text-red-700">일정 반영 의도 점검에 실패했습니다.</p>
              )}
              {writebackStatus === 'success' && writebackResult && (
                <dl className="grid gap-3 text-xs sm:grid-cols-2 2xl:grid-cols-3">
                  <div>
                    <dt className="font-black text-muted-foreground">반영 방식</dt>
                    <dd className="mt-1 text-sm font-bold text-foreground">{getWritebackModeLabel(writebackResult.writeback_mode)}</dd>
                  </div>
                  <div>
                    <dt className="font-black text-muted-foreground">원본 종류</dt>
                    <dd className="mt-1 text-sm font-bold text-foreground">{getIntentProtocolLabel(writebackResult.protocol)}</dd>
                  </div>
                  <div>
                    <dt className="font-black text-muted-foreground">대상 원본</dt>
                    <dd className="mt-1 text-sm font-bold text-foreground">선택한 일정 원본</dd>
                  </div>
                  <div>
                    <dt className="font-black text-muted-foreground">충돌 검사</dt>
                    <dd className="mt-1 text-sm font-bold text-foreground">{writebackResult.if_match ? 'If-Match 필요' : 'If-Match 생략 가능'}</dd>
                  </div>
                  <div>
                    <dt className="font-black text-muted-foreground">감사 근거</dt>
                    <dd className="mt-1 text-sm font-bold text-foreground">기록됨</dd>
                  </div>
                  <div>
                    <dt className="font-black text-muted-foreground">커넥터 실행</dt>
                    <dd className="mt-1 text-sm font-bold text-foreground">{getProviderExecutionLabel(writebackResult)}</dd>
                  </div>
                  <div>
                    <dt className="font-black text-muted-foreground">재시도 상태</dt>
                    <dd className="mt-1 text-sm font-bold text-foreground">{getProviderRetryLabel(writebackResult)}</dd>
                  </div>
                </dl>
              )}
            </div>
          </section>

          {viewMode === '월간 캘린더' && (
            <div className="h-full rounded-2xl border border-border bg-card shadow-sm flex flex-col overflow-hidden">
              <div className="grid grid-cols-7 border-b border-border bg-secondary/50 text-center text-sm font-semibold py-3">
                <div className="text-red-500">일</div><div>월</div><div>화</div><div>수</div><div>목</div><div>금</div><div className="text-blue-500">토</div>
              </div>
              <div className="grid grid-cols-7 grid-rows-5 flex-1 divide-x divide-y divide-border">
                {/* Simulated Grid Cells */}
                {Array.from({ length: 35 }).map((_, i) => {
                  const dayEvents = visibleMonthEvents.filter((event) => event.dayIndex === i);
                  return (
                    <div key={i} className="min-h-[84px] p-2 sm:min-h-[100px]">
                      <span className={`text-sm font-semibold ${i % 7 === 0 ? 'text-red-500' : i % 7 === 6 ? 'text-blue-500' : 'text-muted-foreground'}`}>{i < 31 ? i + 1 : ''}</span>
                      {dayEvents.map((event) => (
                        <div key={event.id} className={`mt-1 rounded px-1.5 py-1 text-[10px] font-semibold leading-tight sm:px-2 sm:text-xs ${event.monthClassName}`}>
                          {event.time}<span className="hidden sm:inline"> {event.title}</span>
                        </div>
                      ))}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {viewMode === '주간 캘린더' && (
            <section aria-label="주간 캘린더" className="rounded-2xl border border-border bg-card p-5 shadow-sm">
              <h3 className="text-lg font-bold">주간 캘린더</h3>
              <div className="mt-4 grid gap-3 md:grid-cols-5">
                {visibleWeekEvents.map((event) => (
                  <article key={event.id} className="rounded-xl border border-border bg-background p-4">
                    <p className="text-xs font-black text-primary">{event.day}</p>
                    <h4 className="mt-2 text-sm font-bold">{event.title}</h4>
                    <p className="mt-2 text-xs font-semibold text-muted-foreground">{event.source}</p>
                  </article>
                ))}
                {visibleWeekEvents.length === 0 && (
                  <p className="rounded-xl border border-border bg-background p-4 text-sm font-bold text-muted-foreground">
                    표시 중인 캘린더 일정이 없습니다.
                  </p>
                )}
              </div>
            </section>
          )}
          {viewMode === '일정 상세' && (
            <section aria-label="일정 상세" className="rounded-2xl border border-border bg-card p-5 shadow-sm">
              <h3 className="text-lg font-bold">{selectedDetailEvent ? `${selectedDetailEvent.title} 상세` : '일정 상세'}</h3>
              <dl className="mt-4 grid gap-4 md:grid-cols-2">
                <div className="rounded-xl border border-border bg-background p-4">
                  <dt className="text-xs font-black text-muted-foreground">원본 계정</dt>
                  <dd className="mt-2 text-sm font-bold">{selectedDetailEvent ? `${selectedDetailEvent.source} · 충돌 토큰 확인` : '표시 중인 원본 없음'}</dd>
                </div>
                <div className="rounded-xl border border-border bg-background p-4">
                  <dt className="text-xs font-black text-muted-foreground">충돌 제어</dt>
                  <dd className="mt-2 text-sm font-bold">ETag / If-Match 필요 시 server-authoritative 검증</dd>
                </div>
              </dl>
            </section>
          )}
          {viewMode === '회의 조율' && (
            <div className="flex h-full flex-col gap-4">
              <div className="rounded-2xl border border-border bg-card p-6 shadow-sm">
                <h3 className="text-lg font-bold mb-4">회의 조율</h3>
                <p className="text-sm text-muted-foreground mb-4">참석자들의 캘린더(CalDAV)를 종합 분석하여 최적의 시간을 제안합니다.</p>
                <div className="grid gap-3 max-w-lg">
                  <button type="button" className="flex items-center justify-between rounded-xl border border-primary/20 bg-primary/5 p-4 hover:bg-primary/10 transition-colors">
                    <div className="flex items-center gap-3">
                      <span className="grid size-8 place-items-center rounded-lg bg-primary/20 text-primary font-bold">1안</span>
                      <div className="text-left">
                        <p className="font-bold">5월 23일 (목) 14:00 - 15:00</p>
                        <p className="text-xs text-muted-foreground">모든 참석자 참석 가능</p>
                      </div>
                    </div>
                    <span className="text-xs font-bold text-primary">제안하기</span>
                  </button>
                  <button type="button" className="flex items-center justify-between rounded-xl border border-border bg-card p-4 hover:bg-secondary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40">
                    <div className="flex items-center gap-3">
                      <span className="grid size-8 place-items-center rounded-lg bg-secondary text-muted-foreground font-bold">2안</span>
                      <div className="text-left">
                        <p className="font-bold">5월 24일 (금) 10:00 - 11:00</p>
                        <p className="text-xs text-muted-foreground">1명(김개발) 불참 예상</p>
                      </div>
                    </div>
                    <span className="text-xs font-bold text-muted-foreground">제안하기</span>
                  </button>
                </div>
              </div>
            </div>
          )}
          {viewMode === '일정 후보' && (
            <section aria-label="일정 후보" className="rounded-2xl border border-border bg-card p-5 shadow-sm">
              <h3 className="text-lg font-bold">일정 후보</h3>
              <div className="mt-4 grid gap-3 lg:grid-cols-3">
                {visibleCandidateEvents.map((event) => (
                  <article key={event.id} className="rounded-xl border border-border bg-background p-4">
                    <h4 className="text-sm font-bold">{event.title}</h4>
                    <p className="mt-2 text-xs text-muted-foreground">{event.source}</p>
                    <p className="mt-3 rounded-full bg-primary/10 px-3 py-1 text-xs font-bold text-primary">{event.mode}</p>
                  </article>
                ))}
                {visibleCandidateEvents.length === 0 && (
                  <p className="rounded-xl border border-border bg-background p-4 text-sm font-bold text-muted-foreground">
                    표시 중인 캘린더 후보가 없습니다.
                  </p>
                )}
              </div>
            </section>
          )}
        </div>
      </main>

      {/* Right Sidebar - Event Detail */}
      <aside className="w-[340px] shrink-0 flex-col overflow-y-auto border-l border-border bg-card p-5 hidden xl:flex">
        <div className="flex items-center justify-between">
          <div className="flex gap-2">
            <span className={`rounded-md px-2 py-1 text-xs font-bold ${selectedDetailEvent?.badgeClassName ?? 'bg-secondary text-muted-foreground'}`}>
              {selectedDetailEvent ? `★ ${selectedDetailEvent.badgeLabel}` : '선택 없음'}
            </span>
            <span className="rounded-md bg-secondary px-2 py-1 text-xs font-bold text-muted-foreground">공개</span>
          </div>
          <div className="flex items-center gap-2">
            <Button type="button" variant="ghost" size="icon-sm" aria-label="닫기" className="rounded-md"><X className="size-4" aria-hidden="true" /></Button>
          </div>
        </div>

        <div className="mt-6">
          <div className="flex items-center gap-3">
            <div className={`size-4 rounded-full ${selectedDetailEvent?.dotClassName ?? 'bg-muted'}`}></div>
            <h2 className="text-xl font-bold">{selectedDetailEvent ? `${selectedDetailEvent.title} (Naruon 2.0)` : '표시 중인 일정 없음'}</h2>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">{selectedDetailEvent?.description ?? '왼쪽 캘린더 목록에서 하나 이상의 캘린더를 표시하세요.'}</p>
        </div>

        <div className="mt-6 space-y-5">
          <div className="flex gap-3">
            <Clock className="size-5 text-muted-foreground shrink-0" />
            <div>
              <p className="text-sm font-semibold">2026.05.23 (목) {selectedDetailEvent?.time ?? '--:--'} - 11:00</p>
              <p className="text-xs text-muted-foreground">{selectedDetailEvent?.duration ?? '일정 없음'}</p>
            </div>
          </div>
          <div className="flex gap-3 items-center">
            <Video className="size-5 text-muted-foreground shrink-0" />
            <p className="text-sm font-semibold">{selectedDetailEvent?.location ?? '장소 없음'}</p>
            <button type="button" aria-label={`${selectedDetailEvent?.location ?? '장소'} 위치 보기`} className="text-xs text-primary font-semibold ml-auto hover:underline rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40">위치 보기</button>
          </div>
          <div className="flex gap-3 items-start">
            <Users className="size-5 text-muted-foreground shrink-0" />
            <div>
              <p className="text-sm font-semibold mb-2">참석자 6명</p>
              <div className="flex -space-x-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="size-8 rounded-full border-2 border-card bg-slate-200"></div>
                ))}
                <div className="flex size-8 items-center justify-center rounded-full border-2 border-card bg-secondary text-xs font-bold">+2</div>
              </div>
            </div>
          </div>
          <div className="flex gap-3 items-start">
            <CalendarDays className="size-5 text-muted-foreground shrink-0" />
            <div>
              <p className="text-sm font-semibold mb-1">설명</p>
              <p className="text-sm text-muted-foreground">{selectedDetailEvent?.description ?? '표시할 일정 설명이 없습니다.'}</p>
            </div>
          </div>
          <div className="flex gap-3 items-start">
            <Paperclip className="size-5 text-muted-foreground shrink-0" />
            <div className="flex-1">
              <p className="text-sm font-semibold mb-2">첨부파일 <span className="text-muted-foreground font-normal">2개</span></p>
              <div className="space-y-2">
                <div className="flex items-center justify-between rounded-lg border border-border bg-background p-2">
                  <span className="text-xs font-semibold">Naruon_2.0_런칭계획.pptx</span>
                  <span className="text-xs text-muted-foreground">2.4 MB</span>
                </div>
                <div className="flex items-center justify-between rounded-lg border border-border bg-background p-2">
                  <span className="text-xs font-semibold">출시_체크리스트.xlsx</span>
                  <span className="text-xs text-muted-foreground">1.1 MB</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-8 flex gap-3">
          <button type="button" aria-label="출시 회의 일정 삭제" className="flex-1 rounded-lg border border-border bg-background py-2 text-sm font-bold shadow-sm hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40">삭제</button>
          <button type="button" aria-label="출시 회의 일정 복사" className="flex-1 rounded-lg border border-border bg-background py-2 text-sm font-bold shadow-sm hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40">복사</button>
          <button type="button" aria-label="출시 회의 일정 수정" className="flex-1 rounded-lg bg-primary py-2 text-sm font-bold text-primary-foreground shadow-sm hover:bg-primary/90">수정</button>
        </div>
      </aside>
    </div>
  );
}
