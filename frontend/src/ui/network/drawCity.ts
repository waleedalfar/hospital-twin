/**
 * Draws the pixel-art city on the network screen's canvas (PROMPT.md §10.1): grass, the street grid, scenery,
 * the three hospitals, and the live ambulances and helicopter. Colors and sizes follow
 * reference/mockups/NetworkMap.dc.html. Positions of hospitals and vehicles come from the server's network
 * stream; trees, houses and grass specks are decoration only.
 */
import type { NetworkMessage } from '../../state/types';
import { MAP_H, MAP_W, makeGrid, poseOnRoute, statusWord, STATUS_COLORS, type Grid } from './geo';

const ROAD_EDGE = '#d9d2bb';
const ASPHALT = '#5a5f6e';
const DASH = '#f3e7b4';
const GRASS = '#8cc06f';
const SPECK = '#7aae5e';
const ROUTE_BLUE = '#2453b0';
const STREET = 44;
const EDGE = 56;

const TREES: readonly [number, number][] = [[40, 60], [90, 140], [40, 240], [110, 470], [50, 600], [130, 680], [260, 30], [520, 60], [540, 300], [700, 60], [820, 140], [760, 260], [480, 660], [820, 690]]; // prettier-ignore
const HOUSES: readonly [number, number][] = [[40, 420], [100, 530], [720, 130], [790, 200], [700, 300], [520, 520], [480, 430], [250, 660]]; // prettier-ignore
const ROOFS = ['#d77a52', '#b85c3c', '#e09a5c'];

function rect(ctx: CanvasRenderingContext2D, color: string, x: number, y: number, w: number, h: number): void {
  ctx.fillStyle = color;
  ctx.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
}

function tree(ctx: CanvasRenderingContext2D, x: number, y: number): void {
  rect(ctx, '#7a5a36', x + 11, y + 20, 6, 8);
  rect(ctx, '#3f8a3a', x + 2, y + 6, 24, 16);
  rect(ctx, '#56a64b', x + 8, y, 12, 10);
}

function ambulance(ctx: CanvasRenderingContext2D, x: number, y: number, heading: number, flash: boolean, carrying: boolean): void {
  ctx.save();
  ctx.translate(Math.round(x), Math.round(y));
  ctx.rotate(heading);
  rect(ctx, '#1d1a2c', -19, -11, 38, 22);
  rect(ctx, '#f6f7fa', -17, -9, 34, 18);
  rect(ctx, '#e5484d', -17, -2, 34, 4);
  rect(ctx, '#8fd0f0', 9, -7, 6, 14);
  rect(ctx, carrying ? (flash ? '#e5484d' : '#3b6fd6') : '#c9cfdb', -3, -9, 6, 4);
  ctx.restore();
}

function helicopter(ctx: CanvasRenderingContext2D, x: number, y: number, t: number): void {
  rect(ctx, '#1d1a2c', x - 12, y - 8, 24, 16);
  rect(ctx, '#e5484d', x - 10, y - 6, 20, 12);
  const spin = Math.floor(t / 60) % 2 === 0;
  rect(ctx, '#2d3446', spin ? x - 18 : x - 2, spin ? y - 2 : y - 18, spin ? 36 : 4, spin ? 4 : 36);
}

export interface DrawOptions {
  /** Wall-clock milliseconds for blinking. */
  nowMs: number;
  /** Sim time in ms for vehicle positions. */
  simMs: number;
}

export function drawCity(ctx: CanvasRenderingContext2D, net: NetworkMessage | null, o: DrawOptions): Grid | null {
  rect(ctx, GRASS, 0, 0, MAP_W, MAP_H);
  for (let i = 0; i < 40; i++) rect(ctx, SPECK, (i * 197) % 900, (i * 131) % 730, 8, 4);
  if (!net || net.hospitals.length === 0) return null;
  const grid = makeGrid(net.hospitals);
  for (const y of grid.streetsY) {
    rect(ctx, ROAD_EDGE, 0, y - EDGE / 2, MAP_W, EDGE);
    rect(ctx, ASPHALT, 0, y - STREET / 2, MAP_W, STREET);
    for (let x = 0; x < MAP_W; x += 48) rect(ctx, DASH, x, y - 2, 20, 4);
  }
  for (const x of grid.streetsX) {
    rect(ctx, ROAD_EDGE, x - EDGE / 2, 0, EDGE, MAP_H);
    rect(ctx, ASPHALT, x - STREET / 2, 0, STREET, MAP_H);
    for (let y = 0; y < MAP_H; y += 48) rect(ctx, DASH, x - 2, y, 4, 20);
  }
  for (const y of grid.streetsY) for (const x of grid.streetsX) rect(ctx, ASPHALT, x - STREET / 2, y - STREET / 2, STREET, STREET);
  const clear = (px: number, py: number, w: number, h: number): boolean =>
    !grid.streetsX.some((sx) => px + w > sx - EDGE / 2 - 6 && px < sx + EDGE / 2 + 6) && !grid.streetsY.some((sy) => py + h > sy - EDGE / 2 - 6 && py < sy + EDGE / 2 + 6);
  for (const [x, y] of TREES) {
    if (clear(x, y, 28, 28)) tree(ctx, x, y);
  }
  HOUSES.forEach(([x, y], i) => {
    if (!clear(x, y, 44, 36)) return;
    rect(ctx, '#5a3a2a', x, y, 44, 36);
    rect(ctx, ROOFS[i % 3] ?? ROOFS[0] ?? '#d77a52', x + 3, y + 3, 38, 30);
    rect(ctx, '#5a3a2a', x + 3, y + 15, 38, 6);
  });
  // Routes of ambulances carrying patients, dotted blue and white.
  for (const v of net.vehicles) {
    if (v.status !== 'to_hospital' && v.status !== 'transferring') continue;
    const pts = v.route.map((p) => grid.toXY(p.lat, p.lon));
    for (let i = 0; i < pts.length - 1; i++) {
      const a = pts[i];
      const b = pts[i + 1];
      if (!a || !b) continue;
      const n = Math.max(1, Math.floor(Math.hypot(b.x - a.x, b.y - a.y) / 16));
      for (let k = 0; k < n; k++) rect(ctx, (k + Math.floor(o.nowMs / 160)) % 4 === 0 ? '#ffffff' : ROUTE_BLUE, a.x + ((b.x - a.x) * k) / n - 4, a.y + ((b.y - a.y) * k) / n - 4, 8, 8);
    }
  }
  for (const h of net.hospitals) {
    const p = grid.toXY(h.lat, h.lon);
    const word = statusWord(h.status, h.kpis.census, h.kpis.capacity);
    const w = 150;
    const hh = 100;
    rect(ctx, 'rgba(29,36,51,0.35)', p.x - w / 2 + 6, p.y - hh / 2 + 6, w, hh);
    rect(ctx, '#3b4560', p.x - w / 2, p.y - hh / 2, w, hh);
    rect(ctx, '#e4e8f0', p.x - w / 2 + 4, p.y - hh / 2 + 4, w - 8, hh - 8);
    rect(ctx, '#c9cfdb', p.x - w / 2 + 12, p.y - hh / 2 + 12, w - 24, 6);
    rect(ctx, '#e5484d', p.x - 4, p.y - 18, 8, 32);
    rect(ctx, '#e5484d', p.x - 16, p.y - 6, 32, 8);
    rect(ctx, STATUS_COLORS[word].bg, p.x - w / 2 + 10, p.y + hh / 2 - 20, 28, 10);
  }
  for (const v of net.vehicles) {
    const pose = poseOnRoute(v.route, o.simMs, v);
    const p = grid.toXY(pose.lat, pose.lon);
    const heading = pose.heading ?? 0;
    if (v.kind === 'helicopter') {
      if (v.status !== 'at_base') helicopter(ctx, p.x, p.y, o.nowMs);
      continue;
    }
    if (v.status === 'at_base' || v.status === 'unloading') continue; // parked in the hospital's bay
    ambulance(ctx, p.x, p.y, heading, Math.floor(o.nowMs / 160) % 2 === 0, v.patient_id !== null);
  }
  return grid;
}
