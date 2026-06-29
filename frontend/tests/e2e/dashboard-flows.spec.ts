import { expect, test } from '@playwright/test';

import { mockDashboardApi } from './helpers';

test('connects inbox selection to summary, execution, reply, calendar, and graph states', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Desktop shell flow has separate mobile detail coverage.');
  await mockDashboardApi(page);

  await page.goto('/');
  await page.getByRole('button', { name: '메일함 바로가기' }).first().click();
  await page.getByRole('button', { name: /김지현 PM/ }).click();

  await expect(page.getByText('출시 일정, 마케팅 계획, 파트너 미팅')).toBeVisible();
  await expect(page.getByText('리소스 배정 검토 회의')).toBeVisible();
  await expect(page.getByText('마케팅 캠페인 오프')).toBeVisible();
  await expect(page.getByText('2개 메시지').nth(1)).toBeVisible();
  await expect(page.getByText('2개 노드와 1개 관계')).toBeVisible();

  await page.getByRole('button', { name: '일정 반영' }).last().click();
  await expect(page.getByText('2개 일정 반영 의도를 선택한 원본 계정에 요청했습니다.')).toBeVisible();

  await page.getByRole('button', { name: '답장 초안 생성' }).last().click();
  await expect(page.getByRole('textbox', { name: '답장 초안', exact: true })).toHaveValue('검토 후 일정과 우선순위를 정리해 공유드리겠습니다.');

  await page.getByRole('button', { name: '답장 보내기' }).click();
  await expect(page.getByText('개발 모드에서 답장을 시뮬레이션했습니다. 실제 메일은 전송되지 않았습니다.')).toBeVisible();
});

test('submits branded inbox search against the search API', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Desktop search box is covered by the desktop shell project.');
  await mockDashboardApi(page);

  await page.goto('/');
  await page.getByRole('button', { name: '메일함 바로가기' }).first().click();
  const desktopWorkspace = page.getByRole('region', { name: '데스크톱 메일 작업공간' });
  await desktopWorkspace.getByLabel('메일 맥락 검색').fill('출시');
  await desktopWorkspace.getByRole('button', { name: /^맥락 검색( 중)?$/ }).click();

  await expect(desktopWorkspace.getByText('Q2 출시 계획 및 우선순위 조정')).toBeVisible();
});

test('selects an email on mobile and executes visible detail task actions', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockDashboardApi(page);

  await page.goto('/');
  await page.getByRole('button', { name: '메일함 바로가기' }).first().click();
  await page.getByRole('button', { name: /김지현 PM/ }).click();

  const detailRegion = page.getByRole('region', { name: '모바일 메일 상세' });
  await expect(detailRegion).toBeVisible();
  await expect(detailRegion.getByText('Q2 출시 계획 및 우선순위 조정')).toBeVisible();
  await expect(detailRegion.getByText('출시 일정, 마케팅 계획, 파트너 미팅')).toBeVisible();
  await expect(detailRegion.getByRole('heading', { name: '실행 항목' })).toBeVisible();
  await detailRegion.getByRole('button', { name: '실행 항목 생성' }).click();
  await expect(detailRegion.getByText('2개 실행 항목을 티켓형 실행 항목으로 추적합니다.')).toBeVisible();
});
