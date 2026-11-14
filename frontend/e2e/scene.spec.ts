import { readFileSync, writeFileSync } from 'node:fs';

import { expect, test, type Page } from '@playwright/test';

import type { TwinDebug } from '../src/engine/debug';
import type { Engine } from '../src/engine/engine';
import type { SnapshotMessage } from '../src/state/wsTypes';

const EVIDENCE = '../docs/evidence/cp3';
const snapshot = JSON.parse(readFileSync('tests/fixtures/snapshot_mercy.json', 'utf8')) as SnapshotMessage;

type W = { __TWIN_DEBUG__: TwinDebug; __ENGINE__: Engine };

async function open(page: Page, query: string): Promise<string[]> {
  const errors: string[] = [];
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text());
  });
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto(`/tests/harness/index.html?freeze=1&${query}`);
  await page.waitForFunction(() => document.title === 'ready', undefined, { timeout: 30_000 });
  await page.waitForFunction(() => (window as unknown as W).__TWIN_DEBUG__.frameStats().frames > 4);
  // Let the eased floors and camera settle so screenshots are stable.
  await page.waitForTimeout(300);
  return errors;
}

const debug = <T>(page: Page, fn: (d: TwinDebug) => T): Promise<T> => page.evaluate<T>(`(${fn.toString()})(window.__TWIN_DEBUG__)`);

test('renders without console errors and reports frame stats', async ({ page }) => {
  const errors = await open(page, 'preset=outside');
  expect(errors).toEqual([]);
  const stats = await debug(page, (d) => d.frameStats());
  expect(stats.frames).toBeGreaterThan(4);
  expect(stats.drawCalls).toBeGreaterThan(50);
  expect(await debug(page, (d) => d.problems())).toEqual([]);
});

test('the pixel factor defaults to 2: the canvas is half size and upscaled with pixelated rendering', async ({ page }) => {
  await open(page, 'preset=outside');
  const info = await page.evaluate(() => {
    const c = document.getElementById('scene') as HTMLCanvasElement;
    return { w: c.width, h: c.height, css: getComputedStyle(c).imageRendering, factor: (window as unknown as W).__TWIN_DEBUG__.view().pixelFactor };
  });
  expect(info).toEqual({ w: 640, h: 372, css: 'pixelated', factor: 2 });
  await page.evaluate(() => (window as unknown as W).__ENGINE__.setPixelFactor(4));
  expect(await page.evaluate(() => (document.getElementById('scene') as HTMLCanvasElement).width)).toBe(320);
  expect(await page.evaluate(() => (window as unknown as W).__ENGINE__.cameraState().mode)).toBe('iso');
});

test('counts() equals the snapshot, beds() has a lying patient in every occupied bed', async ({ page }) => {
  await open(page, 'preset=floor2');
  const counts = await debug(page, (d) => d.counts());
  const simNow = Date.parse(snapshot.sim_time);
  const expected: Record<string, number> = {};
  for (const e of snapshot.entities) if (e.location.floor !== null && !e.location.vehicle) expected[e.kind] = (expected[e.kind] ?? 0) + 1;
  expect(counts).toEqual(expected);
  const beds = await debug(page, (d) => d.beds());
  const inBed = snapshot.entities.filter((e) => e.location.bed && !(e.move && Date.parse(e.move.arrive) > simNow));
  expect(Object.keys(beds)).toHaveLength(inBed.length);
  for (const e of inBed) expect(beds[e.location.bed as string]).toBe(e.id);
  for (const b of snapshot.beds.filter((x) => x.state === 'occupied' && x.patient_id)) {
    const walking = snapshot.entities.find((e) => e.id === b.patient_id)?.move;
    if (!walking) expect(beds[b.id]).toBe(b.patient_id);
  }
  const rendered = await debug(page, (d) => d.entities());
  expect(rendered.filter((r) => r.mode === 'bed').every((r) => r.bed !== null && r.pose === 'lying')).toBe(true);
});

test('faceAudit passes for every character in the scene', async ({ page }) => {
  for (const q of ['preset=outside', 'preset=outside&cam=free', 'preset=outside&night=1']) {
    await open(page, q);
    const audit = await debug(page, (d) => d.faceAudit());
    expect(audit.checked).toBeGreaterThan(40);
    expect(audit.results.filter((r) => !r.audit.ok)).toEqual([]);
    expect(audit.ok).toBe(true);
  }
});

test('X-ray: markers become visible and shell opacity changes; the legend state is reported', async ({ page }) => {
  await open(page, 'preset=outside');
  const before = await debug(page, (d) => d.xray());
  expect(before).toMatchObject({ on: false, wallOpacity: 1, floorOpacity: 1, markersVisible: 0 });
  await page.evaluate(() => (window as unknown as W).__ENGINE__.setXray(true));
  await page.waitForFunction(() => (window as unknown as W).__TWIN_DEBUG__.view().floorY[1]! > 6.8, undefined, { timeout: 10_000 });
  const after = await debug(page, (d) => d.xray());
  expect(after.on).toBe(true);
  expect(after.wallOpacity).toBe(0.07);
  expect(after.floorOpacity).toBe(0.55);
  expect(after.markersVisible).toBeGreaterThan(40);
  const y = await debug(page, (d) => d.view().floorY);
  expect(y[1]).toBeGreaterThan(6.8); // floors spread apart (target 6.9 m) when viewing everything
  await page.evaluate(() => (window as unknown as W).__ENGINE__.setXray(false));
  expect(await debug(page, (d) => d.xray())).toMatchObject({ on: false, wallOpacity: 1, markersVisible: 0 });
});

test('floor presets hide and show the right floors', async ({ page }) => {
  await open(page, 'preset=outside');
  const expectations: [string, boolean[], boolean][] = [
    ['outside', [true, true, true], true],
    ['ground', [true, false, false], false],
    ['floor2', [true, true, false], false],
    ['floor3', [true, true, true], false],
    ['exploded', [true, true, true], true],
    ['helipad', [true, true, true], true],
    ['front_door', [true, false, false], false],
    ['side', [true, true, false], false],
    ['icu', [true, true, true], false],
  ];
  for (const [id, floors, roof] of expectations) {
    await page.evaluate((p) => (window as unknown as W).__ENGINE__.preset(p, false), id);
    const v = await debug(page, (d) => d.view());
    expect(v.floorsVisible, id).toEqual(floors);
    expect(v.roofVisible, id).toBe(roof);
    expect(v.preset).toBe(id);
  }
  await page.evaluate(() => (window as unknown as W).__ENGINE__.preset('exploded', false));
  await page.waitForTimeout(500);
  const y = await debug(page, (d) => d.view().floorY);
  expect(y[1]! - y[0]!).toBeCloseTo(9.4, 1); // 3.4 m floor + 6 m gap
});

test('clicking a patient in ICU-3 selects them (same id as the snapshot)', async ({ page }) => {
  await open(page, 'preset=icu');
  const patient = snapshot.entities.find((e) => e.location.bed === 'ICU-3')!;
  const pt = await page.evaluate((id) => (window as unknown as W).__ENGINE__.screenPoint(id), patient.id);
  expect(pt).not.toBeNull();
  await page.mouse.click(pt!.x, pt!.y);
  expect(await debug(page, (d) => d.selected())).toBe(patient.id);
  // a drag is not a click
  await page.mouse.move(100, 100);
  await page.mouse.down();
  await page.mouse.move(160, 120);
  await page.mouse.up();
  expect(await debug(page, (d) => d.selected())).toBe(patient.id);
});

test('keyboard and mouse control the camera from the canvas (not the window)', async ({ page }) => {
  await open(page, 'preset=outside');
  const get = () => page.evaluate(() => (window as unknown as W).__ENGINE__.cameraState().state);
  const s0 = await get();
  await page.evaluate(() => document.getElementById('scene')?.focus());
  await page.keyboard.down('KeyW');
  await page.waitForTimeout(400);
  await page.keyboard.up('KeyW');
  const s1 = await get();
  expect(Math.hypot((s1['tx'] ?? 0) - (s0['tx'] ?? 0), (s1['tz'] ?? 0) - (s0['tz'] ?? 0))).toBeGreaterThan(0.5);
  await page.mouse.move(400, 300);
  await page.mouse.down();
  await page.mouse.move(520, 300);
  await page.mouse.up();
  expect((await get())['az']).not.toBe(s1['az']);
  await page.mouse.move(640, 372);
  await page.mouse.wheel(0, -300);
  await page.waitForTimeout(100);
  expect((await get())['zoom']).toBeGreaterThan(1);
  // keys pressed while the canvas is not focused do nothing
  await page.evaluate(() => (document.getElementById('scene') as HTMLCanvasElement).blur());
  const s2 = await get();
  await page.keyboard.down('KeyD');
  await page.waitForTimeout(300);
  await page.keyboard.up('KeyD');
  expect((await get())['tx']).toBe(s2['tx']);
});

test('free-fly camera, night mode and the pixel factor switch without errors', async ({ page }) => {
  const errors = await open(page, 'preset=outside');
  await page.evaluate(() => (window as unknown as W).__ENGINE__.setCameraMode('free'));
  expect(await debug(page, (d) => d.view().mode)).toBe('free');
  await page.evaluate(() => (window as unknown as W).__ENGINE__.setNight(true));
  expect(await debug(page, (d) => d.view().night)).toBe(true);
  await page.evaluate(() => (window as unknown as W).__ENGINE__.setNight(false));
  await page.evaluate(() => (window as unknown as W).__ENGINE__.setCameraMode('iso'));
  expect(await debug(page, (d) => d.view())).toMatchObject({ mode: 'iso', night: false });
  await page.waitForTimeout(200);
  expect(errors).toEqual([]);
  expect(await debug(page, (d) => d.counts())).toBeTruthy();
});

test('night mode keeps X-ray and the view', async ({ page }) => {
  await open(page, 'preset=ground&xray=1&night=1');
  const x = await debug(page, (d) => d.xray());
  expect(x.on).toBe(true);
  expect((await debug(page, (d) => d.view())).night).toBe(true);
});

const SHOTS: { file: string; ref: string; query: string }[] = [
  { file: '01-outside', ref: '01-outside', query: 'cam=free&preset=outside' },
  { file: '02-ground-floor-cutaway', ref: '02-ground-floor-cutaway', query: 'cam=free&preset=ground' },
  { file: '03-floor3-icu-cutaway', ref: '03-floor3-icu-cutaway', query: 'cam=free&preset=floor3' },
  { file: '04-exploded', ref: '04-exploded', query: 'cam=free&preset=exploded' },
  { file: '05-xray-whole-hospital', ref: '05-xray-whole-hospital', query: 'cam=free&preset=outside&xray=1' },
  { file: '06-xray-icu-closeup', ref: '06-xray-icu-closeup', query: 'cam=free&preset=icu&xray=1' },
  { file: '07-xray-isometric', ref: '07-xray-isometric', query: 'preset=outside&xray=1' },
  { file: '08-xray-night-side', ref: '08-xray-night-side', query: 'preset=side&xray=1&night=1' },
  { file: '09-isometric', ref: '09-isometric', query: 'preset=outside' },
  { file: '10-night', ref: '10-night', query: 'cam=free&preset=outside&night=1' },
  { file: '11-isometric-floor2-default-view', ref: '11-isometric-floor2-default-view', query: 'preset=floor2' },
  { file: '12-freefly-floor2', ref: '12-freefly-floor2', query: 'cam=free&preset=floor2' },
];

test('parity screenshots next to the reference renders', async ({ page }) => {
  test.setTimeout(180_000);
  for (const s of SHOTS) {
    const errors = await open(page, s.query);
    expect(errors, s.file).toEqual([]);
    await page.screenshot({ path: `${EVIDENCE}/parity/${s.file}.png` });
    const ours = readFileSync(`${EVIDENCE}/parity/${s.file}.png`).toString('base64');
    const ref = readFileSync(`../reference/screens/${s.ref}.png`).toString('base64');
    await page.setViewportSize({ width: 2580, height: 780 });
    await page.setContent(
      `<body style="margin:0;background:#20324a;font:20px monospace;color:#fff"><div style="display:flex;gap:10px;padding:10px">` +
        `<div>reference<br><img style="width:1280px" src="data:image/png;base64,${ref}"></div>` +
        `<div>port<br><img style="width:1280px" src="data:image/png;base64,${ours}"></div></div></body>`,
    );
    await page.screenshot({ path: `${EVIDENCE}/parity/side-by-side-${s.file}.png` });
    await page.setViewportSize({ width: 1280, height: 720 });
  }
});

test('evidence screenshots: Outside, Ground floor, X-ray ICU close-up (frozen)', async ({ page }) => {
  for (const [name, q] of [
    ['outside', 'preset=outside'],
    ['ground-floor', 'preset=ground'],
    ['xray-icu-closeup', 'preset=icu&xray=1'],
  ] as const) {
    await open(page, q);
    await page.screenshot({ path: `${EVIDENCE}/${name}.png` });
  }
  writeFileSync(`${EVIDENCE}/README.txt`, 'Screenshots rendered from tests/fixtures/snapshot_mercy.json with ?freeze=1.\n');
});
