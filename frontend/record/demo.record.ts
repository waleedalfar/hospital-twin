/**
 * Performs the 3-minute demo from docs/demo_script.md in the real app and saves the video to docs/demo.webm.
 * Nothing is faked: every step drives the live stack (the flu surge is the one thing a presenter starts by hand).
 */
import { test, type Page } from '@playwright/test';

import type { TwinDebug } from '../src/engine/debug';

const pause = (page: Page, ms: number): Promise<void> => page.waitForTimeout(ms);

async function api(page: Page, method: 'GET' | 'POST', path: string, data?: object): Promise<unknown> {
  const response = await page.request.fetch(`/api${path}`, { method, ...(data ? { data } : {}) });
  return response.ok() ? response.json() : null;
}

test('record the demo', async ({ page }) => {
  await api(page, 'POST', '/sim/freeze', { frozen: false });
  await api(page, 'POST', '/sim/pause', { paused: false });
  await api(page, 'POST', '/sim/speed', { speed: 4 });

  // Network map, then Mercy in 3D.
  await page.goto('/');
  await page.getByTestId('hospital-mercy').waitFor();
  await pause(page, 4000);
  await page.getByTestId('hospital-mercy').click();
  await page.waitForFunction(() => (window as unknown as { __TWIN_DEBUG__: TwinDebug }).__TWIN_DEBUG__.frameStats().frames > 10);
  await pause(page, 3000);

  // X-ray and the ICU close-up.
  await page.getByRole('button', { name: /^X-ray/ }).click();
  await pause(page, 2000);
  await page.getByRole('button', { name: 'ICU close-up' }).click();
  await pause(page, 3500);

  // The highest-risk ICU patient and why.
  const state = (await api(page, 'GET', '/hospitals/mercy/state')) as { entities: { id: string; kind: string; risk: { score: number } | null; location: { bed: string | null } }[] } | null;
  const icu = (state?.entities ?? []).filter((e) => e.kind === 'patient' && e.risk && (e.location.bed ?? '').startsWith('ICU')).sort((a, b) => (b.risk?.score ?? 0) - (a.risk?.score ?? 0));
  const top = icu[0];
  if (top) {
    const point = await page.evaluate((id) => (window as unknown as { __TWIN_DEBUG__: TwinDebug }).__TWIN_DEBUG__.screenPoint(id), top.id);
    const box = await page.getByTestId('scene').boundingBox();
    if (point && box) await page.mouse.click(box.x + point.x, box.y + point.y);
    await pause(page, 5000);
  }
  await page.getByRole('button', { name: /^X-ray/ }).click();
  await page.getByRole('button', { name: 'Outside' }).click();
  await pause(page, 2500);

  // Flu surge, 8x.
  await api(page, 'POST', '/scenario', { name: 'flu_surge', hospital_id: 'mercy' });
  await api(page, 'POST', '/sim/speed', { speed: 8 });
  await pause(page, 30_000);

  // Drift, then the agent's recommendation and approval.
  await page.getByTestId('governance-button').click();
  await pause(page, 6000);
  await page.getByTestId('governance-button').click();
  await page.locator('[data-testid^="rec-REC-"].rec--pending').first().waitFor({ timeout: 120_000 });
  await pause(page, 4000);
  const approve = page.locator('[data-testid^="rec-REC-"].rec--pending').first().getByRole('button', { name: 'Approve' });
  await approve.click();
  await pause(page, 3000);
  await page.getByRole('button', { name: '← City' }).click();
  await pause(page, 8000);
  await page.getByTestId('hospital-mercy').click();
  await pause(page, 3000);

  // Ask a question, then fly to the patient.
  await page.getByTestId('ask-input').fill('who is most likely to crash tonight');
  await pause(page, 1500);
  await page.getByTestId('ask-send').click();
  await page.getByTestId('ask-answer').waitFor({ timeout: 20_000 });
  await pause(page, 5000);
  const fly = page.getByRole('button', { name: 'Fly to' }).first();
  if (await fly.isVisible()) await fly.click();
  await pause(page, 5000);

  // Governance: federated training and the model card.
  await page.getByTestId('governance-button').click();
  await page.getByRole('tab', { name: 'Federated training' }).click();
  await pause(page, 6000);
  await page.getByRole('tab', { name: 'Fairness' }).click();
  await pause(page, 4000);
  await api(page, 'POST', '/sim/speed', { speed: 1 });

  const video = page.video();
  await page.close();
  await video?.saveAs('../docs/demo.webm');
});
