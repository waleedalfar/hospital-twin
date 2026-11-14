import { describe, expect, it } from 'vitest';

import { LAYOUT } from '../../src/engine/layout';
import { exteriorSpans, interiorWalls, type WallSegment } from '../../src/engine/walls';

type Seg = [axis: 'x' | 'z', at: number, lo: number, hi: number];

const order = (a: Seg, b: Seg): number => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] - b[1] || a[2] - b[2]);

function norm(walls: WallSegment[]): Seg[] {
  return walls.map((w): Seg => [w.axis, w.at, w.lo, w.hi]).sort(order);
}

/** Typed from reference/engine/pulse3d.js: common(floor, northDoors, southDoors, northParts, southParts). */
function expectedWalls(northDoors: [number, number][], southDoors: [number, number][], nParts: number[], sParts: (number | [number, number, number])[]): Seg[] {
  const segs = (gaps: [number, number][]): [number, number][] => {
    const out: [number, number][] = [];
    let cur = -20;
    for (const [a, b] of gaps) {
      if (a > cur) out.push([cur, a]);
      cur = b;
    }
    if (cur < 17) out.push([cur, 17]);
    return out;
  };
  const out: Seg[] = [];
  segs(northDoors).forEach(([a, b]) => out.push(['x', -2, a, b]));
  segs(southDoors).forEach(([a, b]) => out.push(['x', 2, a, b]));
  nParts.forEach((x) => out.push(['z', x, -14, -2]));
  sParts.forEach((p) => (typeof p === 'number' ? out.push(['z', p, 2, 14]) : out.push(['z', p[0], p[1], p[2]])));
  return out.sort(order);
}

const floor = (i: number) => {
  const f = LAYOUT.floors[i];
  if (!f) throw new Error('missing floor');
  return f;
};

describe('interior walls derived from the layout equal the prototype walls', () => {
  it('floor 0 (ground)', () => {
    const want = expectedWalls([[-13, -10], [0, 3], [12, 14.5]], [[-13, -10], [-2, 4], [10, 13]], [-4, 8], [-4, [8, 2, 5], [8, 9, 14]]);
    expect(norm(interiorWalls(LAYOUT, floor(0)))).toEqual(want);
  });
  it('floor 1 (wards)', () => {
    const want = expectedWalls([[-14, -11], [-1, 2], [10, 13]], [[-14, -11], [-1, 2], [10, 13]], [6], [6]);
    expect(norm(interiorWalls(LAYOUT, floor(1)))).toEqual(want);
  });
  it('floor 2 (ICU and support)', () => {
    const want = expectedWalls([[-14, -11], [-1, 2], [10, 13]], [[-13, -10], [0, 3], [10, 13]], [6], [-4, 6]);
    expect(norm(interiorWalls(LAYOUT, floor(2)))).toEqual(want);
  });
  it('the roof has no interior walls', () => {
    expect(interiorWalls(LAYOUT, floor(3))).toEqual([]);
  });
});

describe('exterior walls', () => {
  it('only the ground-floor south wall has the entrance gap (x 12..16)', () => {
    expect(exteriorSpans(LAYOUT, floor(0), 'south')).toEqual([[-20.4, 12], [16, 20.4]]);
    expect(exteriorSpans(LAYOUT, floor(1), 'south')).toEqual([[-20.4, 20.4]]);
    expect(exteriorSpans(LAYOUT, floor(0), 'north')).toEqual([[-20.4, 20.4]]);
    expect(exteriorSpans(LAYOUT, floor(0), 'east')).toEqual([[-14, 14]]);
  });
});
