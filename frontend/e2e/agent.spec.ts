/**
 * End to end, PROMPT.md §11 test 7: a flu surge raises the waiting count, a drift alert appears, and the
 * operations agent recommends something that the user approves, which changes the sim and writes the audit log.
 * Everything is read from the live backend.
 */
import { expect, test, type APIRequestContext } from '@playwright/test';

const EVIDENCE = '../docs/evidence/cp6';

interface AuditRow {
  actor: string;
  action: string;
  payload: Record<string, unknown>;
}
interface Rec {
  id: string;
  action: string;
  status: string;
  source: string;
  label: string | null;
  cited_metrics: { name: string; value: number }[];
}

async function reset(request: APIRequestContext): Promise<void> {
  for (const [path, data] of [
    ['/api/sim/freeze', { frozen: false }],
    ['/api/sim/pause', { paused: false }],
    ['/api/sim/speed', { speed: 1 }],
  ] as const) {
    expect((await request.post(path, { data })).ok()).toBe(true);
  }
}

const waiting = async (request: APIRequestContext): Promise<number> =>
  ((await (await request.get('/api/hospitals/mercy/state')).json()) as { kpis: { waiting: number } }).kpis.waiting;

test.afterEach(async ({ request }) => {
  await reset(request);
});

test('7. flu surge: waiting rises, a drift alert fires, the agent recommends, approving changes the sim and is audited', async ({ page, request }) => {
  test.setTimeout(240_000);
  await reset(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/#/hospital/mercy');
  await expect(page.getByTestId('agent-panel')).toBeVisible();

  const before = await waiting(request);
  const quietAlerts = ((await (await request.get('/api/governance/audit?action=drift_alert&limit=500')).json()) as AuditRow[]).length;
  expect((await request.post('/api/sim/speed', { data: { speed: 8 } })).ok()).toBe(true);
  const started = await request.post('/api/scenario', { data: { name: 'flu_surge', hospital_id: 'mercy' } });
  expect(started.status()).toBe(201);

  // The waiting room fills.
  await expect.poll(() => waiting(request), { timeout: 150_000, intervals: [1000] }).toBeGreaterThan(before);

  // A drift alert is written for Mercy on a respiratory vital, and shows in the governance drawer.
  await expect
    .poll(
      async () => {
        const rows = (await (await request.get('/api/governance/audit?action=drift_alert&limit=500')).json()) as AuditRow[];
        const fresh = rows.slice(0, Math.max(0, rows.length - quietAlerts));
        return fresh.some((r) => r.payload['hospital_id'] === 'mercy' && ['spo2', 'rr', 'spo2_min_2h', 'rr_max_2h'].includes(String(r.payload['feature'])));
      },
      { timeout: 150_000, intervals: [1000] },
    )
    .toBe(true);

  // A recommendation appears in the panel, with its cited numbers, and is labelled when the rules engine made it.
  const pending = page.locator('[data-testid^="rec-REC-"].rec--pending').first();
  await expect(pending).toBeVisible({ timeout: 150_000 });
  await expect(pending.locator('.rec__metrics li').first()).toBeVisible();
  const recs = (await (await request.get('/api/agent/recs?hospital=mercy&status=pending')).json()) as Rec[];
  expect(recs.length).toBeGreaterThan(0);
  for (const r of recs) {
    expect(r.cited_metrics.length).toBeGreaterThan(0);
    if (r.source === 'rules') expect(r.label).toBe('Rules engine — Gemini unavailable');
  }
  await page.screenshot({ path: `${EVIDENCE}/agent-panel.png` });

  // Approve the first one in the UI. The sim changes and the audit log records who did what.
  const id = (await pending.getAttribute('data-testid'))?.replace('rec-', '') ?? '';
  const chosen = recs.find((r) => r.id === id) ?? recs[0];
  expect(chosen).toBeDefined();
  await pending.getByRole('button', { name: 'Approve' }).click();
  await expect.poll(async () => ((await (await request.get(`/api/agent/recs?hospital=mercy&status=approved`)).json()) as Rec[]).some((r) => r.id === id), { timeout: 20_000 }).toBe(true);
  const audit = (await (await request.get('/api/governance/audit?limit=500')).json()) as AuditRow[];
  const approved = audit.find((r) => r.action === 'agent_rec_approved' && r.payload['id'] === id);
  expect(approved?.actor).toBe('user');
  expect(audit.some((r) => r.action === 'action_applied')).toBe(true);
  if (chosen?.action === 'divert_ambulances') {
    await expect.poll(async () => ((await (await request.get('/api/hospitals/mercy/state')).json()) as { hospital: { status: string } }).hospital.status, { timeout: 20_000 }).toBe('diverting');
  }
  await expect(page.getByTestId(`rec-${id}`)).toHaveClass(/rec--approved/);

  // The governance drawer shows the drift heatmap with an alert cell, the fairness table and the audit log.
  await page.getByTestId('governance-button').click();
  await expect(page.getByTestId('drift-heatmap')).toBeVisible();
  await expect(page.locator('[data-testid^="drift-mercy-"][data-alert="true"]').first()).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: `${EVIDENCE}/governance-drift.png` });
  await page.getByRole('tab', { name: 'Fairness' }).click();
  await expect(page.getByTestId('fairness')).toBeVisible({ timeout: 30_000 });
  await page.getByRole('tab', { name: 'Audit log' }).click();
  await expect(page.getByTestId('audit-row').first()).toBeVisible();
  await expect(page.getByTestId('audit')).toContainText('agent_rec_approved');
  await page.screenshot({ path: `${EVIDENCE}/governance-audit.png` });
});
