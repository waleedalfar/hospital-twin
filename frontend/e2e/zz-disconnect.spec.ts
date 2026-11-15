/**
 * PROMPT.md §11 test 10. It kills and restarts the backend, so it lives in its own file named to run after
 * every other spec (Playwright runs files in alphabetical order, one worker).
 */
import { execSync, spawn } from 'node:child_process';

import { expect, test } from '@playwright/test';

import type { TwinDebug } from '../src/engine/debug';
import type { SnapshotMessage } from '../src/state/wsTypes';

const EVIDENCE = '../docs/evidence/cp4';
const debug = <T>(page: import('@playwright/test').Page, fn: (d: TwinDebug) => T): Promise<T> => page.evaluate<T>(`(${fn.toString()})(window.__TWIN_DEBUG__)`);

function drawn(s: SnapshotMessage): SnapshotMessage['entities'] {
  return s.entities.filter((e) => e.location.floor !== null && (!e.location.vehicle || e.move));
}

async function state(request: import('@playwright/test').APIRequestContext): Promise<SnapshotMessage> {
  return (await (await request.get('/api/hospitals/mercy/state')).json()) as SnapshotMessage;
}

test('10. killing the backend shows the Disconnected banner; restarting resyncs from a fresh snapshot', async ({ page, request }) => {
  test.setTimeout(120_000);
  await page.goto('/#/hospital/mercy');
  await page.waitForFunction(() => Object.keys((window as unknown as { __TWIN_DEBUG__: TwinDebug }).__TWIN_DEBUG__.counts()).length > 0, undefined, { timeout: 20_000 });
  await expect(page.getByTestId('disconnected-banner')).toHaveCount(0);
  const pids = execSync('lsof -ti tcp:8000 -sTCP:LISTEN || true').toString().split('\n').filter(Boolean);
  expect(pids.length).toBeGreaterThan(0);
  for (const pid of pids) process.kill(Number(pid), 'SIGTERM');
  await expect(page.getByTestId('disconnected-banner')).toBeVisible({ timeout: 15_000 });
  await page.screenshot({ path: `${EVIDENCE}/disconnected.png` });
  const server = spawn('uv', ['run', '--directory', '../backend', 'uvicorn', 'twin.api.main:app', '--host', '127.0.0.1', '--port', '8000'], {
    env: { ...process.env, VIRTUAL_ENV: '' },
    stdio: 'ignore',
    detached: true,
  });
  server.unref();
  try {
    await expect(page.getByTestId('disconnected-banner')).toHaveCount(0, { timeout: 60_000 });
    const api = await state(request);
    const expected: Record<string, number> = {};
    for (const e of drawn(api)) expected[e.kind] = (expected[e.kind] ?? 0) + 1;
    await request.post('/api/sim/pause', { data: { paused: true } });
    await page.waitForTimeout(1500);
    const fresh = await state(request);
    const want: Record<string, number> = {};
    for (const e of drawn(fresh)) want[e.kind] = (want[e.kind] ?? 0) + 1;
    await expect.poll(() => debug(page, (d) => d.counts()), { timeout: 15_000 }).toEqual(want);
    expect(Object.keys(want).length).toBeGreaterThan(0);
    expect(expected).toBeTruthy();
  } finally {
    // Do not leave the server this test started running after the suite.
    await request.post('/api/sim/pause', { data: { paused: false } }).catch(() => undefined);
    if (server.pid !== undefined) {
      try {
        process.kill(-server.pid, 'SIGTERM');
      } catch (error) {
        console.warn('Could not stop the restarted backend', error);
      }
    }
  }
});

