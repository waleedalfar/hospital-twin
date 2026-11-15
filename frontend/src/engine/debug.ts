/**
 * `window.__TWIN_DEBUG__` (PROMPT.md §10.6): a read-only view of what the scene contains, so tests can assert
 * on scene contents and not only on pixels. It is always present; before an engine exists it reports an
 * empty scene.
 */
import type { FaceAudit } from './characters';
import type { RenderedEntity } from './entities';

export interface FrameStats {
  frames: number;
  fps: number;
  lastFrameMs: number;
  drawCalls: number;
  triangles: number;
}

export interface ViewInfo {
  mode: 'iso' | 'free';
  view: 'all' | number;
  exploded: boolean;
  night: boolean;
  pixelFactor: number;
  preset: string | null;
  floorsVisible: boolean[];
  roofVisible: boolean;
  floorY: number[];
}

export interface TwinDebug {
  entities(): RenderedEntity[];
  counts(): Record<string, number>;
  beds(): Record<string, string>;
  view(): ViewInfo;
  xray(): { on: boolean; wallOpacity: number; floorOpacity: number; markersVisible: number };
  selected(): string | null;
  /** The entities highlighted by an answer, and how many rings are drawn. */
  highlighted(): { ids: string[]; drawn: number };
  faceAudit(): { ok: boolean; checked: number; results: { id: string; audit: FaceAudit }[] };
  frameStats(): FrameStats;
  problems(): string[];
  vehicles(): { id: string; x: number; z: number }[];
  /** Where an entity is on the canvas in CSS pixels (so tests can click it), or null. */
  screenPoint(id: string): { x: number; y: number } | null;
}

declare global {
  interface Window {
    __TWIN_DEBUG__: TwinDebug;
  }
}

const EMPTY: TwinDebug = {
  entities: () => [],
  counts: () => ({}),
  beds: () => ({}),
  view: () => ({ mode: 'iso', view: 'all', exploded: false, night: false, pixelFactor: 2, preset: null, floorsVisible: [], roofVisible: false, floorY: [] }),
  xray: () => ({ on: false, wallOpacity: 1, floorOpacity: 1, markersVisible: 0 }),
  selected: () => null,
  highlighted: () => ({ ids: [], drawn: 0 }),
  faceAudit: () => ({ ok: true, checked: 0, results: [] }),
  frameStats: () => ({ frames: 0, fps: 0, lastFrameMs: 0, drawCalls: 0, triangles: 0 }),
  problems: () => [],
  vehicles: () => [],
  screenPoint: () => null,
};

/** Install the debug object on `window`. A frozen copy is exposed, so tests cannot change the scene through it. */
export function installDebug(source: TwinDebug = EMPTY): void {
  window.__TWIN_DEBUG__ = Object.freeze({ ...source });
}

export function countsOf(entities: readonly RenderedEntity[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const e of entities) out[e.kind] = (out[e.kind] ?? 0) + 1;
  return out;
}
