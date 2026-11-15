/**
 * End to end, PROMPT.md §11 tests 11 and 12: a typed "Ask Hospital Twin" question highlights the right patient,
 * and a federated training run started from the UI streams round progress and the model switch changes the model
 * version shown in the inspector. Everything is read from the live backend.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

import type { TwinDebug } from '../src/engine/debug';
import type { SnapshotMessage } from '../src/state/wsTypes';

const EVIDENCE = '../docs/evidence/cp7';
const debug = <T>(page: Page, fn: (d: TwinDebug) => T): Promise<T> => page.evaluate<T>(`(${fn.toString()})(window.__TWIN_DEBUG__)`);

async function reset(request: APIRequestContext): Promise<void> {
  for (const [path, data] of [
    ['/api/sim/freeze', { frozen: false }],
    ['/api/sim/pause', { paused: false }],
    ['/api/sim/speed', { speed: 1 }],
  ] as const) {
    expect((await request.post(path, { data })).ok()).toBe(true);
  }
}

async function state(request: APIRequestContext): Promise<SnapshotMessage> {
  return (await (await request.get('/api/hospitals/mercy/state')).json()) as SnapshotMessage;
}

test.afterEach(async ({ request }) => {
  await reset(request);
});

test('11. a typed question highlights the highest-risk ICU patient', async ({ page, request }) => {
  await reset(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/?freeze=1#/hospital/mercy');
  await page.waitForFunction(() => (window as unknown as { __TWIN_DEBUG__: TwinDebug }).__TWIN_DEBUG__.frameStats().frames > 3);
  await expect.poll(async () => ((await (await request.get('/api/sim')).json()) as { frozen: boolean }).frozen, { timeout: 15_000 }).toBe(true);
  await page.waitForTimeout(800);

  // The highest-risk patient in the ICU, according to the API.
  const snap = await state(request);
  const icu = snap.entities
    .filter((e) => e.kind === 'patient' && e.risk && (e.location.bed ?? '').startsWith('ICU'))
    .sort((a, b) => (b.risk?.score ?? 0) - (a.risk?.score ?? 0));
  test.skip(icu.length === 0, 'no scored ICU patient in this run');
  const top = icu[0];
  expect(top).toBeDefined();

  await expect(page.getByTestId('ask-panel')).toBeVisible();
  await page.getByTestId('ask-input').fill('who is most likely to crash in the ICU');
  await page.getByTestId('ask-send').click();

  const answer = page.getByTestId('ask-answer-text');
  await expect(answer).toContainText(top?.id ?? '', { timeout: 15_000 });
  await expect(answer).toContainText((top?.risk?.score ?? 0).toFixed(2));
  // Without a Gemini key the deterministic parser answers, and says so.
  await expect(page.getByTestId('ask-label')).toHaveText('Fallback intent parser — Gemini unavailable');

  // The scene highlights that patient first: a ring and an X-ray marker are drawn for them.
  await expect.poll(() => debug(page, (d) => d.highlighted().ids), { timeout: 10_000 }).toContain(top?.id ?? '');
  expect((await debug(page, (d) => d.highlighted().ids))[0]).toBe(top?.id);
  await expect.poll(() => debug(page, (d) => d.highlighted().drawn), { timeout: 10_000 }).toBeGreaterThan(0);
  await page.screenshot({ path: `${EVIDENCE}/ask-highlight.png` });

  // "Fly to" selects the patient and opens the inspector on the same id.
  await page.getByRole('button', { name: 'Fly to' }).first().click();
  await expect(page.getByTestId('inspector-id')).toHaveText(top?.id ?? '');

  // Closing the answer clears its highlight. (A nurse with a pending alert is ringed too, so only patients are checked.)
  await page.getByTestId('ask-answer').getByRole('button', { name: 'Close' }).click();
  await expect.poll(async () => (await debug(page, (d) => d.highlighted().ids)).filter((i) => i.startsWith('P-'))).toEqual([]);

  // A question outside the tools gets an honest "I can answer questions about ..." and highlights nothing.
  await page.getByTestId('ask-input').fill('tell me a joke');
  await page.getByTestId('ask-send').click();
  await expect(page.getByTestId('ask-answer-text')).toContainText('I can answer questions about');
  expect((await debug(page, (d) => d.highlighted().ids)).filter((i) => i.startsWith('P-'))).toEqual([]);
});

test('12. federated training from the UI streams round progress, and the model switch changes the version in the inspector', async ({ page, request }) => {
  test.setTimeout(300_000);
  await reset(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/?freeze=1#/hospital/mercy');
  await page.waitForFunction(() => (window as unknown as { __TWIN_DEBUG__: TwinDebug }).__TWIN_DEBUG__.frameStats().frames > 3);
  await expect.poll(async () => ((await (await request.get('/api/sim')).json()) as { frozen: boolean }).frozen, { timeout: 15_000 }).toBe(true);
  await page.waitForTimeout(800);

  try {
    // Run federated training from the governance drawer and watch the rounds arrive over the WebSocket.
    await page.getByTestId('governance-button').click();
    await page.getByRole('tab', { name: 'Federated training' }).click();
    await expect(page.getByTestId('federated')).toBeVisible();
    await page.getByTestId('fed-run').click();
    await expect(page.getByTestId('fed-progress')).toHaveText(/Round \d+ of 25/, { timeout: 120_000 });
    const seen = new Set<string>();
    await expect
      .poll(async () => {
        seen.add((await page.getByTestId('fed-progress').textContent()) ?? '');
        return (await page.getByTestId('fed-progress').textContent()) ?? '';
      }, { timeout: 240_000, intervals: [250] })
      .toBe('Done: 25 rounds');
    expect(seen.size).toBeGreaterThan(1); // progress changed while it ran
    await expect(page.getByTestId('fed-comparison')).toContainText('Federated MLP (FedAvg)');
    await page.screenshot({ path: `${EVIDENCE}/federated.png` });

    // The numbers on screen are the ones the API serves, and the gates passed.
    const status = (await (await request.get('/api/federated')).json()) as {
      state: { status: string; val_auroc: number[] };
      result: { federated: { test: { auroc: number }; validation_auroc_by_round: number[] }; centralized: { test: { auroc: number } }; local_only: { mean_auroc: number }; gates: Record<string, boolean> };
    };
    expect(status.state.status).toBe('done');
    expect(status.result.federated.validation_auroc_by_round).toHaveLength(25);
    expect(status.result.federated.test.auroc).toBeGreaterThanOrEqual(status.result.centralized.test.auroc - 0.03);
    expect(status.result.federated.test.auroc).toBeGreaterThan(status.result.local_only.mean_auroc);
    expect(Object.values(status.result.gates).every(Boolean)).toBe(true);
    await expect(page.getByTestId('fed-comparison')).toContainText(status.result.federated.test.auroc.toFixed(3));
    await page.getByTestId('governance-drawer').getByRole('button', { name: 'Close' }).click();

    // Open a scored patient: the inspector shows the central model.
    const snap = await state(request);
    const target = snap.entities.find((e) => e.kind === 'patient' && e.risk && e.location.bed);
    test.skip(target === undefined, 'no scored patient in a bed');
    const id = target?.id ?? '';
    const preset = { 0: 'Ground floor', 1: 'Floor 2', 2: 'Floor 3' }[target?.location.floor ?? 0] ?? 'Outside';
    await page.getByRole('button', { name: preset }).click();
    await page.waitForTimeout(1500);
    const point = await page.evaluate((pid) => (window as unknown as { __TWIN_DEBUG__: TwinDebug }).__TWIN_DEBUG__.screenPoint(pid), id);
    expect(point).not.toBeNull();
    const box = await page.getByTestId('scene').boundingBox();
    await page.mouse.click((box?.x ?? 0) + (point?.x ?? 0), (box?.y ?? 0) + (point?.y ?? 0));
    await expect(page.getByTestId('inspector-id')).toHaveText(id);
    await expect(page.getByTestId('inspector')).toContainText('model lgbm-v1');

    // Switch the live model to the federated MLP: the inspector (and the API) show the new version.
    await page.getByTestId('governance-button').click();
    await page.getByRole('tab', { name: 'Federated training' }).click();
    await page.getByLabel(/Federated MLP/).click();
    await expect.poll(async () => ((await (await request.get('/api/models')).json()) as { active_deterioration: string }).active_deterioration, { timeout: 15_000 }).toBe('fed-mlp-v1');
    await page.getByTestId('governance-drawer').getByRole('button', { name: 'Close' }).click();
    await expect(page.getByTestId('inspector')).toContainText('model fed-mlp-v1', { timeout: 20_000 });
    const after = await state(request);
    expect(after.entities.find((e) => e.id === id)?.risk?.model_version).toBe('fed-mlp-v1');
    await page.screenshot({ path: `${EVIDENCE}/model-switch.png` });
    const audit = (await (await request.get('/api/governance/audit?action=model_switch&limit=5')).json()) as { payload: { from: string; to: string } }[];
    expect(audit[0]?.payload).toEqual({ from: 'lgbm-v1', to: 'fed-mlp-v1' });
  } finally {
    // Leave the stack as other tests expect it: the central model scoring.
    await request.post('/api/models/active', { data: { version: 'lgbm-v1' } });
  }
});
