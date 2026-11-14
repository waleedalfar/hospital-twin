import * as THREE from 'three';
import { describe, expect, it } from 'vitest';

import { PART_NAMES, auditFace, roleStyle, skinColor, type AppearanceSpec, type Role } from '../../src/engine/characters';
import { paletteFor } from '../../src/engine/palette';
import { makeKit } from './helpers';

const ROLES: Role[] = ['patient', 'visitor', 'nurse', 'doctor', 'surgeon', 'emt'];
const APPEARANCES: AppearanceSpec[] = [];
for (let skin = 0; skin < 5; skin++) for (let hair = 0; hair < 5; hair++) for (const headscarf of [false, true]) APPEARANCES.push({ skin, hair, headscarf, top: skin + hair });

describe('faceless characters (PROMPT.md §10.4)', () => {
  it('the factory exposes exactly the allowed part names', () => {
    const { chars } = makeKit();
    expect([...chars.partNames].sort()).toEqual(
      ['legL', 'legR', 'torso', 'armL', 'armR', 'handL', 'handR', 'head', 'hairCap', 'hairBack', 'scarf', 'scarfDrape', 'facePanel'].sort(),
    );
    expect(PART_NAMES).toHaveLength(13);
  });

  it('every role and appearance builds only allowed parts, with a plain skin-colored facePanel at most', () => {
    for (const style of ['iso', 'classic', 'neon'] as const) {
      const { tk, chars } = makeKit(style);
      const allowed = new Set<string>(PART_NAMES);
      for (const role of ROLES) {
        for (const a of APPEARANCES) {
          const parent = new THREE.Group();
          const c = chars.create(role, a, parent, false);
          expect(c.partNames().every((p) => allowed.has(p))).toBe(true);
          const audit = auditFace(c.group, tk.mapC(skinColor(a)));
          expect(audit.problems).toEqual([]);
          const panels = c.partNames().filter((p) => p === 'facePanel').length;
          expect(panels).toBe(a.headscarf ? 1 : 0);
          expect(c.partNames()).toContain('head');
        }
      }
    }
  });

  it('facePanel is one box with one material in the skin color and nothing else is on the front of the head', () => {
    const { tk, chars } = makeKit();
    const c = chars.create('nurse', { skin: 2, hair: 1, headscarf: true }, new THREE.Group(), false);
    const panels: THREE.Mesh[] = [];
    c.group.traverse((o) => {
      if (o.userData['part'] === 'facePanel' && o instanceof THREE.Mesh) panels.push(o as THREE.Mesh);
    });
    expect(panels).toHaveLength(1);
    const panel = panels[0]!;
    expect(panel.geometry).toBeInstanceOf(THREE.BoxGeometry);
    expect(Array.isArray(panel.material)).toBe(false);
    expect('#' + (panel.material as THREE.MeshToonMaterial).color.getHexString()).toBe(tk.mapC(skinColor({ skin: 2, hair: 1, headscarf: true })));
  });

  it('lying models are faceless too', () => {
    const { tk, chars } = makeKit();
    for (const a of APPEARANCES) {
      for (const kind of ['bed', 'table'] as const) {
        const g = chars.createLying(a, new THREE.Group(), kind);
        expect(auditFace(g, tk.mapC(skinColor(a)), '+y').problems).toEqual([]);
      }
    }
  });

  it('the audit catches an eye, a mouth, an extra part or a wrong-colored face panel', () => {
    const { tk, chars } = makeKit();
    const a: AppearanceSpec = { skin: 0, hair: 0, headscarf: false };
    const skin = tk.mapC(skinColor(a));
    const make = (): THREE.Group => chars.create('visitor', a, new THREE.Group(), false).group;

    const eye = make();
    const eyeMesh = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.05, 0.02), new THREE.MeshBasicMaterial({ color: '#000000' }));
    eyeMesh.position.set(0.1, 1.85, 0.22);
    eyeMesh.userData['part'] = 'torso'; // pretending to be an allowed part does not hide it
    eye.add(eyeMesh);
    expect(auditFace(eye, skin).problems.join()).toContain('front face');

    const unnamed = make();
    unnamed.add(new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.1, 0.1), new THREE.MeshBasicMaterial()));
    expect(auditFace(unnamed, skin).problems.join()).toContain('no part name');

    const wrongName = make();
    const nose = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.1, 0.1), new THREE.MeshBasicMaterial());
    nose.userData['part'] = 'nose';
    wrongName.add(nose);
    expect(auditFace(wrongName, skin).problems.join()).toContain('nose is not allowed');

    const scarfed = chars.create('visitor', { ...a, headscarf: true }, new THREE.Group(), false).group;
    const panel = scarfed.children.find((c) => c.userData['part'] === 'facePanel') as THREE.Mesh;
    (panel.material as THREE.MeshToonMaterial) = new THREE.MeshToonMaterial({ color: '#ff0000' });
    expect(auditFace(scarfed, skin).problems.join()).toContain('not the skin color');
    const second = panel.clone();
    scarfed.add(second);
    expect(auditFace(scarfed, skin).problems.join()).toContain('2 facePanel');
  });
});

describe('the audit does not depend on which way the person faces (regression)', () => {
  it('passes for characters rotated and moved anywhere, and still catches a bad part', () => {
    const { tk, chars } = makeKit();
    const a: AppearanceSpec = { skin: 1, hair: 1, headscarf: false };
    const skin = tk.mapC(skinColor(a));
    for (const yaw of [0, Math.PI / 2, Math.PI, -Math.PI / 2, 2.3]) {
      const parent = new THREE.Group();
      parent.position.set(5, 3, -7);
      parent.rotation.y = 0.4;
      const c = chars.create('nurse', a, parent, false);
      c.group.rotation.y = yaw;
      c.group.position.x = 11;
      expect(auditFace(c.group, skin).problems).toEqual([]);
      const eye = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.05, 0.02), new THREE.MeshBasicMaterial());
      eye.position.set(0.1, 1.85, 0.22);
      eye.userData['part'] = 'torso';
      c.group.add(eye);
      expect(auditFace(c.group, skin).problems.join()).toContain('front face');
    }
  });
});

describe('roles, poses and animation', () => {
  it('role colors follow the spec', () => {
    const p = paletteFor('iso');
    const a: AppearanceSpec = { skin: 0, hair: 0, headscarf: false, top: 3 };
    expect(roleStyle('nurse', a, p).top).toBe('#2fa39a');
    expect(roleStyle('surgeon', a, p).top).toBe('#4f9c7a');
    expect(roleStyle('emt', a, p).top).toBe('#e58a2e');
    expect(roleStyle('patient', a, p).top).toBe('#8ec0ea');
    expect(roleStyle('doctor', a, p).top).toBe('#f6f7fa');
    expect(roleStyle('visitor', a, p).top).toBe('#8ac25c');
    expect(roleStyle('visitor', { ...a, top: 9 }, p).top).toBe('#5c8ac2');
  });

  it('seated people sit lower with bent legs; walking people swing their legs', () => {
    const { chars } = makeKit();
    const c = chars.create('nurse', { skin: 0, hair: 0, headscarf: false }, new THREE.Group(), false);
    c.setPose('seated');
    c.animate(0, 0, 0);
    expect(c.legs[0].rotation.x).toBeCloseTo(-Math.PI / 2);
    expect(c.group.position.y).toBeLessThan(0.3);
    c.setPose('standing');
    c.animate(0, 0, 3.4);
    expect(c.legs[0].rotation.x).toBe(0);
    expect(c.group.position.y).toBeCloseTo(3.7, 1);
    c.setPose('walking');
    c.animate(0.2, 0, 0);
    expect(c.legs[0].rotation.x).toBeCloseTo(-c.legs[1].rotation.x);
    expect(Math.abs(c.legs[0].rotation.x)).toBeGreaterThan(0.1);
  });

  it('role markers use the role color', () => {
    const { tk, chars } = makeKit();
    const c = chars.create('nurse', { skin: 0, hair: 0, headscarf: false }, new THREE.Group(), true);
    expect(c.marker?.userData['markerColor']).toBe(tk.mapC('#2fa39a'));
  });
});
