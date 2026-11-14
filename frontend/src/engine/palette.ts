/**
 * Colors and style definitions, ported unchanged from reference/engine/pulse3d.js (PROMPT.md §10.2).
 * These values are pinned by tests/engine/palette.test.ts; changing one changes the look and needs the
 * human's approval (CLAUDE.md §1.10).
 */

export type StyleName = 'iso' | 'classic' | 'neon';

export function hex2rgb(h: string): [number, number, number] {
  const s = h.replace('#', '');
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
}

export function rgb2hex(r: number[]): string {
  return (
    '#' +
    r
      .map((v) => {
        const c = Math.max(0, Math.min(255, Math.round(v)));
        return (c < 16 ? '0' : '') + c.toString(16);
      })
      .join('')
  );
}

export function mix(a: string, b: string, t: number): string {
  const x = hex2rgb(a);
  const y = hex2rgb(b);
  return rgb2hex([x[0] + (y[0] - x[0]) * t, x[1] + (y[1] - x[1]) * t, x[2] + (y[2] - x[2]) * t]);
}

export function shade(a: string, t: number): string {
  return t < 0 ? mix(a, '#000000', -t) : mix(a, '#ffffff', t);
}

export const BASE = {
  sky: '#8fd3ff',
  grass: '#6fbf5a',
  grass2: '#5ea84c',
  road: '#4a4e5c',
  dash: '#f6e7a1',
  sidewalk: '#d8cfb6',
  asphalt: '#5a5f6e',
  slab: '#b9bfcc',
  wallInt: '#f6f2e8',
  wallExt: '#e9dcc6',
  wallExt2: '#cdb592',
  cap: '#3b4560',
  glass: '#8fd0f0',
  glassLit: '#ffe28a',
  roof: '#9aa3b8',
  helipad: '#4a4e5c',
  helipadMark: '#f6e7a1',
  ER: '#f3e3c3',
  IMG: '#dfe6f2',
  PHARM: '#e8f0dc',
  TRIAGE: '#f6dede',
  WAIT: '#d9e2ef',
  RECEP: '#e8e2f4',
  CORR: '#eceff3',
  WARD: '#d6efe2',
  OR: '#d4ecf0',
  RECOV: '#efe4f6',
  ICU: '#f4dadd',
  LAB: '#e2ecf6',
  STAFF: '#f1e6d4',
  PRAY: '#e6efe0',
  ADMIN: '#ece7dc',
  wood: '#c99a63',
  woodDark: '#7a5a36',
  bedFrame: '#8a93aa',
  sheet: '#ffffff',
  pillow: '#eef2f8',
  blanket: '#8ec0ea',
  shoulder: '#c9dcef',
  monitor: '#1b2140',
  pole: '#6b7390',
  chair: '#6b7890',
  chairBase: '#4b5266',
  curtain: '#76c7b9',
  machine: '#e6e9ef',
  machineDark: '#9aa3b8',
  trunk: '#7a5a36',
  tree: '#3f8a3a',
  tree2: '#56a64b',
  ambBody: '#f6f7fa',
  ambStripe: '#e5484d',
  nurse: '#2fa39a',
  nurse2: '#1f7a73',
  doc: '#f6f7fa',
  docPants: '#3b4560',
  surg: '#4f9c7a',
  gown: '#8ec0ea',
  emt: '#e58a2e',
  emtPants: '#2d3446',
  rug1: '#2f7a55',
  rug2: '#a8423c',
  rug3: '#c9a24a',
  couch: '#c25c5c',
  plant: '#3f8a3a',
  pot: '#b56b45',
  heli: '#e5484d',
  heliDark: '#2d3446',
  labelBg: '#20324a',
  labelInk: '#ffffff',
  low: '#3fb68b',
  med: '#f0a830',
  high: '#e5484d',
  screenOff: '#2c3563',
  ring: '#2453b0',
  lamp: '#fff6c9',
  vend: '#7fd0ff',
} as const;

export const MEDS = ['#e5484d', '#3d6fd6', '#f0b030', '#3fb68b'] as const;

export type Palette = { [K in keyof typeof BASE]: string };

export const SKINS = ['#e8b98f', '#c68a5e', '#8d5a3b', '#f1cfae', '#a86b45'] as const;
export const HAIRS = ['#2b1d14', '#5a3a22', '#111111', '#8c6a3f', '#3b2b4a'] as const;
export const SCARVES = ['#5c4a8a', '#2d6a5a', '#7a3a5c', '#3b5a8a'] as const;
export const TOPS = ['#7a5cc2', '#c25c8a', '#5c8ac2', '#8ac25c', '#c29a5c', '#5cc2b4', '#c25c5c'] as const;

export interface StyleDef {
  pix: number;
  toon: number;
  outline: boolean;
  outlineColor: string;
  texture: boolean;
  ortho: boolean;
  night: boolean;
  fog: [number, number] | null;
  hemi: [string, string, number];
  sun: [string, number];
  map: ((c: string) => string) | null;
  pal: Partial<Palette>;
}

/** The three ported styles. The prototype's `gameboy` style is intentionally not ported (PROMPT.md §10.2). */
export const STYLES: Record<StyleName, StyleDef> = {
  classic: {
    pix: 2,
    toon: 3,
    outline: true,
    outlineColor: '#1d1a2c',
    texture: true,
    ortho: false,
    night: false,
    fog: [80, 170],
    hemi: ['#ffffff', '#7a9a6a', 0.65],
    sun: ['#fff1d6', 0.85],
    map: null,
    pal: {},
  },
  neon: {
    pix: 2,
    toon: 3,
    outline: true,
    outlineColor: '#05060f',
    texture: true,
    ortho: false,
    night: true,
    fog: [40, 120],
    hemi: ['#8a9cff', '#202a50', 0.8],
    sun: ['#b4c4ff', 0.45],
    map: (c) => mix(mix(c, '#141a3a', 0.32), '#2a1a5a', 0.08),
    pal: {
      sky: '#0b1026',
      glassLit: '#ffd56b',
      labelBg: '#120a2a',
      labelInk: '#5ef2ff',
      dash: '#5ef2ff',
      lamp: '#ffffff',
      vend: '#ff5ec4',
      ring: '#5ef2ff',
    },
  },
  iso: {
    pix: 2,
    toon: 4,
    outline: true,
    outlineColor: '#3b3350',
    texture: true,
    ortho: true,
    night: false,
    fog: null,
    hemi: ['#ffffff', '#b8a99a', 0.75],
    sun: ['#fff6e8', 0.7],
    map: (c) => mix(c, '#fff4ea', 0.12),
    pal: { sky: '#f4efe4', labelBg: '#3b3350' },
  },
};

export const DEFAULT_PIXEL_FACTOR = 2;
export const MIN_PIXEL_FACTOR = 1;
export const MAX_PIXEL_FACTOR = 4;

/** Palette for a style: the base colors with the style's overrides. */
export function paletteFor(style: StyleName): Palette {
  return { ...BASE, ...STYLES[style].pal };
}

/** Risk level colors (PROMPT.md §10.2): low, medium, high. */
export function riskColor(level: 'low' | 'medium' | 'high' | null | undefined, p: Palette): string {
  if (level === 'high') return p.high;
  if (level === 'medium') return p.med;
  if (level === 'low') return p.low;
  return p.screenOff;
}

/** Marker color of a bedded patient whose risk is not scored yet. */
export const UNSCORED_MARKER = '#b8c4d6';
