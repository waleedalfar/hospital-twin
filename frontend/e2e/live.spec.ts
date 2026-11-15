/**
 * End to end against the real stack: backend + TimescaleDB + frontend (PROMPT.md §11, tests 1-6, 8, 10).
 * Nothing here uses a fixture: every expected value is read from the backend API.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

import type { TwinDebug } from '../src/engine/debug';
import type { SnapshotMessage } from '../src/state/wsTypes';

const EVIDENCE = '../docs/evidence/cp4';
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

async function state(request: APIRequestContext, id = 'mercy'): Promise<SnapshotMessage> {
  const res = await request.get(`/api/hospitals/${id}/state`);
  expect(res.ok()).toBe(true);
  return (await res.json()) as SnapshotMessage;
}

/** Open a hospital's 3D view with the sim frozen, and wait until the scene shows the same state as the API. */
async function openFrozen(page: Page, request: APIRequestContext, hospital = 'mercy'): Promise<SnapshotMessage> {
  await page.goto(`/?freeze=1#/hospital/${hospital}`);
  await page.waitForFunction(() => (window as unknown as { __TWIN_DEBUG__: TwinDebug }).__TWIN_DEBUG__.frameStats().frames > 3);
  await expect.poll(async () => (await request.get('/api/sim')).json().then((s: { frozen: boolean }) => s.frozen), { timeout: 15_000 }).toBe(true);
  // The sim is frozen now; wait for the page to receive the last tick.
  await page.waitForTimeout(800);
  return state(request, hospital);
}

function drawn(s: SnapshotMessage): SnapshotMessage['entities'] {
  // People sitting in a vehicle are not drawn in the building; an EMT walking a patient in is.
  return s.entities.filter((e) => e.location.floor !== null && (!e.location.vehicle || e.move));
}

test.beforeEach(async ({ request }) => {
  await reset(request);
});

test.afterEach(async ({ request }) => {
  await reset(request);
});

test('1. the network map loads, three hospitals render, and clicking Mercy opens the 3D view', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  for (const id of ['mercy', 'stlukes', 'desert']) await expect(page.getByTestId(`hospital-${id}`)).toBeVisible();
  await expect(page.getByTestId('hospital-mercy')).toContainText('Mercy General');
  await expect(page.getByTestId('hospital-row-mercy')).toContainText(/OK|BUSY|CRITICAL|OFFLINE/);
  await expect(page.getByTestId('sim-clock')).toContainText(/SIM DAY \d+ · \d\d:\d\d/);
  await page.screenshot({ path: `${EVIDENCE}/network-map.png` });
  await page.getByTestId('hospital-mercy').click();
  await expect(page).toHaveURL(/#\/hospital\/mercy$/);
  await expect(page.getByTestId('scene')).toBeVisible();
  await page.waitForFunction(() => Object.keys((window as unknown as { __TWIN_DEBUG__: TwinDebug }).__TWIN_DEBUG__.counts()).length > 0, undefined, { timeout: 20_000 });
  await expect(page.getByTestId('kpis')).toContainText('CENSUS');
});

test('2. __TWIN_DEBUG__.counts() equals the counts from GET /hospitals/mercy/state', async ({ page, request }) => {
  const api = await openFrozen(page, request);
  const expected: Record<string, number> = {};
  for (const e of drawn(api)) expected[e.kind] = (expected[e.kind] ?? 0) + 1;
  await expect.poll(() => debug(page, (d) => d.counts()), { timeout: 15_000 }).toEqual(expected);
  expect(Object.values(expected).reduce((a, b) => a + b, 0)).toBeGreaterThan(15);
  expect(await debug(page, (d) => d.problems())).toEqual([]);
});

test('3. every occupied bed from the API has a lying patient at that bed', async ({ page, request }) => {
  const api = await openFrozen(page, request);
  const simNow = Date.parse(api.sim_time);
  const settled = new Map(api.entities.filter((e) => !e.move || Date.parse(e.move.arrive) <= simNow).map((e) => [e.id, e]));
  const occupied = api.beds.filter((b) => b.state === 'occupied' && b.patient_id && settled.has(b.patient_id));
  expect(occupied.length).toBeGreaterThan(5);
  await expect.poll(() => debug(page, (d) => d.beds()), { timeout: 15_000 }).toEqual(Object.fromEntries(occupied.map((b) => [b.id, b.patient_id])));
  const rendered = await debug(page, (d) => d.entities());
  for (const b of occupied) expect(rendered.find((r) => r.bed === b.id)).toMatchObject({ id: b.patient_id, pose: 'lying', mode: 'bed' });
});

test('4. X-ray: markers become visible and the shell opacity changes', async ({ page, request }) => {
  await openFrozen(page, request);
  expect(await debug(page, (d) => d.xray())).toMatchObject({ on: false, wallOpacity: 1, markersVisible: 0 });
  await page.getByRole('button', { name: 'X-ray', exact: true }).click();
  await expect.poll(() => debug(page, (d) => d.xray())).toMatchObject({ on: true, wallOpacity: 0.07, floorOpacity: 0.55 });
  expect((await debug(page, (d) => d.xray())).markersVisible).toBeGreaterThan(15);
  await expect(page.getByTestId('xray-legend')).toContainText('Nurse');
  await page.getByRole('button', { name: 'Ground floor' }).click();
  await page.getByRole('button', { name: 'Floor 3' }).click();
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${EVIDENCE}/xray-floor3.png` });
  await page.getByRole('button', { name: 'X-ray on' }).click();
  await expect.poll(() => debug(page, (d) => d.xray())).toMatchObject({ on: false, wallOpacity: 1, markersVisible: 0 });
});

test('5. clicking a patient in a bed opens the inspector with the same id as the API', async ({ page, request }) => {
  const api = await openFrozen(page, request);
  const simNow = Date.parse(api.sim_time);
  const inBed = api.entities.filter((e) => e.kind === 'patient' && e.location.bed && !e.move && Date.parse(api.sim_time) >= simNow);
  expect(inBed.length).toBeGreaterThan(3);
  // ICU-3 first, then the other ICU beds, then any bed on that floor: the first one that no HUD panel is drawn over.
  const ordered = [inBed.find((e) => e.location.bed === 'ICU-3'), ...inBed.filter((e) => e.location.room === 'ICU'), ...inBed].filter((e): e is (typeof inBed)[number] => e !== undefined);
  const floor = ordered[0]?.location.floor ?? 0;
  const preset = { 0: 'Ground floor', 1: 'Floor 2', 2: 'Floor 3' }[floor] ?? 'Outside';
  await page.getByRole('button', { name: preset }).click();
  await expect.poll(() => debug(page, (d) => d.view().floorY.length), { timeout: 5000 }).toBe(3);
  await page.waitForTimeout(1500);
  const box = (await page.getByTestId('scene').boundingBox())!;
  let target = ordered[0]!;
  let point: { x: number; y: number } | null = null;
  for (const c of ordered.filter((e) => e.location.floor === floor)) {
    const p = await page.evaluate((id) => (window as unknown as { __TWIN_DEBUG__: TwinDebug }).__TWIN_DEBUG__.screenPoint(id), c.id);
    if (!p) continue;
    const free = await page.evaluate(([x, y]) => document.elementFromPoint(x ?? 0, y ?? 0)?.getAttribute('data-testid') === 'scene', [box.x + p.x, box.y + p.y]);
    if (free) {
      target = c;
      point = p;
      break;
    }
  }
  expect(point, 'a patient that no HUD panel covers').not.toBeNull();
  await page.mouse.click(box.x + point!.x, box.y + point!.y);
  await expect(page.getByTestId('inspector-id')).toHaveText(target.id);
  expect(await debug(page, (d) => d.selected())).toBe(target.id);
  await expect(page.getByTestId('inspector-bed')).toContainText(target.location.bed as string);
  const detail = (await (await request.get(`/api/patients/${target.id}`)).json()) as { fhir_id: string; age: number };
  await expect(page.getByTestId('inspector-fhir')).toHaveText(detail.fhir_id);
  await expect(page.getByTestId('inspector-bed')).toContainText(`age ${detail.age}`);
  await expect(page.getByLabel('Live vital signs')).toContainText('HR');
  await expect(page.getByRole('img', { name: /Heart rate, 6 h/ })).toBeVisible();
  await page.screenshot({ path: `${EVIDENCE}/inspector.png` });
  await page.getByRole('button', { name: 'Fly to this bed' }).click();
  await page.waitForTimeout(1500);
  expect((await debug(page, (d) => d.view())).preset).toBeNull();
});

test('6. floor presets hide and show the right floors', async ({ page, request }) => {
  await openFrozen(page, request);
  const cases: [string, boolean[], boolean][] = [
    ['Ground floor', [true, false, false], false],
    ['Floor 2', [true, true, false], false],
    ['Floor 3', [true, true, true], false],
    ['Exploded', [true, true, true], true],
    ['Outside', [true, true, true], true],
  ];
  for (const [name, floors, roof] of cases) {
    await page.getByRole('button', { name, exact: true }).click();
    await expect.poll(() => debug(page, (d) => d.view().floorsVisible)).toEqual(floors);
    expect((await debug(page, (d) => d.view())).roofVisible).toBe(roof);
    await expect(page.getByTestId('viewing')).toContainText(name === 'Floor 2' ? 'floor2' : name === 'Floor 3' ? 'floor3' : name === 'Ground floor' ? 'ground' : name.toLowerCase());
  }
  await page.getByRole('button', { name: 'Ground floor' }).click();
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${EVIDENCE}/ground-floor-live.png` });
});

test('8. faceAudit passes for every character in the live scene', async ({ page, request }) => {
  await openFrozen(page, request);
  expect((await debug(page, (d) => d.view())).mode).toBe('free'); // the default view is the free-fly one
  await page.getByRole('button', { name: 'Night' }).click();
  const audit = await debug(page, (d) => d.faceAudit());
  expect(audit.checked).toBeGreaterThan(15);
  expect(audit.results.filter((r) => !r.audit.ok)).toEqual([]);
  expect(audit.ok).toBe(true);
});

test('moves animate along their paths: walking people change position over time', async ({ page, request }) => {
  // At 1x one real second is one sim minute, so a 20 m walk lasts a fraction of a second. A recorder inside
  // the page samples every animation frame and cannot miss it.
  await page.goto('/#/hospital/mercy');
  await page.waitForFunction(() => (window as unknown as { __TWIN_DEBUG__: TwinDebug }).__TWIN_DEBUG__.frameStats().frames > 3);
  await page.evaluate(() => {
    const w = window as unknown as { __TWIN_DEBUG__: TwinDebug; __tracks: Record<string, { x: number; z: number }[]> };
    w.__tracks = {};
    const sample = () => {
      for (const e of w.__TWIN_DEBUG__.entities()) {
        if (e.pose !== 'walking') continue;
        (w.__tracks[e.id] ??= []).push({ x: e.position.x, z: e.position.z });
      }
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });
  // A walk seen at 3 or more frames that covered more than a meter: it moved smoothly rather than jumping.
  const smooth = () =>
    page.evaluate(() => {
      const tracks = (window as unknown as { __tracks: Record<string, { x: number; z: number }[]> }).__tracks;
      return Object.values(tracks).filter((t) => {
        const meters = t.slice(1).reduce((sum, p, i) => sum + Math.hypot(p.x - (t[i]?.x ?? p.x), p.z - (t[i]?.z ?? p.z)), 0);
        return t.length >= 3 && meters > 1;
      }).length;
    });
  await expect.poll(smooth, { timeout: 90_000 }).toBeGreaterThan(0);
  await request.post('/api/sim/speed', { data: { speed: 8 } });
  await expect(page.getByTestId('feed-row').first()).toBeVisible({ timeout: 60_000 }); // arrivals, admissions, discharges
});

test('the 2D floor plan shows the same live entities and stays usable without WebGL', async ({ page, request }) => {
  const api = await openFrozen(page, request);
  await page.getByRole('button', { name: '2D plan' }).click();
  await expect(page.getByTestId('floor-plan')).toBeVisible();
  const level0 = drawn(api).length;
  expect(level0).toBeGreaterThan(5);
  await expect.poll(() => page.getByTestId('plan-dot').count()).toBeGreaterThan(0);
  await page.getByRole('tab', { name: /Floor 3/ }).click();
  const icu = api.entities.filter((e) => e.location.floor === 2 && !e.move);
  await expect.poll(() => page.getByTestId('plan-dot').count()).toBeGreaterThanOrEqual(Math.min(icu.length, 1));
  // Click a dot that nothing in the HUD is drawn over.
  const dots = page.getByTestId('plan-dot');
  let index = 0;
  for (let i = 0; i < (await dots.count()); i++) {
    const free = await dots.nth(i).evaluate((el) => {
      const r = el.getBoundingClientRect();
      return document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2) === el;
    });
    if (free) {
      index = i;
      break;
    }
  }
  const first = dots.nth(index);
  const id = (await first.getAttribute('data-entity'))!;
  await first.click();
  await expect(page.getByTestId('inspector-id')).toHaveText(id);
  await page.screenshot({ path: `${EVIDENCE}/floor-plan.png` });

  // No WebGL: the 3D view cannot start, a banner says so, and the plan still works.
  const nogl = await page.context().newPage();
  await nogl.addInitScript(() => {
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string) {
      return type === 'webgl' || type === 'webgl2' || type === 'experimental-webgl' ? null : null;
    } as never;
  });
  await nogl.goto('/#/hospital/mercy');
  await expect(nogl.getByTestId('webgl-banner')).toBeVisible({ timeout: 20_000 });
  await expect(nogl.getByTestId('floor-plan')).toBeVisible();
  await expect.poll(() => nogl.getByTestId('plan-dot').count(), { timeout: 20_000 }).toBeGreaterThan(0);
  await nogl.close();
});

test('the network map shows ambulances on the road with their patients', async ({ page, request }) => {
  await request.post('/api/sim/speed', { data: { speed: 8 } });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await expect(page.getByTestId('incoming').first()).toBeVisible({ timeout: 90_000 });
  await expect(page.getByTestId('incoming').first()).toContainText(/AMB-.* · P-\d+ → /);
  await page.screenshot({ path: `${EVIDENCE}/network-map-live.png` });
});

test('5b. live risk scores, SHAP factors, forecast and model version appear in the UI and match the API', async ({ page, request }) => {
  const api = await openFrozen(page, request);
  const scored = api.entities.filter((e) => e.kind === 'patient' && e.location.bed && !e.move && e.risk);
  expect(scored.length).toBeGreaterThan(3);
  // The alerts KPI is the number of high-risk patients.
  const high = api.entities.filter((e) => e.risk?.level === 'high').length;
  expect(api.kpis.alerts).toBe(high);
  await expect(page.getByTestId('kpis')).toContainText(`ALERTS ${high}`);
  // The risk model in use, with its validation AUROC.
  const models = (await (await request.get('/api/models')).json()) as { active_deterioration: string };
  expect(models.active_deterioration).toBe('lgbm-v1');
  await expect(page.getByTestId('model-badge')).toContainText(/Risk model lgbm-v1 · AUROC 0\.\d\d/);
  // The forecast panel shows six hours of arrivals and hours until full per unit, from /forecast.
  const forecast = (await (await request.get('/api/forecast/mercy')).json()) as { arrivals: { expected: number }[]; hours_until_full: Record<string, number | null> };
  expect(forecast.arrivals).toHaveLength(6);
  await expect(page.getByTestId('forecast-total')).toContainText(`Arrivals expected: ${forecast.arrivals.reduce((s, a) => s + a.expected, 0).toFixed(1)} in 6 h`);
  for (const unit of ['ER', 'WARD', 'ICU', 'REC']) await expect(page.getByTestId(`full-${unit}`)).toBeVisible();
  // A scored patient: the inspector shows the same score, level, model version and three factors.
  const target = [...scored].sort((a, b) => (b.risk?.score ?? 0) - (a.risk?.score ?? 0))[0]!;
  const preset = { 0: 'Ground floor', 1: 'Floor 2', 2: 'Floor 3' }[target.location.floor ?? 0] ?? 'Outside';
  await page.getByRole('button', { name: preset }).click();
  await page.waitForTimeout(1500);
  const point = await page.evaluate((id) => (window as unknown as { __TWIN_DEBUG__: TwinDebug }).__TWIN_DEBUG__.screenPoint(id), target.id);
  const box = (await page.getByTestId('scene').boundingBox())!;
  await page.mouse.click(box.x + point!.x, box.y + point!.y);
  await expect(page.getByTestId('inspector-id')).toHaveText(target.id);
  const inspector = page.getByTestId('inspector');
  await expect(inspector).toContainText((target.risk?.score ?? 0).toFixed(2));
  await expect(inspector).toContainText(`${(target.risk?.level ?? '').toUpperCase()} RISK`);
  await expect(inspector).toContainText('model lgbm-v1');
  await expect(inspector).toContainText('Why the model flagged this');
  for (const [name] of (target.risk?.top_factors ?? []) as unknown as [string, number][]) await expect(inspector).toContainText(name);
  await page.screenshot({ path: `${EVIDENCE}/risk-inspector.png` });
});

test('the view starts in free-fly: W A S D fly through the building right after the page loads, and Isometric pans', async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/?freeze=1#/hospital/mercy');
  await page.waitForFunction(() => (window as unknown as { __TWIN_DEBUG__: TwinDebug }).__TWIN_DEBUG__.frameStats().frames > 3);
  await expect.poll(async () => ((await (await request.get('/api/sim')).json()) as { frozen: boolean }).frozen, { timeout: 15_000 }).toBe(true);
  await page.waitForTimeout(800);
  expect((await debug(page, (d) => d.view())).mode).toBe('free');
  await expect(page.getByTestId('controls-hint')).toContainText('W A S D fly');
  await expect(page.getByRole('button', { name: 'Isometric camera' })).toBeVisible();
  const target = (await debug(page, (d) => d.entities())).find((e) => e.kind === 'patient')?.id ?? '';
  const where = () => page.evaluate((id) => (window as unknown as { __TWIN_DEBUG__: TwinDebug }).__TWIN_DEBUG__.screenPoint(id), target);
  const moved = (a: { x: number; y: number } | null, b: { x: number; y: number } | null) => Math.hypot((a?.x ?? 0) - (b?.x ?? 0), (a?.y ?? 0) - (b?.y ?? 0));

  // No click first: the canvas already has focus, and W flies forward.
  const before = await where();
  await page.keyboard.down('KeyW');
  await page.waitForTimeout(800);
  await page.keyboard.up('KeyW');
  await page.waitForTimeout(200);
  expect(moved(before, await where())).toBeGreaterThan(5);

  // The isometric view is one click away, and there W pans.
  await page.getByRole('button', { name: 'Isometric camera' }).click();
  await expect(page.getByTestId('controls-hint')).toContainText('W A S D pan');
  expect((await debug(page, (d) => d.view())).mode).toBe('iso');
  await page.getByTestId('scene').focus();
  const isoBefore = await where();
  await page.keyboard.down('KeyW');
  await page.waitForTimeout(600);
  await page.keyboard.up('KeyW');
  await page.waitForTimeout(200);
  expect(moved(isoBefore, await where())).toBeGreaterThan(5);
});
