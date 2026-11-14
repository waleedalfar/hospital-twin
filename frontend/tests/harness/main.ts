// Test-only page: renders the 3D scene from a recorded snapshot fixture (PROMPT.md §14, CP3). The product
// app never loads this page or the fixture. Query: fixture, freeze=1, preset, cam=iso|free, night=1,
// xray=1, pixel=1..4, select=<entity id>.
import { Engine } from '../../src/engine/engine';
import type { CameraMode } from '../../src/engine/camera';
import type { SnapshotMessage } from '../../src/state/wsTypes';

const q = new URLSearchParams(location.search);
const canvas = document.getElementById('scene') as HTMLCanvasElement;

async function main(): Promise<void> {
  const res = await fetch(`/tests/fixtures/${q.get('fixture') ?? 'snapshot_mercy'}.json`);
  if (!res.ok) throw new Error(`Fixture not found: HTTP ${res.status}`);
  const snap = (await res.json()) as SnapshotMessage;
  const simMs = Date.parse(snap.sim_time);
  const engine = new Engine({
    canvas,
    hospitalName: snap.hospital.name,
    cameraMode: (q.get('cam') as CameraMode | null) ?? 'iso',
    night: q.get('night') === '1',
    pixelFactor: Number(q.get('pixel') ?? 2),
    frozen: q.get('freeze') === '1',
    simClock: () => simMs,
  });
  engine.setEntities(snap.entities);
  if (q.get('xray') === '1') engine.setXray(true);
  const preset = q.get('preset');
  if (preset) engine.preset(preset, false);
  const sel = q.get('select');
  if (sel) engine.select(sel);
  (window as unknown as { __ENGINE__: Engine }).__ENGINE__ = engine;
  document.title = 'ready';
}

main().catch((e: unknown) => {
  console.error('Harness failed', e);
  document.title = 'error';
});
