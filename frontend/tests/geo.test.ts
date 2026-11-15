import { describe, expect, it } from 'vitest';

import { makeGrid, minutesLeft, percent, poseOnRoute, statusWord, STATUS_COLORS } from '../src/ui/network/geo';
import { parseRoute, routeHash, isFreeze } from '../src/ui/route';

const HOSPITALS = [
  { lat: 33.4484, lon: -112.074 },
  { lat: 33.5106, lon: -112.0296 },
  { lat: 33.3942, lon: -112.1513 },
];

describe('network geometry', () => {
  const grid = makeGrid(HOSPITALS);
  it('puts north up and fills the map inside a margin', () => {
    const stlukes = grid.toXY(33.5106, -112.0296);
    const desert = grid.toXY(33.3942, -112.1513);
    expect(stlukes.y).toBeLessThan(desert.y);
    expect(stlukes.x).toBeGreaterThan(desert.x);
    expect(desert.x).toBeGreaterThan(100);
    expect(stlukes.x).toBeLessThan(820);
  });
  it('has one street through each hospital latitude and longitude', () => {
    expect(grid.streetsY).toHaveLength(3);
    expect(grid.streetsX).toHaveLength(3);
    expect(grid.streetsY).toContain(grid.toXY(33.4484, -112.074).y);
    expect(grid.streetsX).toContain(grid.toXY(33.4484, -112.074).x);
  });
  it('handles a single point', () => {
    const g = makeGrid([{ lat: 1, lon: 2 }]);
    expect(Number.isFinite(g.toXY(1, 2).x)).toBe(true);
  });
});

describe('vehicle poses', () => {
  const route = [
    { lat: 33.4, lon: -112.1, t: '2026-11-14T15:00:00Z' },
    { lat: 33.4, lon: -112.0, t: '2026-11-14T15:10:00Z' },
    { lat: 33.5, lon: -112.0, t: '2026-11-14T15:20:00Z' },
  ];
  const at = (m: number) => Date.parse('2026-11-14T15:00:00Z') + m * 60_000;
  it('interpolates along the route and reports the heading', () => {
    const p = poseOnRoute(route, at(5), { lat: 0, lon: 0 });
    expect(p.lon).toBeCloseTo(-112.05);
    expect(p.heading).toBeCloseTo(0); // east
    const q = poseOnRoute(route, at(15), { lat: 0, lon: 0 });
    expect(q.lat).toBeCloseTo(33.45);
    expect(q.heading).toBeCloseTo(-Math.PI / 2); // north is up the screen
  });
  it('waits at the ends and falls back without a route', () => {
    expect(poseOnRoute(route, at(-5), { lat: 0, lon: 0 })).toMatchObject({ lat: 33.4, lon: -112.1, heading: null });
    expect(poseOnRoute(route, at(50), { lat: 0, lon: 0 })).toMatchObject({ lat: 33.5, lon: -112 });
    expect(poseOnRoute([], at(0), { lat: 7, lon: 8 })).toEqual({ lat: 7, lon: 8, heading: null });
    expect(minutesLeft(route, at(5))).toBe(15);
    expect(minutesLeft(route, at(99))).toBe(0);
    expect(minutesLeft([], 0)).toBeNull();
  });
});

describe('status words', () => {
  it('say OFFLINE, CRITICAL, BUSY or OK in text', () => {
    expect(statusWord('offline', 0, 29)).toBe('OFFLINE');
    expect(statusWord('open', 27, 29)).toBe('CRITICAL');
    expect(statusWord('diverting', 21, 29)).toBe('BUSY');
    expect(statusWord('open', 5, 29)).toBe('OK');
    expect(statusWord('open', 0, 0)).toBe('OK');
    expect(Object.keys(STATUS_COLORS)).toHaveLength(4);
    expect(percent(22, 29)).toBe(76);
    expect(percent(1, 0)).toBe(0);
  });
});

describe('routes', () => {
  it('parses and builds hash routes', () => {
    expect(parseRoute('')).toEqual({ page: 'network' });
    expect(parseRoute('#/')).toEqual({ page: 'network' });
    expect(parseRoute('#/hospital/mercy')).toEqual({ page: 'hospital', hospitalId: 'mercy' });
    expect(parseRoute('#/hospital/st-lukes/')).toEqual({ page: 'hospital', hospitalId: 'st-lukes' });
    expect(parseRoute('#/hospital/<script>')).toEqual({ page: 'network' });
    expect(routeHash({ page: 'hospital', hospitalId: 'mercy' })).toBe('#/hospital/mercy');
    expect(routeHash({ page: 'network' })).toBe('#/');
    expect(isFreeze('?freeze=1')).toBe(true);
    expect(isFreeze('?freeze=0')).toBe(false);
    expect(isFreeze('')).toBe(false);
  });
});
