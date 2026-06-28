"use client";

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import Link from 'next/link';
import {
  Activity,
  Bot,
  FileCode2,
  GitBranch,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';

import { apiClient } from '@/lib/api-client';

type SurfaceStatus = 'loading' | 'ready' | 'error';
type TabId = 'prompts' | 'workflows' | 'agents' | 'evaluation' | 'runs';

type SummaryCard = {
  summary_key: string;
  label_text: string;
  value_text: string;
  detail_text: string;
  state_code: string;
};

type PromptCard = {
  prompt_key: string;
  prompt_title: string;
  description_text: string | null;
  shared_scope: boolean;
  owner_label: string;
  updated_at: string | null;
};

type WorkflowCard = {
  workflow_key: string;
  workflow_title: string;
  trigger_source: string;
  state_code: string;
  evidence_text: string;
};

type AgentCard = {
  agent_key: string;
  agent_title: string;
  model_label: string;
  state_code: string;
  configured: boolean;
  governance_text: string;
};

type EvaluationMetric = {
  metric_key: string;
  metric_label: string;
  score_value: number;
  trend_text: string;
};

type RunEvent = {
  event_key: string;
  event_title: string;
  state_code: string;
  evidence_source: string;
  observed_at: string | null;
  detail_text: string | null;
};

type AiHubSurfaceResponse = {
  summary_cards: SummaryCard[];
  prompt_cards: PromptCard[];
  workflow_cards: WorkflowCard[];
  agent_cards: AgentCard[];
  evaluation_metrics: EvaluationMetric[];
  run_events: RunEvent[];
};

const tabs = [
  { id: 'prompts', label: '프롬프트 스튜디오', icon: FileCode2 },
  { id: 'workflows', label: '워크플로우', icon: GitBranch },
  { id: 'agents', label: '판단 보조', icon: Bot },
  { id: 'evaluation', label: '평가', icon: ShieldCheck },
  { id: 'runs', label: '실행 이력', icon: Activity },
] as const;

function getSafeErrorSummary(error: unknown) {
  if (error instanceof Error) return error.message;
  return 'unknown error';
}

function formatDateTime(value: string | null) {
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

function stateLabel(stateCode: string) {
  const labels: Record<string, string> = {
    active: '활성',
    attention: '점검',
    completed: '완료',
    configured: '구성됨',
    draft: '초안',
    empty: '없음',
    failed: '실패',
    needs_key: '키 필요',
    needs_provider: '모델 연결 필요',
    pending: '대기',
    ready: '준비됨',
    recorded: '기록됨',
    running: '실행 중',
  };
  return labels[stateCode] ?? stateCode;
}

function stateClassName(stateCode: string) {
  if (stateCode === 'active' || stateCode === 'ready' || stateCode === 'recorded' || stateCode === 'completed') {
    return 'border-green-200 bg-green-50 text-green-700';
  }
  if (stateCode === 'failed') {
    return 'border-red-200 bg-red-50 text-red-700';
  }
  if (stateCode === 'attention' || stateCode.startsWith('needs_')) {
    return 'border-amber-200 bg-amber-50 text-amber-700';
  }
  return 'border-border bg-secondary text-muted-foreground';
}

function StatusBadge({ stateCode }: { stateCode: string }) {
  return (
    <span className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[11px] font-bold ${stateClassName(stateCode)}`}>
      {stateLabel(stateCode)}
    </span>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-card p-8 text-center">
      <p className="font-bold text-foreground">{title}</p>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{detail}</p>
    </div>
  );
}

function getKoreanFirstLabel(label: string) {
  return label
    .replace(/\bProvider\b/gi, '연동')
    .replace(/\bCredential\b/gi, '인증 정보')
    .replace(/\bsource evidence\b/gi, '원본 근거');
}

function SummaryGrid({ cards }: { cards: SummaryCard[] }) {
  return (
    <section aria-label="AI 허브 원본 기반 종합" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      {cards.map((card) => (
        <article key={card.summary_key} className="rounded-lg border border-border bg-card p-4 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm font-bold text-muted-foreground">{getKoreanFirstLabel(card.label_text)}</p>
            <StatusBadge stateCode={card.state_code} />
          </div>
          <p className="mt-4 text-3xl font-black text-foreground">{card.value_text}</p>
          <p className="mt-1 text-xs font-semibold text-muted-foreground">{card.detail_text}</p>
        </article>
      ))}
    </section>
  );
}

function PromptPanel({ prompts }: { prompts: PromptCard[] }) {
  if (prompts.length === 0) {
    return <EmptyState title="등록된 프롬프트가 없습니다." detail="프롬프트 스튜디오에서 저장된 템플릿이 생기면 이 화면에 연결됩니다." />;
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {prompts.map((prompt) => (
        <article key={prompt.prompt_key} className="rounded-lg border border-border bg-card p-5 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="truncate text-base font-black">{prompt.prompt_title}</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{prompt.description_text ?? '프롬프트 설명이 등록되지 않았습니다.'}</p>
            </div>
            <StatusBadge stateCode={prompt.shared_scope ? 'ready' : 'configured'} />
          </div>
          <dl className="mt-5 grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="font-bold text-muted-foreground">소유자</dt>
              <dd className="mt-1 font-semibold">{prompt.owner_label}</dd>
            </div>
            <div>
              <dt className="font-bold text-muted-foreground">업데이트</dt>
              <dd className="mt-1 font-semibold">{formatDateTime(prompt.updated_at)}</dd>
            </div>
          </dl>
          <div className="mt-5 flex flex-wrap justify-end gap-2 border-t border-border pt-4">
            <Link
              href="/prompt-studio"
              className="inline-flex h-9 items-center rounded-lg border border-border bg-background px-3 text-xs font-black text-foreground hover:border-primary/30 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            >
              프롬프트 열기
            </Link>
            <Link
              href="/ai-hub#actions"
              className="inline-flex h-9 items-center rounded-lg bg-primary px-3 text-xs font-black text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            >
              실행 항목 보기
            </Link>
          </div>
        </article>
      ))}
    </div>
  );
}

function WorkflowPanel({ workflows, onOpenRuns }: { workflows: WorkflowCard[]; onOpenRuns: () => void }) {
  if (workflows.length === 0) {
    return <EmptyState title="실행 흐름으로 만들 프롬프트가 없습니다." detail="저장된 프롬프트와 활성 모델 연결이 준비되면 실행 후보가 생성됩니다." />;
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {workflows.map((workflow) => (
        <article key={workflow.workflow_key} className="rounded-lg border border-border bg-card p-5 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <h2 className="text-base font-black">{workflow.workflow_title}</h2>
            <StatusBadge stateCode={workflow.state_code} />
          </div>
          <p className="mt-4 text-sm font-bold text-primary">{workflow.trigger_source}</p>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">{workflow.evidence_text}</p>
          <div className="mt-5 flex justify-end border-t border-border pt-4">
            <button
              type="button"
              onClick={onOpenRuns}
              className="inline-flex h-9 items-center rounded-lg border border-border bg-background px-3 text-xs font-black text-foreground hover:border-primary/30 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            >
              실행 이력 보기
            </button>
          </div>
        </article>
      ))}
    </div>
  );
}

function AgentsPanel({ agents }: { agents: AgentCard[] }) {
  if (agents.length === 0) {
    return <EmptyState title="조직 모델 연결이 없습니다." detail="설정의 LLM 모델 연결이 구성되면 판단 보조 실행 후보로 표시됩니다." />;
  }
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {agents.map((agent) => (
        <article key={agent.agent_key} className="rounded-lg border border-border bg-card p-5 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <h2 className="text-base font-black">{agent.agent_title}</h2>
            <StatusBadge stateCode={agent.state_code} />
          </div>
          <dl className="mt-5 space-y-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <dt className="font-bold text-muted-foreground">모델</dt>
              <dd className="font-semibold">{agent.model_label}</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="font-bold text-muted-foreground">연결 상태</dt>
              <dd className="font-semibold">{agent.configured ? '연결됨' : '연결 필요'}</dd>
            </div>
          </dl>
          <p className="mt-4 text-xs leading-5 text-muted-foreground">{agent.governance_text}</p>
          <div className="mt-5 flex justify-end border-t border-border pt-4">
            <Link
              href="/settings"
              className="inline-flex h-9 items-center rounded-lg border border-border bg-background px-3 text-xs font-black text-foreground hover:border-primary/30 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            >
              모델 설정 열기
            </Link>
          </div>
        </article>
      ))}
    </div>
  );
}

function EvaluationPanel({ metrics, onOpenRuns }: { metrics: EvaluationMetric[]; onOpenRuns: () => void }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {metrics.map((metric) => (
        <article key={metric.metric_key} className="rounded-lg border border-border bg-card p-5 shadow-sm">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-base font-black">{getKoreanFirstLabel(metric.metric_label)}</h2>
            <span className="text-2xl font-black text-primary">{metric.score_value}</span>
          </div>
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-secondary">
            <div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(0, Math.min(metric.score_value, 100))}%` }} />
          </div>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">{metric.trend_text}</p>
          <div className="mt-5 flex justify-end border-t border-border pt-4">
            <button
              type="button"
              onClick={onOpenRuns}
              className="inline-flex h-9 items-center rounded-lg border border-border bg-background px-3 text-xs font-black text-foreground hover:border-primary/30 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            >
              평가 근거 보기
            </button>
          </div>
        </article>
      ))}
    </div>
  );
}

function RunHistoryPanel({ events }: { events: RunEvent[] }) {
  if (events.length === 0) {
    return <EmptyState title="기록된 실행 증거가 없습니다." detail="에이전트 실행 row 또는 운영 감사 근거가 생기면 실행 근거로 정렬됩니다." />;
  }
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card shadow-sm">
      <div className="grid grid-cols-[minmax(0,1fr)_9rem_8rem] gap-4 border-b border-border px-4 py-3 text-xs font-black text-muted-foreground max-md:hidden">
        <span>이벤트</span>
        <span>증거</span>
        <span>시간</span>
      </div>
      <div className="divide-y divide-border">
        {events.map((event) => (
          <article key={event.event_key} className="grid gap-3 px-4 py-4 md:grid-cols-[minmax(0,1fr)_9rem_8rem] md:items-center">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-black">{event.event_title}</h2>
                <StatusBadge stateCode={event.state_code} />
              </div>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">{event.detail_text ?? '상세 증거 없음'}</p>
            </div>
            <p className="text-sm font-semibold text-primary">{event.evidence_source}</p>
            <p className="text-sm font-semibold text-muted-foreground">{formatDateTime(event.observed_at)}</p>
          </article>
        ))}
      </div>
    </div>
  );
}

function ExecutionCheckpointNav() {
  return (
    <nav aria-label="AI 허브 실행 체크포인트" className="flex gap-2 overflow-x-auto pb-1">
      {[
        { href: '#context', label: '맥락 종합' },
        { href: '#decisions', label: '판단 포인트' },
        { href: '#actions', label: '실행 항목' },
      ].map((item) => (
        <a
          key={item.href}
          href={item.href}
          className="inline-flex h-10 shrink-0 items-center rounded-lg border border-border bg-card px-3 text-sm font-black text-foreground shadow-sm hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
        >
          {item.label}
        </a>
      ))}
    </nav>
  );
}

function CheckpointSection({
  id,
  title,
  detail,
  children,
}: {
  id: string;
  title: string;
  detail: string;
  children: ReactNode;
}) {
  const titleId = `${id}-title`;
  return (
    <section
      id={id}
      aria-labelledby={titleId}
      className="scroll-mt-24 rounded-lg border border-border bg-card p-5 shadow-sm"
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-black text-primary">연결 근거</p>
          <h2 id={titleId} className="mt-1 text-xl font-black">
            {title}
          </h2>
        </div>
        <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{detail}</p>
      </div>
      <div className="mt-5">{children}</div>
    </section>
  );
}

function ContextCheckpoint({ prompts }: { prompts: PromptCard[] }) {
  if (prompts.length === 0) {
    return <EmptyState title="맥락 종합할 프롬프트가 없습니다." detail="프롬프트 스튜디오에 원본 근거 기반 템플릿이 저장되면 이 영역에 표시됩니다." />;
  }
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {prompts.slice(0, 4).map((prompt) => (
        <article key={prompt.prompt_key} className="rounded-lg border border-border bg-background p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="text-base font-black">{prompt.prompt_title}</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{prompt.description_text ?? '프롬프트 설명이 등록되지 않았습니다.'}</p>
            </div>
            <StatusBadge stateCode={prompt.shared_scope ? 'ready' : 'configured'} />
          </div>
          <dl className="mt-4 flex flex-wrap gap-3 text-xs font-bold text-muted-foreground">
            <div>
              <dt className="sr-only">소유자</dt>
              <dd>{prompt.owner_label}</dd>
            </div>
            <div>
              <dt className="sr-only">업데이트</dt>
              <dd>{formatDateTime(prompt.updated_at)}</dd>
            </div>
          </dl>
        </article>
      ))}
    </div>
  );
}

function DecisionCheckpoint({ metrics, agents }: { metrics: EvaluationMetric[]; agents: AgentCard[] }) {
  const visibleMetrics = metrics.slice(0, 4);
  if (visibleMetrics.length === 0 && agents.length === 0) {
    return <EmptyState title="판단 포인트 근거가 없습니다." detail="모델 연결, 프롬프트, 감사 근거가 연결되면 운영 판단 근거가 표시됩니다." />;
  }
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="grid gap-3 md:grid-cols-2">
        {visibleMetrics.map((metric) => (
          <article key={metric.metric_key} className="rounded-lg border border-border bg-background p-4">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-black">{getKoreanFirstLabel(metric.metric_label)}</h3>
              <span className="text-xl font-black text-primary">{metric.score_value}</span>
            </div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-secondary">
              <div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(0, Math.min(metric.score_value, 100))}%` }} />
            </div>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">{metric.trend_text}</p>
          </article>
        ))}
      </div>
      <aside className="rounded-lg border border-border bg-background p-4">
        <h3 className="text-sm font-black">모델 판단 보조</h3>
        {agents.length === 0 ? (
          <p className="mt-3 text-sm leading-6 text-muted-foreground">조직 모델 연결이 없으면 실행 판단은 대기 상태로 표시됩니다.</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {agents.slice(0, 3).map((agent) => (
              <li key={agent.agent_key} className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-black">{agent.agent_title}</p>
                  <p className="text-xs font-semibold text-muted-foreground">{agent.model_label}</p>
                </div>
                <StatusBadge stateCode={agent.state_code} />
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}

function ActionsCheckpoint({ workflows, events }: { workflows: WorkflowCard[]; events: RunEvent[] }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="grid gap-3 md:grid-cols-2">
        {workflows.length === 0 ? (
          <EmptyState title="실행 항목 후보가 없습니다." detail="저장된 프롬프트와 활성 모델 연결이 준비되면 실행 흐름 후보가 생성됩니다." />
        ) : (
          workflows.slice(0, 4).map((workflow) => (
            <article key={workflow.workflow_key} className="rounded-lg border border-border bg-background p-4">
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-sm font-black">{workflow.workflow_title}</h3>
                <StatusBadge stateCode={workflow.state_code} />
              </div>
              <p className="mt-3 text-sm font-bold text-primary">{workflow.trigger_source}</p>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{workflow.evidence_text}</p>
            </article>
          ))
        )}
      </div>
      <aside className="rounded-lg border border-border bg-background p-4">
        <h3 className="text-sm font-black">최근 실행 근거</h3>
        {events.length === 0 ? (
          <p className="mt-3 text-sm leading-6 text-muted-foreground">기록된 실행 근거가 없습니다.</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {events.slice(0, 3).map((event) => (
              <li key={event.event_key} className="text-sm">
                <p className="font-black">{event.event_title}</p>
                <p className="mt-1 font-semibold text-primary">{event.evidence_source}</p>
                <p className="mt-1 text-xs text-muted-foreground">{formatDateTime(event.observed_at)}</p>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}

export function AIHubLayout() {
  const [activeTab, setActiveTab] = useState<TabId>('prompts');
  const [surfaceStatus, setSurfaceStatus] = useState<SurfaceStatus>('loading');
  const [surface, setSurface] = useState<AiHubSurfaceResponse | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);

  const requestRefresh = () => {
    setSurfaceStatus('loading');
    setErrorText(null);
    setRefreshNonce((value) => value + 1);
  };

  useEffect(() => {
    let cancelled = false;
    apiClient
      .get<AiHubSurfaceResponse>('/api/ai-hub/surface')
      .then((data) => {
        if (cancelled) return;
        setSurface(data);
        setSurfaceStatus('ready');
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        console.error('AI Hub surface fetch error', getSafeErrorSummary(error));
        setSurface(null);
        setErrorText('AI 허브 원본 근거를 불러오지 못했습니다.');
        setSurfaceStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [refreshNonce]);

  const activeTabLabel = useMemo(
    () => tabs.find((tab) => tab.id === activeTab)?.label ?? 'AI 허브',
    [activeTab],
  );

  return (
    <div className="flex h-full min-h-0 flex-col bg-background text-foreground">
      <header className="shrink-0 border-b border-border bg-card px-4 py-4 md:px-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="flex items-center gap-3 text-xl font-black md:text-2xl">
            <Sparkles className="size-6 text-primary" aria-hidden="true" />
            AI 허브
          </h1>
          <button
            type="button"
            onClick={requestRefresh}
            disabled={surfaceStatus === 'loading'}
            aria-busy={surfaceStatus === 'loading'}
            className="inline-flex h-10 items-center gap-2 rounded-lg border border-border bg-background px-3 text-sm font-bold hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RefreshCw className={`size-4 ${surfaceStatus === 'loading' ? 'animate-spin' : ''}`} aria-hidden="true" />
            {surfaceStatus === 'loading' ? '새로고침 중' : '새로고침'}
          </button>
        </div>
        <nav aria-label="AI 허브 섹션" className="mt-4 flex gap-2 overflow-x-auto pb-1">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`inline-flex h-10 shrink-0 items-center gap-2 rounded-lg px-3 text-sm font-bold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 ${
                activeTab === tab.id
                  ? 'bg-primary text-primary-foreground'
                  : 'border border-border bg-background text-muted-foreground hover:bg-secondary'
              }`}
            >
              <tab.icon className="size-4" aria-hidden="true" />
              {tab.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden bg-background p-4 pb-[calc(6rem+env(safe-area-inset-bottom))] md:p-8">
        <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
          {surfaceStatus === 'loading' && (
            <div role="status" aria-live="polite" className="rounded-lg border border-border bg-card p-6 font-bold text-primary">
              AI 허브 원본 근거를 불러오는 중입니다.
            </div>
          )}

          {surfaceStatus === 'error' && (
            <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-6 text-red-700">
              <p className="font-black">{errorText}</p>
              <button
                type="button"
                onClick={requestRefresh}
                className="mt-4 rounded-lg bg-red-600 px-4 py-2 text-sm font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-600/40 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                다시 시도
              </button>
            </div>
          )}

          {surfaceStatus === 'ready' && surface && (
            <>
              <SummaryGrid cards={surface.summary_cards} />
              <ExecutionCheckpointNav />
              <CheckpointSection
                id="context"
                title="맥락 종합"
                detail="저장된 프롬프트와 원본 근거 기반 설명을 함께 묶어 현재 판단에 필요한 핵심 맥락을 보여줍니다."
              >
                <ContextCheckpoint prompts={surface.prompt_cards} />
              </CheckpointSection>
              <CheckpointSection
                id="decisions"
                title="판단 포인트"
                detail="모델 연결 준비도, 프롬프트 커버리지, 감사 근거를 기준으로 실행 전 확인할 운영 판단 근거를 정리합니다."
              >
                <DecisionCheckpoint metrics={surface.evaluation_metrics} agents={surface.agent_cards} />
              </CheckpointSection>
              <CheckpointSection
                id="actions"
                title="실행 항목"
                detail="프롬프트에서 파생된 실행 흐름과 최근 실행 근거를 연결하되 외부 제공자 쓰기는 직접 수행하지 않습니다."
              >
                <ActionsCheckpoint workflows={surface.workflow_cards} events={surface.run_events} />
              </CheckpointSection>
              <section aria-label={activeTabLabel} className="min-h-[24rem]">
                {activeTab === 'prompts' && <PromptPanel prompts={surface.prompt_cards} />}
                {activeTab === 'workflows' && <WorkflowPanel workflows={surface.workflow_cards} onOpenRuns={() => setActiveTab('runs')} />}
                {activeTab === 'agents' && <AgentsPanel agents={surface.agent_cards} />}
                {activeTab === 'evaluation' && <EvaluationPanel metrics={surface.evaluation_metrics} onOpenRuns={() => setActiveTab('runs')} />}
                {activeTab === 'runs' && <RunHistoryPanel events={surface.run_events} />}
              </section>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
