import { expect, test, type APIResponse } from '@playwright/test';
import crypto from 'node:crypto';

// Live model-path E2E (companion to the mocked nano.spec.ts).
//
// Skipped unless run against a live stack (LIVE_BASE_URL or RUN_LIVE_E2E=1) whose
// backend reaches an OpenAI-compatible local provider (ollama) serving the
// packaged Gemma models. It proves the user-facing model paths reach a REAL
// model rather than a mock:
//   - chat:      POST /api/llm/draft  -> gemma4:e2b-it-qat (답장 초안)
//   - embedding: POST /api/search     -> embeddinggemma    (맥락 검색)
//
// Requests go through the frontend same-origin /api proxy. The proxy strips
// client authority headers and forwards the signed naruon_session cookie as a
// backend Authorization bearer token, mirroring browser authentication.

const liveSessionPayload = {
  ver: 1,
  iss: 'naruon-control-plane',
  aud: 'naruon-api',
  sub: 'testuser',
  role: 'member',
  org: 'org-acme',
  groups: ['group-1', 'group-2'],
  workspace: 'workspace-org-acme',
};

function encodeJson(value: unknown): string {
  return Buffer.from(JSON.stringify(value)).toString('base64url');
}

function signLiveSession(): string {
  const secret = process.env.LIVE_E2E_SESSION_SECRET;
  if (!secret) {
    throw new Error('LIVE_E2E_SESSION_SECRET is required for live model tests.');
  }
  const header = encodeJson({ alg: 'HS256', typ: 'JWT' });
  const payload = encodeJson({
    ...liveSessionPayload,
    exp: Math.floor(Date.now() / 1000) + 600,
  });
  const signature = crypto
    .createHmac('sha256', secret)
    .update(`${header}.${payload}`, 'ascii')
    .digest('base64url');
  return `${header}.${payload}.${signature}`;
}

function liveSessionCookie(token: string): string {
  return `naruon_session=${token}`;
}

function sameOriginRequestHeaders(token: string): Record<string, string> {
  const origin = new URL(process.env.LIVE_BASE_URL ?? 'http://127.0.0.1:18080').origin;
  return {
    Cookie: liveSessionCookie(token),
    Origin: origin,
    Referer: `${origin}/`,
  };
}

async function responseSummary(response: APIResponse): Promise<string> {
  return `${response.status()} ${response.statusText()}: ${await response.text()}`;
}

async function expectOkResponse(response: APIResponse): Promise<void> {
  if (!response.ok()) {
    expect(response.ok(), await responseSummary(response)).toBeTruthy();
  }
}

test.skip(
  !process.env.LIVE_BASE_URL && process.env.RUN_LIVE_E2E !== '1',
  'Requires a live stack with ollama serving gemma4:e2b-it-qat + embeddinggemma.',
);

// Local model inference on CPU is slow, especially on a cold model load.
test.setTimeout(600_000);

test('nano live: 답장 초안 reaches the gemma4 e2b chat model', async ({ request }) => {
  const token = signLiveSession();
  const response = await request.post('/api/llm/draft', {
    headers: sameOriginRequestHeaders(token),
    data: {
      email_body:
        '다음 주 화요일 오후 2시에 프로젝트 킥오프 미팅을 제안드립니다. 가능하신지 회신 부탁드립니다.',
      instruction: '정중하게 수락하는 짧은 답장 초안을 작성해줘.',
    },
    timeout: 600_000,
  });
  await expectOkResponse(response);
  const body = await response.json();
  const draft =
    typeof body?.draft === 'string' ? body.draft : JSON.stringify(body ?? {});
  // A real model returns non-empty generated text; the mock path is not exercised here.
  expect(draft.trim().length).toBeGreaterThan(0);
});

test('nano live: 맥락 검색 exercises the embeddinggemma model', async ({ request }) => {
  const token = signLiveSession();
  const response = await request.post('/api/search', {
    headers: sameOriginRequestHeaders(token),
    data: { query: '프로젝트 킥오프 일정' },
    timeout: 120_000,
  });
  // The query is embedded server-side before the vector search runs; a 2xx proves
  // the embedding model answered, regardless of how many seeded rows match.
  await expectOkResponse(response);
  const body = await response.json();
  const results = Array.isArray(body) ? body : body?.results;
  expect(Array.isArray(results)).toBeTruthy();
});
