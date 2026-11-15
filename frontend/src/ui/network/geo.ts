/** Map geometry for the network screen: lat/lon to pixels, the street grid, vehicle positions along routes. */
import type { NetworkMessage } from '../../state/types';

export const MAP_W = 920;
export const MAP_H = 744;
const PAD_X = 150;
const PAD_Y = 120;

export interface Point {
  x: number;
  y: number;
}

export interface Grid {
  toXY: (lat: number, lon: number) => Point;
  /** y of each east-west street and x of each north-south street. */
  streetsY: number[];
  streetsX: number[];
}

/**
 * Projection for a set of hospitals: north is up, the hospitals' extent fills the map inside a margin. The
 * streets are the lines through the hospitals' latitudes and longitudes (ambulances drive on them).
 */
export function makeGrid(hospitals: readonly { lat: number; lon: number }[], width = MAP_W, height = MAP_H): Grid {
  const lats = hospitals.map((h) => h.lat);
  const lons = hospitals.map((h) => h.lon);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const toXY = (lat: number, lon: number): Point => ({
    x: PAD_X + ((lon - minLon) / (maxLon - minLon || 1)) * (width - 2 * PAD_X),
    y: PAD_Y + ((maxLat - lat) / (maxLat - minLat || 1)) * (height - 2 * PAD_Y),
  });
  const uniq = (v: number[]) => [...new Set(v)].sort((a, b) => a - b);
  return {
    toXY,
    streetsY: uniq(lats).map((lat) => toXY(lat, minLon).y),
    streetsX: uniq(lons).map((lon) => toXY(minLat, lon).x),
  };
}

type Route = NetworkMessage['vehicles'][number]['route'];

export interface VehiclePose {
  lat: number;
  lon: number;
  /** Heading of the current segment in radians (0 = east, pi/2 = south on screen). */
  heading: number | null;
}

/** Position on a route at `tMs`; before the first and after the last point the vehicle waits there. */
export function poseOnRoute(route: Route, tMs: number, fallback: { lat: number; lon: number }): VehiclePose {
  if (route.length === 0) return { ...fallback, heading: null };
  const pts = route.map((p) => ({ lat: p.lat, lon: p.lon, t: Date.parse(p.t) }));
  const first = pts[0];
  const last = pts[pts.length - 1];
  if (!first || !last) return { ...fallback, heading: null };
  if (tMs <= first.t) return { lat: first.lat, lon: first.lon, heading: null };
  if (tMs >= last.t) return { lat: last.lat, lon: last.lon, heading: null };
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i];
    const b = pts[i + 1];
    if (!a || !b || tMs < a.t || tMs > b.t) continue;
    const f = b.t > a.t ? (tMs - a.t) / (b.t - a.t) : 1;
    return { lat: a.lat + (b.lat - a.lat) * f, lon: a.lon + (b.lon - a.lon) * f, heading: b.lat === a.lat && b.lon === a.lon ? null : Math.atan2(-(b.lat - a.lat), b.lon - a.lon) };
  }
  return { lat: last.lat, lon: last.lon, heading: null };
}

export type StatusWord = 'OK' | 'BUSY' | 'CRITICAL' | 'OFFLINE';

/** The pill text: OFFLINE when the hospital takes no ambulances, otherwise by how full it is. */
export function statusWord(status: 'open' | 'diverting' | 'offline', census: number, capacity: number): StatusWord {
  if (status === 'offline') return 'OFFLINE';
  const pct = capacity > 0 ? census / capacity : 0;
  if (pct >= 0.9) return 'CRITICAL';
  if (pct >= 0.7) return 'BUSY';
  return 'OK';
}

export const STATUS_COLORS: Record<StatusWord, { bg: string; ink: string; text: string }> = {
  OK: { bg: '#3f9b6b', ink: '#ffffff', text: '#2b7350' },
  BUSY: { bg: '#f0a830', ink: '#1d2433', text: '#9a6410' },
  CRITICAL: { bg: '#c2363c', ink: '#ffffff', text: '#c2363c' },
  OFFLINE: { bg: '#55657c', ink: '#ffffff', text: '#55657c' },
};

export function percent(census: number, capacity: number): number {
  return capacity > 0 ? Math.round((census / capacity) * 100) : 0;
}

/** Minutes until a vehicle reaches the end of its route. */
export function minutesLeft(route: Route, tMs: number): number | null {
  const last = route[route.length - 1];
  if (!last) return null;
  return Math.max(0, Math.ceil((Date.parse(last.t) - tMs) / 60_000));
}
