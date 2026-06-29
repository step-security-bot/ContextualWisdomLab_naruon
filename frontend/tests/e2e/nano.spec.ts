import { expect, test } from '@playwright/test';
import crypto from 'node:crypto';

import { mockDashboardApi } from './helpers';

const publicIdentityHeaders = [
  'x-user-id',
  'x-organization-id',
  'x-group-id',
  'x-group-ids',
  'x-user-role',
  'x-dev-auth-token',
];

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

function signLiveSession(expiresInSeconds = 300): string {
  const secret = process.env.LIVE_E2E_SESSION_SECRET;
  if (!secret) {
    throw new Error('LIVE_E2E_SESSION_SECRET is required for live model nano E2E.');
  }

  const header = encodeJson({ alg: 'HS256', typ: 'JWT' });
  const payload = encodeJson({
    ...liveSessionPayload,
    exp: Math.floor(Date.now() / 1000) + expiresInSeconds,
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

test('nano test: verify user requested features', async ({ page }) => {
  const sessionToken = 'signed.nano.session';
  const providerRequestHeaders: Record<string, string>[] = [];
  await mockDashboardApi(page, (path, request) => {
    if (path === '/api/llm-providers' && request.method() === 'GET') {
      providerRequestHeaders.push(request.headers());
    }
  });
  await page.addInitScript((token) => {
    document.cookie = `naruon_session=${token}; Path=/; SameSite=Lax`;
  }, sessionToken);

  // 1. Check AI Model Settings
  await page.goto('/settings');
  await expect(page.getByText('Naruon', { exact: false }).first()).toBeVisible();

  // Click AI Models tab (use visible=true to avoid strict mode violation and hidden elements on responsive layouts)
  await page.getByRole('button', { name: 'AI 모델' }).first().click();

  await expect.poll(() => providerRequestHeaders.length).toBeGreaterThan(0);
  const headers = providerRequestHeaders.at(-1) ?? {};
  expect(headers.authorization).toBeUndefined();
  expect(headers.cookie).toContain(`naruon_session=${sessionToken}`);
  for (const headerName of publicIdentityHeaders) {
    expect(headers[headerName]).toBeUndefined();
  }

  // Verify Model registration UI
  await expect(page.getByText('로컬 모델 등록', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('임베딩 모델 지정', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('제공자 유형').first()).toBeVisible();
  await expect(page.getByText('연결 엔드포인트').first()).toBeVisible();
  await expect(page.getByText('API 엔드포인트')).toBeVisible();
  await expect(page.getByText('로컬 API 키 대체값')).toBeVisible();
  await expect(page.getByLabel('모델 식별자').nth(1)).toHaveValue('gemma4:e2b-it-qat');
  await expect(page.getByLabel('임베딩 모델').nth(1)).toHaveValue('embeddinggemma');
  await expect(page.getByText('Provider', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Endpoint', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Local API key override', { exact: true })).toHaveCount(0);

  // 2. Check Data page for email import
  await page.goto('/data');
  await expect(page.getByRole('button', { name: '이메일 파일 선택' })).toBeVisible();
  await expect(page.getByRole('button', { name: '선택 파일 반입' })).toBeVisible();
});

test('nano live model: ollama gemma4 e2b chat and embedding search complete', async ({ request }) => {
  test.setTimeout(600_000);
  test.skip(
    process.env.RUN_LIVE_MODEL_E2E !== '1' || !process.env.LIVE_BASE_URL,
    'Requires live Docker Compose stack with Ollama Gemma4 models.',
  );

  const token = signLiveSession(1_200);
  const cookie = liveSessionCookie(token);

  const draftResponse = await request.post('/api/llm/draft', {
    headers: { Cookie: cookie },
    data: {
      email_body: 'Live Gemma4 verification request from Naruon E2E.',
      instruction: 'Reply with one concise Korean sentence confirming receipt.',
    },
    timeout: 600_000,
  });
  expect(draftResponse.ok()).toBeTruthy();
  const draftBody = await draftResponse.json();
  expect(String(draftBody.draft ?? '').trim().length).toBeGreaterThan(0);

  const searchResponse = await request.post('/api/search', {
    headers: { Cookie: cookie },
    data: { query: 'Live E2E Release', limit: 3 },
    timeout: 600_000,
  });
  expect(searchResponse.ok()).toBeTruthy();
  const searchBody = await searchResponse.json();
  const subjects = new Set(
    (searchBody.results ?? []).map((item: { subject?: string | null }) => item.subject),
  );
  expect(subjects.has('Live E2E Release')).toBe(true);
});
