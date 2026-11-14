/**
 * Position of a walker at a given time along a server-provided path (PROMPT.md §10.6). The path is a list
 * of waypoint ids with the time the walker reaches each one; between two waypoints on one floor the walker
 * moves in a straight line, between two floors (the elevator) the car's x/z is fixed and the height changes.
 * Two equal waypoints with different times mean the walker waits there.
 */
import type { LayoutIndex } from './layout';

export interface WorldPose {
  x: number;
  z: number;
  /** Floor level; fractional while riding the elevator between floors. */
  level: number;
  /** Facing, radians about y (0 faces +z). */
  yaw: number;
  moving: boolean;
  riding: boolean;
}

export function positionAt(idx: LayoutIndex, path: readonly string[], times: readonly number[], t: number, fallbackYaw = 0): WorldPose {
  if (path.length === 0 || path.length !== times.length) throw new Error('A move needs a path and one time per waypoint');
  const node = (i: number) => {
    const id = path[i] as string;
    const n = idx.nodes.get(id);
    if (!n) throw new Error(`Unknown waypoint ${id}`);
    return n;
  };
  const first = node(0);
  if (t <= (times[0] as number) || path.length === 1) {
    return { x: first.x, z: first.z, level: first.floor, yaw: headingAt(idx, path, 0, fallbackYaw), moving: false, riding: false };
  }
  const last = node(path.length - 1);
  if (t >= (times[times.length - 1] as number)) {
    return { x: last.x, z: last.z, level: last.floor, yaw: headingAt(idx, path, path.length - 2, fallbackYaw), moving: false, riding: false };
  }
  for (let i = 0; i < path.length - 1; i++) {
    const ta = times[i] as number;
    const tb = times[i + 1] as number;
    if (t < ta || t > tb) continue;
    const a = node(i);
    const b = node(i + 1);
    const f = tb > ta ? (t - ta) / (tb - ta) : 1;
    if (a.floor !== b.floor) {
      return { x: a.x, z: a.z, level: a.floor + (b.floor - a.floor) * f, yaw: fallbackYaw, moving: false, riding: true };
    }
    const dx = b.x - a.x;
    const dz = b.z - a.z;
    const still = dx === 0 && dz === 0;
    return {
      x: a.x + dx * f,
      z: a.z + dz * f,
      level: a.floor,
      yaw: still ? headingAt(idx, path, i, fallbackYaw) : Math.atan2(dx, dz),
      moving: !still,
      riding: false,
    };
  }
  return { x: last.x, z: last.z, level: last.floor, yaw: fallbackYaw, moving: false, riding: false };
}

/** Heading of the last real segment at or before index `i` (so a waiting walker keeps facing the way they came). */
function headingAt(idx: LayoutIndex, path: readonly string[], i: number, fallback: number): number {
  for (let k = Math.min(i, path.length - 2); k >= 0; k--) {
    const a = idx.nodes.get(path[k] as string);
    const b = idx.nodes.get(path[k + 1] as string);
    if (a && b && a.floor === b.floor && (a.x !== b.x || a.z !== b.z)) return Math.atan2(b.x - a.x, b.z - a.z);
  }
  return fallback;
}

/** Parse ISO times to epoch milliseconds, failing loudly on a bad value. */
export function parseTimes(times: readonly string[]): number[] {
  return times.map((s) => {
    const ms = Date.parse(s);
    if (Number.isNaN(ms)) throw new Error(`Bad time ${s}`);
    return ms;
  });
}
