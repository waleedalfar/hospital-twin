/**
 * End to end for extra X1: paging a patient's nurse raises the same pop-up as a high-risk alert, the nurse walks to the
 * bedside, acknowledging records the response time, and the governance tab shows it. Everything is read from the API.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

import type { TwinDebug } from '../src/engine/debug';
import type { SnapshotMessage } from '../src/state/wsTypes';

const EVIDENCE = '../docs/evidence/cp9';

async function reset(request: APIRequestContext): Promise<void> {
  for (const [path, data] of [
    ['/api/sim/freeze', { frozen: false }],
    ['/api/sim/pause', { paused: false }],
    ['/api/sim/speed', { speed: 1 }],
  ] as const) {
    expect((await request.post(path, { data })).ok()).toBe(true);
  }
}

test.afterEach(async ({ request }) => {
  await reset(request);
});

test('X1. paging a nurse shows a pop-up addressed to the right nurse, acknowledging is timed, and governance shows it', async ({ page, request }: { page: Page; request: APIRequestContext }) => {
  test.setTimeout(120_000);
  await reset(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  // Frozen while the patient is selected, so nothing moves under the click; unfrozen after the page.
  await page.goto('/?freeze=1#/hospital/mercy');
  await page.waitForFunction(() => (window as unknown as { __TWIN_DEBUG__: TwinDebug }).__TWIN_DEBUG__.frameStats().frames > 3);
  await expect.poll(async () => ((await (await request.get('/api/sim')).json()) as { frozen: boolean }).frozen, { timeout: 15_000 }).toBe(true);
  await page.waitForTimeout(800);

  // A scored patient in a bed whose nurse the API names, on a floor we look at; one that no HUD panel covers.
  const state = (await (await request.get('/api/hospitals/mercy/state')).json()) as SnapshotMessage;
  const candidates = state.entities.filter((e) => e.kind === 'patient' && e.location.bed && e.risk && e.nurse_id);
  expect(candidates.length, 'scored patients with an assigned nurse').toBeGreaterThan(0);
  const floor = candidates[0]?.location.floor ?? 0;
  const preset = { 0: 'Ground floor', 1: 'Floor 2', 2: 'Floor 3' }[floor] ?? 'Outside';
  await page.getByRole('button', { name: preset }).click();
  await page.waitForTimeout(1500);
  const box = await page.getByTestId('scene').boundingBox();
  let target = candidates[0];
  let point: { x: number; y: number } | null = null;
  for (const c of candidates.filter((e) => e.location.floor === floor)) {
    const p = await page.evaluate((pid) => (window as unknown as { __TWIN_DEBUG__: TwinDebug }).__TWIN_DEBUG__.screenPoint(pid), c.id);
    if (!p) continue;
    const onCanvas = await page.evaluate(([x, y]) => document.elementFromPoint(x ?? 0, y ?? 0)?.getAttribute('data-testid') === 'scene', [(box?.x ?? 0) + p.x, (box?.y ?? 0) + p.y]);
    if (onCanvas) {
      target = c;
      point = p;
      break;
    }
  }
  expect(point, 'a patient that is not under a HUD panel').not.toBeNull();
  const id = target?.id ?? '';
  const nurse = target?.nurse_id ?? '';
  expect(nurse).toMatch(/^N-\d+/);

  // Select the patient through the UI: the inspector names the nurse.
  await page.mouse.click((box?.x ?? 0) + (point?.x ?? 0), (box?.y ?? 0) + (point?.y ?? 0));
  await expect(page.getByTestId('inspector-id')).toHaveText(id);
  await expect(page.getByTestId('inspector-nurse')).toContainText(`Nurse ${nurse}`);

  // Page the nurse: the pop-up is addressed to them, with the patient and bed.
  await page.getByTestId('page-nurse').click();
  const toast = page.locator('[data-testid^="nurse-alert-"]').first();
  await expect(toast).toBeVisible({ timeout: 15_000 });
  await expect(toast).toContainText(`${nurse}: ${id} in ${target?.location.bed}`);
  await expect(toast).toContainText('Paged from the inspector');
  const alerts = (await (await request.get('/api/nurse-alerts?status=pending')).json()) as { id: string; nurse_id: string; patient_id: string }[];
  const mine = alerts.find((a) => a.patient_id === id);
  expect(mine?.nurse_id).toBe(nurse);
  await expect.poll(() => page.evaluate(() => (window as unknown as { __TWIN_DEBUG__: TwinDebug }).__TWIN_DEBUG__.highlighted().ids), { timeout: 10_000 }).toContain(nurse);
  await page.screenshot({ path: `${EVIDENCE}/nurse-alert.png` });

  // The sim sends the nurse to the bedside (a few sim minutes at 8x).
  await request.post('/api/sim/freeze', { data: { frozen: false } });
  await request.post('/api/sim/speed', { data: { speed: 8 } });
  await page.waitForTimeout(6000);

  await toast.getByRole('button', { name: 'Acknowledge' }).click();
  await expect.poll(async () => ((await (await request.get('/api/nurse-alerts?status=acknowledged&limit=200')).json()) as { id: string }[]).some((a) => a.id === mine?.id), { timeout: 15_000 }).toBe(true);
  await expect(page.locator(`[data-testid="nurse-alert-${mine?.id}"]`)).toHaveCount(0);

  const audit = (await (await request.get('/api/governance/audit?limit=300')).json()) as { action: string; actor: string; payload: Record<string, unknown> }[];
  const acknowledged = audit.find((r) => r.action === 'nurse_alert_acknowledged' && r.payload['id'] === mine?.id);
  expect(acknowledged?.actor).toBe('user');
  expect(Number(acknowledged?.payload['seconds_to_ack'])).toBeGreaterThan(0);
  expect(audit.some((r) => r.action === 'nurse_paged' && r.payload['id'] === mine?.id)).toBe(true);

  // Governance shows the response time.
  await page.getByTestId('governance-button').click();
  await page.getByRole('tab', { name: 'Nurse response' }).click();
  await expect(page.getByTestId('nurse-response')).toBeVisible();
  await expect(page.getByTestId('nr-mean')).toContainText('sim min');
  await page.screenshot({ path: `${EVIDENCE}/nurse-response.png` });
});
