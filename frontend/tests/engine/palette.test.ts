import { describe, expect, it } from 'vitest';

import { BASE, DEFAULT_PIXEL_FACTOR, HAIRS, MEDS, SCARVES, SKINS, STYLES, TOPS, hex2rgb, mix, paletteFor, rgb2hex, riskColor, shade } from '../../src/engine/palette';

/** These constants are the prototype's look (CLAUDE.md §1.10). Changing one needs the human's approval. */
describe('palette pinned to the prototype', () => {
  it('has the spec colors', () => {
    expect(BASE.sky).toBe('#8fd3ff');
    expect(BASE.grass).toBe('#6fbf5a');
    expect(BASE.wallInt).toBe('#f6f2e8');
    expect(BASE.wallExt).toBe('#e9dcc6');
    expect(BASE.glass).toBe('#8fd0f0');
    expect(BASE.low).toBe('#3fb68b');
    expect(BASE.med).toBe('#f0a830');
    expect(BASE.high).toBe('#e5484d');
    expect(BASE.nurse).toBe('#2fa39a');
  });

  it('has the room colors', () => {
    expect([BASE.ER, BASE.IMG, BASE.PHARM, BASE.TRIAGE, BASE.WAIT, BASE.RECEP, BASE.CORR]).toEqual([
      '#f3e3c3', '#dfe6f2', '#e8f0dc', '#f6dede', '#d9e2ef', '#e8e2f4', '#eceff3',
    ]); // prettier-ignore
    expect([BASE.WARD, BASE.OR, BASE.RECOV, BASE.ICU, BASE.LAB, BASE.STAFF, BASE.PRAY, BASE.ADMIN]).toEqual([
      '#d6efe2', '#d4ecf0', '#efe4f6', '#f4dadd', '#e2ecf6', '#f1e6d4', '#e6efe0', '#ece7dc',
    ]); // prettier-ignore
  });

  it('has the character colors', () => {
    expect(SKINS).toEqual(['#e8b98f', '#c68a5e', '#8d5a3b', '#f1cfae', '#a86b45']);
    expect(HAIRS).toEqual(['#2b1d14', '#5a3a22', '#111111', '#8c6a3f', '#3b2b4a']);
    expect(SCARVES).toEqual(['#5c4a8a', '#2d6a5a', '#7a3a5c', '#3b5a8a']);
    expect(TOPS).toHaveLength(7);
    expect(MEDS).toHaveLength(4);
    expect([BASE.gown, BASE.surg, BASE.emt]).toEqual(['#8ec0ea', '#4f9c7a', '#e58a2e']);
  });

  it('pins pixel factor, toon steps and outline colors', () => {
    expect(DEFAULT_PIXEL_FACTOR).toBe(2);
    expect(STYLES.classic.pix).toBe(2);
    expect(STYLES.iso.pix).toBe(2);
    expect(STYLES.neon.pix).toBe(2);
    expect([STYLES.classic.toon, STYLES.iso.toon, STYLES.neon.toon]).toEqual([3, 4, 3]);
    expect(STYLES.classic.outlineColor).toBe('#1d1a2c');
    expect(STYLES.iso.outlineColor).toBe('#3b3350');
    expect(STYLES.neon.outlineColor).toBe('#05060f');
    expect(STYLES.iso.pal.sky).toBe('#f4efe4');
    expect(STYLES.neon.pal.sky).toBe('#0b1026');
    expect(STYLES.neon.night).toBe(true);
    expect(STYLES.classic.fog).toEqual([80, 170]);
  });

  it('ports exactly three styles (the gameboy style is not ported)', () => {
    expect(Object.keys(STYLES).sort()).toEqual(['classic', 'iso', 'neon']);
  });

  it('has the style color maps and palette overrides', () => {
    expect(STYLES.classic.map).toBeNull();
    expect(STYLES.iso.map?.('#000000')).toBe(mix('#000000', '#fff4ea', 0.12));
    expect(STYLES.neon.map?.('#ffffff')).toBe(mix(mix('#ffffff', '#141a3a', 0.32), '#2a1a5a', 0.08));
    expect(paletteFor('neon').labelInk).toBe('#5ef2ff');
    expect(paletteFor('iso').labelBg).toBe('#3b3350');
    expect(paletteFor('classic').labelBg).toBe('#20324a');
  });
});

describe('color helpers', () => {
  it('round-trips hex and rgb', () => {
    expect(hex2rgb('#e5484d')).toEqual([229, 72, 77]);
    expect(rgb2hex([229, 72, 77])).toBe('#e5484d');
    expect(rgb2hex([-5, 300, 8.4])).toBe('#00ff08');
  });
  it('mixes and shades', () => {
    expect(mix('#000000', '#ffffff', 0.5)).toBe('#808080');
    expect(shade('#808080', -0.5)).toBe('#404040');
    expect(shade('#808080', 0.5)).toBe('#c0c0c0');
  });
  it('maps risk levels to colors', () => {
    const p = paletteFor('iso');
    expect(riskColor('low', p)).toBe(p.low);
    expect(riskColor('medium', p)).toBe(p.med);
    expect(riskColor('high', p)).toBe(p.high);
    expect(riskColor(null, p)).toBe(p.screenOff);
  });
});
