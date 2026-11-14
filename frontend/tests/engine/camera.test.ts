import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { CameraController, ISO_AZIMUTH, ISO_ELEVATION, ORTHO_HEIGHT, PRESETS, TWEEN_MS, easeInOut, lerpState, look, presetById } from '../../src/engine/camera';
import { frameDelta, MAX_DT_S } from '../../src/engine/frame';

describe('camera angles pinned to the prototype', () => {
  it('isometric azimuth is 45 degrees and elevation is atan(1/2)', () => {
    expect(ISO_AZIMUTH).toBeCloseTo(Math.PI / 4, 10);
    expect((ISO_ELEVATION * 180) / Math.PI).toBeCloseTo(26.565, 2);
    expect(ISO_ELEVATION).toBeCloseTo(Math.atan(0.5), 3);
    const c = new CameraController('iso', 1280 / 744);
    expect(c.ortho.az).toBe(ISO_AZIMUTH);
    expect(c.ortho.el).toBe(ISO_ELEVATION);
  });

  it('the isometric camera is orthographic and free-fly is perspective', () => {
    expect(new CameraController('iso', 1.7).camera).toBeInstanceOf(THREE.OrthographicCamera);
    const free = new CameraController('free', 1.7).camera as THREE.PerspectiveCamera;
    expect(free).toBeInstanceOf(THREE.PerspectiveCamera);
    expect(free.fov).toBe(55);
  });

  it('has the nine presets with ASCII ids and separate display labels', () => {
    expect(PRESETS.map((p) => p.label)).toEqual([
      'Outside', 'Ground floor', 'Floor 2', 'Floor 3', 'Exploded', 'Helipad', 'Front door', 'Side view', 'ICU close-up',
    ]); // prettier-ignore
    for (const p of PRESETS) expect(p.id).toMatch(/^[a-z0-9_]+$/);
    expect(new Set(PRESETS.map((p) => p.id)).size).toBe(9);
    expect(presetById('front_door')?.label).toBe('Front door');
    expect(presetById('nope')).toBeUndefined();
  });

  it('presets hide and show the right floors', () => {
    expect(presetById('outside')?.view).toBe('all');
    expect(presetById('ground')?.view).toBe(0);
    expect(presetById('floor2')?.view).toBe(1);
    expect(presetById('floor3')?.view).toBe(2);
    expect(presetById('exploded')?.exploded).toBe(true);
    expect(presetById('outside')?.exploded).toBe(false);
  });

  it('keeps the prototype camera numbers', () => {
    expect(presetById('floor2')?.iso).toEqual({ tx: 0, ty: 3.4, tz: 0, az: Math.PI / 4, el: 0.62, zoom: 1.25 });
    expect(presetById('exploded')?.iso.zoom).toBe(0.62);
    expect(presetById('helipad')?.iso.zoom).toBe(2.2);
    expect(presetById('icu')?.iso).toEqual({ tx: -9, ty: 6.8, tz: -9, az: Math.PI / 5, el: 0.7, zoom: 2.8 });
    const f = look(-34, 26, 44, 0, 4, 0);
    expect(presetById('outside')?.free).toEqual(f);
    expect(f.yaw).toBeCloseTo(Math.atan2(-34, 44), 10); // the prototype: atan2(-dx, -dz)
  });
});

describe('easing and tweens', () => {
  it('eases between 0 and 1', () => {
    expect(easeInOut(0)).toBe(0);
    expect(easeInOut(1)).toBe(1);
    expect(easeInOut(0.5)).toBe(0.5);
    expect(easeInOut(0.25)).toBeLessThan(0.25);
    expect(easeInOut(0.75)).toBeGreaterThan(0.75);
  });
  it('takes the short way around for angles', () => {
    const r = lerpState({ az: 3 }, { az: -3 }, 0.5);
    expect(Math.abs(r['az'] as number)).toBeGreaterThan(3);
    expect(lerpState({ x: 0 }, { x: 10 }, 0.3)['x']).toBeCloseTo(3);
  });
  it('flies to a preset in 1.2 seconds', () => {
    const c = new CameraController('iso', 1.7);
    expect(TWEEN_MS).toBe(1200);
    c.flyTo({ tx: 10, ty: 0, tz: 0, az: ISO_AZIMUTH, el: 0.5, zoom: 2 }, 1000);
    c.update(0.016, 1600);
    expect(c.ortho.tx).toBeCloseTo(5, 1);
    expect(c.flying).toBe(true);
    c.update(0.016, 2200);
    expect(c.ortho.tx).toBe(10);
    expect(c.flying).toBe(false);
  });
  it('jump applies a preset at once and cancels a tween', () => {
    const c = new CameraController('free', 1.7);
    c.flyTo({ x: 100 }, 0);
    c.jump(presetById('ground') as NonNullable<ReturnType<typeof presetById>>);
    expect(c.flying).toBe(false);
    expect(c.free.y).toBe(20);
  });
});

describe('input', () => {
  it('drag rotates iso and clamps elevation; free-fly looks and clamps pitch', () => {
    const iso = new CameraController('iso', 1.7);
    iso.drag(100, 0);
    expect(iso.ortho.az).toBeCloseTo(ISO_AZIMUTH - 0.6);
    iso.drag(0, 10000);
    expect(iso.ortho.el).toBe(1.35);
    iso.drag(0, -100000);
    expect(iso.ortho.el).toBe(0.15);
    const free = new CameraController('free', 1.7);
    free.drag(0, -100000);
    expect(free.free.pitch).toBe(1.5);
    free.drag(0, 100000);
    expect(free.free.pitch).toBe(-1.5);
  });
  it('wheel zooms iso within 0.4..5 and dollies free-fly', () => {
    const iso = new CameraController('iso', 1.7);
    for (let i = 0; i < 50; i++) iso.wheel(-1);
    expect(iso.ortho.zoom).toBe(5);
    for (let i = 0; i < 100; i++) iso.wheel(1);
    expect(iso.ortho.zoom).toBe(0.4);
    const free = new CameraController('free', 1.7);
    const z0 = free.free.z;
    free.wheel(-100);
    expect(free.free.z).not.toBe(z0);
  });
  it('WASD pans iso, E and Q change height, Shift is faster', () => {
    const c = new CameraController('iso', 1.7);
    c.keys['KeyW'] = true;
    c.update(1, 0);
    const slow = Math.hypot(c.ortho.tx, c.ortho.tz);
    expect(slow).toBeCloseTo(10, 5);
    c.keys['ShiftLeft'] = true;
    const before = { ...c.ortho };
    c.update(1, 0);
    expect(Math.hypot(c.ortho.tx - before.tx, c.ortho.tz - before.tz)).toBeCloseTo(30, 5);
    c.keys['KeyW'] = false;
    c.keys['KeyE'] = true;
    const ty = c.ortho.ty;
    c.update(1, 0);
    expect(c.ortho.ty).toBeGreaterThan(ty);
    c.keys['KeyE'] = false;
    c.keys['KeyQ'] = true;
    c.update(10, 0);
    expect(c.ortho.ty).toBe(0);
  });
  it('free-fly moves along the view direction and stays above the ground', () => {
    const c = new CameraController('free', 1.7);
    c.keys['KeyQ'] = true;
    c.update(100, 0);
    expect(c.free.y).toBe(0.8);
    c.keys['KeyQ'] = false;
    c.keys['KeyW'] = true;
    const { x, z } = c.free;
    c.update(1, 0);
    expect(Math.hypot(c.free.x - x, c.free.z - z)).toBeCloseTo(10, 5);
  });
  it('writes the orthographic frustum and a negative delta cannot break the camera', () => {
    const c = new CameraController('iso', 2);
    const cam = c.camera as THREE.OrthographicCamera;
    expect(cam.top).toBe(ORTHO_HEIGHT / 2);
    expect(cam.right).toBe(ORTHO_HEIGHT);
    c.keys['KeyW'] = true;
    c.update(-5, 0);
    expect(Number.isFinite(c.ortho.tx)).toBe(true);
    expect(c.ortho.tx).toBe(0);
    c.resize(1);
    expect(cam.right).toBe(ORTHO_HEIGHT / 2);
    const free = new CameraController('free', 2);
    free.resize(1.5);
    expect((free.camera as THREE.PerspectiveCamera).aspect).toBe(1.5);
  });
  it('switching mode keeps the other mode state', () => {
    const c = new CameraController('iso', 1.7);
    c.setMode('free');
    expect(c.camera).toBeInstanceOf(THREE.PerspectiveCamera);
    expect(c.state['yaw']).toBeDefined();
  });
});

describe('frame delta (regression: a negative first frame crashed the prototype)', () => {
  it('is never negative, even when the first rAF timestamp is before performance.now()', () => {
    expect(frameDelta(100, 5000)).toBe(0);
    expect(frameDelta(5000, 5000)).toBe(0);
  });
  it('is clamped to 50 ms', () => {
    expect(frameDelta(10_000, 0)).toBe(MAX_DT_S);
    expect(frameDelta(1016, 1000)).toBeCloseTo(0.016);
  });
});
