/**
 * Interior wall segments derived from the layout's rooms and door gaps. The same rule produces the walls the
 * prototype hardcodes per floor: room edges are merged where rooms touch, edges on the outer footprint are
 * left to the exterior walls with window bands, edges on the elevator shaft are left to its glass, and door
 * gaps are cut out.
 */
import type { Floor, Layout, Rect } from './layout';

export interface WallSegment {
  /** 'x': the wall runs along x at z = `at`; 'z': it runs along z at x = `at`. */
  axis: 'x' | 'z';
  at: number;
  lo: number;
  hi: number;
}

const EPS = 1e-6;

function edgesOf(r: Rect): WallSegment[] {
  return [
    { axis: 'x', at: r.z1, lo: r.x1, hi: r.x2 },
    { axis: 'x', at: r.z2, lo: r.x1, hi: r.x2 },
    { axis: 'z', at: r.x1, lo: r.z1, hi: r.z2 },
    { axis: 'z', at: r.x2, lo: r.z1, hi: r.z2 },
  ];
}

function union(intervals: [number, number][]): [number, number][] {
  const sorted = [...intervals].sort((a, b) => a[0] - b[0]);
  const out: [number, number][] = [];
  for (const [lo, hi] of sorted) {
    const last = out[out.length - 1];
    if (last && lo <= last[1] + EPS) last[1] = Math.max(last[1], hi);
    else out.push([lo, hi]);
  }
  return out;
}

function subtract(intervals: [number, number][], gaps: [number, number][]): [number, number][] {
  let current = intervals;
  for (const [g0, g1] of gaps) {
    const next: [number, number][] = [];
    for (const [lo, hi] of current) {
      if (g1 <= lo + EPS || g0 >= hi - EPS) next.push([lo, hi]);
      else {
        if (g0 > lo + EPS) next.push([lo, g0]);
        if (g1 < hi - EPS) next.push([g1, hi]);
      }
    }
    current = next;
  }
  return current;
}

/** Interior walls of one floor. */
export function interiorWalls(layout: Layout, floor: Floor): WallSegment[] {
  const fp = layout.building.footprint;
  const elevator = layout.building.elevator;
  const byLine = new Map<string, { axis: 'x' | 'z'; at: number; spans: [number, number][] }>();
  for (const room of floor.rooms) {
    if (room.kind !== 'room' && room.kind !== 'corridor') continue;
    for (const e of edgesOf(room.rect)) {
      const outer = e.axis === 'x' ? Math.abs(e.at - fp.z1) < EPS || Math.abs(e.at - fp.z2) < EPS : Math.abs(e.at - fp.x1) < EPS || Math.abs(e.at - fp.x2) < EPS;
      if (outer) continue;
      // The end of the corridor and the elevator shaft: the shaft has its own glass.
      if (e.axis === 'z' && Math.abs(e.at - elevator.x1) < EPS && room.kind === 'corridor') continue;
      const key = `${e.axis}|${e.at}`;
      const line = byLine.get(key) ?? { axis: e.axis, at: e.at, spans: [] };
      line.spans.push([e.lo, e.hi]);
      byLine.set(key, line);
    }
  }
  const out: WallSegment[] = [];
  for (const line of byLine.values()) {
    let spans = union(line.spans);
    if (line.axis === 'x') {
      // No wall between the upper rooms and the elevator shaft, as in the prototype.
      spans = spans.map(([lo, hi]): [number, number] => [lo, Math.min(hi, elevator.x1)]).filter(([lo, hi]) => hi - lo > EPS);
    }
    const gaps = floor.doors
      .filter((d) => d.axis === line.axis && Math.abs(d.at - line.at) < EPS)
      .map((d): [number, number] => [d.start, d.end]);
    for (const [lo, hi] of subtract(spans, gaps)) out.push({ axis: line.axis, at: line.at, lo, hi });
  }
  return out.sort((a, b) => (a.axis === b.axis ? a.at - b.at || a.lo - b.lo : a.axis < b.axis ? -1 : 1));
}

/** Pieces of an exterior wall after the entrance gap (the ground-floor south wall) is cut out. */
export function exteriorSpans(layout: Layout, floor: Floor, side: 'south' | 'north' | 'east' | 'west'): [number, number][] {
  const fp = layout.building.footprint;
  const ext = 0.4;
  const full: [number, number] = side === 'south' || side === 'north' ? [fp.x1 - ext, fp.x2 + ext] : [fp.z1, fp.z2];
  if (side !== 'south') return [full];
  const gaps = floor.doors.filter((d) => d.kind === 'entrance').map((d): [number, number] => [d.start, d.end]);
  return subtract([full], gaps);
}
