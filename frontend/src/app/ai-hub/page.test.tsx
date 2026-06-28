/* @vitest-environment jsdom */
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock('lucide-react', () => ({
  Activity: () => <svg aria-hidden="true" />,
  Bot: () => <svg aria-hidden="true" />,
  CheckCircle2: () => <svg aria-hidden="true" />,
  FileCode2: () => <svg aria-hidden="true" />,
  GitBranch: () => <svg aria-hidden="true" />,
  RefreshCw: () => <svg aria-hidden="true" />,
  ShieldCheck: () => <svg aria-hidden="true" />,
  Sparkles: () => <svg aria-hidden="true" />,
}));

import AIHubPage from './page';

const forbiddenIdentityHeaders = [
  'x-user-id',
  'x-organization-id',
  'x-group-id',
  'x-group-ids',
  'x-user-role',
  'x-dev-auth-token',
];

const aiHubSurface = {
  summary_cards: [
    {
      summary_key: 'prompt_templates',
      label_text: '프롬프트',
      value_text: '2',
      detail_text: '원본 근거 템플릿',
      state_code: 'ready',
    },
    {
      summary_key: 'ai_providers',
      label_text: '판단 보조',
      value_text: '1/1',
      detail_text: '활성 조직 모델 연결',
      state_code: 'ready',
    },
  ],
  prompt_cards: [
    {
      prompt_key: 'prompt_safe',
      prompt_title: '의사결정 로그 맥락 종합',
      description_text: '메일에서 판단 포인트를 추출합니다.',
      shared_scope: false,
      owner_label: 'alice',
      updated_at: '2026-05-29T09:30:00Z',
    },
  ],
  workflow_cards: [
    {
      workflow_key: 'workflow_prompt_safe',
      workflow_title: '의사결정 로그 자동 작성',
      trigger_source: 'workflow_definition',
      state_code: 'ready',
      evidence_text: '2 persisted workflow steps',
    },
  ],
  agent_cards: [
    {
      agent_key: 'agent_primary',
      agent_title: 'Primary OpenAI',
      model_label: 'openai',
      state_code: 'active',
      configured: true,
      governance_text: '조직 LLM 모델 연결 registry',
    },
  ],
  evaluation_metrics: [
    {
      metric_key: 'provider_readiness',
      metric_label: 'Provider 준비도',
      score_value: 100,
      trend_text: '활성 모델 연결 1/1',
    },
  ],
  run_events: [
    {
      event_key: 'agent_run_prompt_safe',
      event_title: '워크플로우 실행',
      state_code: 'completed',
      evidence_source: 'agent_run_records',
      observed_at: '2026-05-29T09:30:00Z',
      detail_text: '3개 판단 포인트를 추출했습니다.',
    },
  ],
};

function jsonResponse(body: unknown, ok = true) {
  return {
    ok,
    status: ok ? 200 : 500,
    statusText: ok ? 'OK' : 'Server Error',
    json: async () => body,
  } as Response;
}

async function flushAsyncWork() {
  await act(async () => {
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function clickButton(container: HTMLElement, label: string) {
  const button = Array.from(container.querySelectorAll('button')).find((node) =>
    node.textContent?.includes(label),
  );
  expect(button).not.toBeUndefined();
  act(() => {
    button?.click();
  });
}

describe('AIHubPage', () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(() => {
    if (root) {
      act(() => root?.unmount());
    }
    root = null;
    container?.remove();
    container = null;
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it('fetches the signed AI Hub surface and renders every operational tab', async () => {
    const fetchMock = vi.fn(async () => jsonResponse(aiHubSurface));
    vi.stubGlobal('fetch', fetchMock);
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<AIHubPage />);
    });
    await flushAsyncWork();

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/ai-hub/surface',
      expect.objectContaining({
        credentials: 'same-origin',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
        }),
      }),
    );
    const firstFetchCall = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const sentHeaders = firstFetchCall[1]?.headers;
    const headerNames =
      sentHeaders && !Array.isArray(sentHeaders) && !(sentHeaders instanceof Headers)
        ? Object.keys(sentHeaders)
        : [];
    const lowerHeaderNames = new Set(headerNames.map((name) => name.toLowerCase()));
    expect(lowerHeaderNames.has('authorization')).toBe(false);
    for (const headerName of forbiddenIdentityHeaders) {
      expect(lowerHeaderNames.has(headerName)).toBe(false);
    }
    expect(container.textContent).toContain('AI 허브');
    expect(container.textContent).toContain('의사결정 로그 맥락 종합');
    expect(container.textContent).toContain('프롬프트 열기');
    expect(container.textContent).toContain('실행 항목 보기');
    expect(container.querySelector('nav[aria-label="AI 허브 실행 체크포인트"]')?.textContent).toContain('맥락 종합');
    expect(container.querySelector('section[aria-labelledby="context-title"]')?.textContent).toContain('맥락 종합');
    expect(container.querySelector('section[aria-labelledby="decisions-title"]')?.textContent).toContain('판단 포인트');
    expect(container.querySelector('section[aria-labelledby="actions-title"]')?.textContent).toContain('실행 항목');
    expect(container.textContent).not.toContain('설명 없음');

    clickButton(container, '워크플로우');
    expect(container.textContent).toContain('의사결정 로그 자동 작성');
    expect(container.textContent).toContain('workflow_definition');
    expect(container.textContent).toContain('실행 이력 보기');
    clickButton(container, '실행 이력 보기');
    expect(container.textContent).toContain('워크플로우 실행');

    clickButton(container, '판단 보조');
    expect(container.textContent).toContain('Primary OpenAI');
    expect(container.textContent).toContain('연결 상태');
    expect(container.textContent).toContain('연결됨');
    expect(container.textContent).toContain('모델 설정 열기');

    clickButton(container, '평가');
    expect(container.textContent).toContain('연동 준비도');
    expect(container.textContent).not.toContain('Provider 준비도');
    expect(container.textContent).toContain('활성 모델 연결 1/1');
    expect(container.textContent).toContain('평가 근거 보기');
    clickButton(container, '평가 근거 보기');
    expect(container.textContent).toContain('워크플로우 실행');

    clickButton(container, '실행 이력');
    expect(container.textContent).toContain('agent_run_records');
  });

  it('renders a loading state while the AI Hub surface is pending', async () => {
    let resolveFetch: (response: Response) => void = () => {};
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            resolveFetch = resolve;
          }),
      ),
    );
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    act(() => {
      root?.render(<AIHubPage />);
    });

    expect(container.textContent).toContain('AI 허브 원본 근거를 불러오는 중입니다.');

    await act(async () => {
      resolveFetch(jsonResponse(aiHubSurface));
    });
    await flushAsyncWork();
  });

  it('disables the refresh action while a reload is pending', async () => {
    const pendingFetches: Array<(response: Response) => void> = [];
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          pendingFetches.push(resolve);
        }),
    );
    vi.stubGlobal('fetch', fetchMock);
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    act(() => {
      root?.render(<AIHubPage />);
    });

    await act(async () => {
      pendingFetches.shift()?.(jsonResponse(aiHubSurface));
    });
    await flushAsyncWork();

    let refreshButton = Array.from(container.querySelectorAll('button')).find((node) =>
      node.textContent?.includes('새로고침'),
    ) as HTMLButtonElement | undefined;
    expect(refreshButton).not.toBeUndefined();
    expect(refreshButton?.disabled).toBe(false);
    expect(refreshButton?.getAttribute('aria-busy')).toBe('false');

    act(() => {
      refreshButton?.click();
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    refreshButton = Array.from(container.querySelectorAll('button')).find((node) =>
      node.textContent?.includes('새로고침 중'),
    ) as HTMLButtonElement | undefined;
    expect(refreshButton).not.toBeUndefined();
    expect(refreshButton?.disabled).toBe(true);
    expect(refreshButton?.getAttribute('aria-busy')).toBe('true');

    await act(async () => {
      pendingFetches.shift()?.(jsonResponse(aiHubSurface));
    });
    await flushAsyncWork();

    refreshButton = Array.from(container.querySelectorAll('button')).find((node) =>
      node.textContent?.includes('새로고침'),
    ) as HTMLButtonElement | undefined;
    expect(refreshButton?.disabled).toBe(false);
    expect(refreshButton?.getAttribute('aria-busy')).toBe('false');
  });

  it('renders a retryable error state when the source surface fails', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ message: 'Internal Server Error' }, false)));
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<AIHubPage />);
    });
    await flushAsyncWork();

    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'AI 허브 원본 근거를 불러오지 못했습니다.',
    );
    expect(container.textContent).toContain('다시 시도');
    expect(consoleError).toHaveBeenCalled();
  });
});
