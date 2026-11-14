import { expect, test } from '@playwright/test';

import type { Health } from '../src/state/health';

test('shell loads and shows the live backend status from the API', async ({ page, request }) => {
  const apiResponse = await request.get('/api/health');
  expect(apiResponse.status()).toBe(200);
  const health = (await apiResponse.json()) as Health;
  expect(health.db).toBe('ok');
  expect(health.timescaledb_version).toMatch(/^\d+\.\d+/);
  expect(health.migrations_applied).toBeGreaterThanOrEqual(1);

  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Hospital Twin');
  await expect(page.getByText('Simulated data')).toBeVisible();

  const status = page.getByTestId('backend-status');
  await expect(status).toHaveAttribute('data-tone', 'ok');
  const migrations = health.migrations_applied ?? 0;
  await expect(status).toHaveText(
    `Backend OK - TimescaleDB ${health.timescaledb_version ?? ''} - ${migrations} migration${migrations === 1 ? '' : 's'} applied`,
  );

  await page.screenshot({ path: '../docs/evidence/cp0/shell.png' });
});

test('WebGL is available in the headless browser (SwiftShader)', async ({ page }) => {
  await page.goto('/');
  const renderer = await page.evaluate(() => {
    const gl = document.createElement('canvas').getContext('webgl');
    if (!gl) return null;
    const info = gl.getExtension('WEBGL_debug_renderer_info');
    return info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : 'webgl';
  });
  expect(renderer).not.toBeNull();
});
