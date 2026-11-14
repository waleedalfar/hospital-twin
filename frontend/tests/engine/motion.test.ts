import { describe, expect, it } from 'vitest';

import { LAYOUT, LayoutIndex } from '../../src/engine/layout';
import { parseTimes, positionAt } from '../../src/engine/motion';

const idx = new LayoutIndex(LAYOUT);
const A = 'f2-ICU-door-1';
const B = 'f2-c-1';

describe('positionAt', () => {
  const a = idx.nodes.get(A)!;
  const b = idx.nodes.get(B)!;

  it('stays at the first node before departure and at the last after arrival', () => {
    expect(positionAt(idx, [A, B], [100, 200], 50)).toMatchObject({ x: a.x, z: a.z, moving: false });
    expect(positionAt(idx, [A, B], [100, 200], 500)).toMatchObject({ x: b.x, z: b.z, moving: false });
  });

  it('interpolates in a straight line and faces the direction of travel', () => {
    const p = positionAt(idx, [A, B], [100, 200], 150);
    expect(p.x).toBeCloseTo((a.x + b.x) / 2);
    expect(p.z).toBeCloseTo((a.z + b.z) / 2);
    expect(p.moving).toBe(true);
    expect(p.yaw).toBeCloseTo(Math.atan2(b.x - a.x, b.z - a.z));
    expect(p.level).toBe(2);
  });

  it('follows several segments', () => {
    const path = [A, B, 'f2-c-2'];
    const p = positionAt(idx, path, [0, 10, 30], 20);
    const mid = idx.nodes.get('f2-c-2')!;
    expect(p.x).toBeCloseTo((b.x + mid.x) / 2);
  });

  it('rides the elevator: fixed x/z, fractional level, not walking', () => {
    const p = positionAt(idx, ['f0-ELEV', 'f2-ELEV'], [0, 20], 10);
    expect(p.riding).toBe(true);
    expect(p.moving).toBe(false);
    expect(p.level).toBeCloseTo(1);
    expect(p.x).toBe(18.5);
    expect(p.z).toBe(0);
  });

  it('waits at a node repeated with later times (a busy elevator) and keeps facing the way it came', () => {
    const path = [A, B, B, 'f2-c-2'];
    const p = positionAt(idx, path, [0, 10, 30, 40], 20);
    expect(p.x).toBeCloseTo(b.x);
    expect(p.moving).toBe(false);
    expect(p.yaw).toBeCloseTo(Math.atan2(b.x - a.x, b.z - a.z));
  });

  it('handles a single-node path and zero-length times', () => {
    expect(positionAt(idx, [A], [0], 5).x).toBe(a.x);
    expect(positionAt(idx, [A, B], [10, 10], 10).x).toBe(a.x);
  });

  it('rejects bad input loudly', () => {
    expect(() => positionAt(idx, [], [], 0)).toThrow('needs a path');
    expect(() => positionAt(idx, [A], [0, 1], 0)).toThrow('needs a path');
    expect(() => positionAt(idx, ['nope', B], [0, 1], 0.5)).toThrow('Unknown waypoint');
    expect(() => parseTimes(['not a time'])).toThrow('Bad time');
    expect(parseTimes(['2026-11-14T15:00:00Z'])).toEqual([Date.parse('2026-11-14T15:00:00Z')]);
  });
});
