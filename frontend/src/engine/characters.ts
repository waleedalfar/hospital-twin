/**
 * Voxel characters (PROMPT.md §10.3). Built from boxes: two legs, torso, two arms with hands, a head block,
 * and either a hair cap and back or a headscarf. NO eyes, nose, mouth, eyebrows or any facial detail: the
 * only thing on the front of a head is `facePanel`, one plain box in the skin color (§10.4). Ported from
 * `person()` in reference/engine/pulse3d.js.
 */
import * as THREE from 'three';

import type { LabelFactory } from './labels';
import type { Toolkit } from './materials';
import { HAIRS, SCARVES, SKINS, TOPS, type Palette } from './palette';

export const PART_NAMES = [
  'legL',
  'legR',
  'torso',
  'armL',
  'armR',
  'handL',
  'handR',
  'head',
  'hairCap',
  'hairBack',
  'scarf',
  'scarfDrape',
  'facePanel',
] as const;
export type PartName = (typeof PART_NAMES)[number];

export type Role = 'patient' | 'visitor' | 'nurse' | 'doctor' | 'surgeon' | 'emt';
export type CharacterPose = 'walking' | 'standing' | 'seated' | 'lying';

export interface AppearanceSpec {
  skin: number;
  hair: number;
  headscarf: boolean;
  top?: number;
}

export interface RoleStyle {
  top: string;
  bottom: string;
  detail?: string;
  mark: string;
}

export const SLAB = 0.3;
const WALK_SPEED_M_S = 1.3;
export const VISITOR_MARK = '#b48ead';

export function roleStyle(role: Role, appearance: AppearanceSpec, P: Palette): RoleStyle {
  switch (role) {
    case 'nurse':
      return { top: P.nurse, bottom: P.nurse2, detail: '#ffffff', mark: P.nurse };
    case 'doctor':
      return { top: P.doc, bottom: P.docPants, detail: P.nurse, mark: '#ffffff' };
    case 'surgeon':
      return { top: P.surg, bottom: P.surg, detail: '#ffffff', mark: P.surg };
    case 'emt':
      return { top: P.emt, bottom: P.emtPants, detail: '#f3e7b4', mark: P.emt };
    case 'patient':
      return { top: P.gown, bottom: P.gown, mark: P.gown };
    case 'visitor':
      return { top: TOPS[(appearance.top ?? 0) % TOPS.length] ?? TOPS[0], bottom: P.docPants, mark: VISITOR_MARK };
  }
}

function pick<T>(list: readonly T[], i: number): T {
  const v = list[((i % list.length) + list.length) % list.length];
  if (v === undefined) throw new Error('empty palette list');
  return v;
}

export function skinColor(a: AppearanceSpec): string {
  return pick(SKINS, a.skin);
}
export function hairColor(a: AppearanceSpec): string {
  return pick(HAIRS, a.hair);
}
export function scarfColor(a: AppearanceSpec): string {
  return pick(SCARVES, a.hair);
}

export class Character {
  readonly legs: [THREE.Group, THREE.Group];
  readonly arms: [THREE.Group, THREE.Group];
  baseY = 0;
  pose: CharacterPose = 'standing';
  marker: THREE.Sprite | null = null;
  /** The skin color this character was built with, so the faceless audit can compare it. */
  readonly skin: string;

  constructor(
    readonly group: THREE.Group,
    legs: [THREE.Group, THREE.Group],
    arms: [THREE.Group, THREE.Group],
    skin: string,
  ) {
    this.legs = legs;
    this.arms = arms;
    this.skin = skin;
  }

  /** Names of the parts this character is built from. */
  partNames(): PartName[] {
    const found = new Set<PartName>();
    this.group.traverse((o) => {
      const p = o.userData['part'] as PartName | undefined;
      if (p) found.add(p);
    });
    return [...found];
  }

  setPose(pose: CharacterPose): void {
    this.pose = pose;
    const seated = pose === 'seated';
    this.legs.forEach((l) => (l.rotation.x = seated ? -Math.PI / 2 : 0));
    this.arms.forEach((a) => (a.rotation.x = seated ? -0.6 : 0));
    if (pose === 'standing') {
      this.legs.forEach((l) => (l.rotation.x = 0));
    }
    this.group.position.y = this.baseY - (seated ? 0.2 : 0);
  }

  /**
   * Per-frame animation: leg and arm swing while walking, a tiny bob while standing or seated. `floorY` is
   * the height of the floor the character is on (floors ease apart in exploded and X-ray views).
   */
  animate(time: number, phase: number, floorY: number): void {
    this.baseY = floorY + SLAB;
    let y = this.baseY;
    if (this.pose === 'walking') {
      const sw = Math.sin(time * (2 + WALK_SPEED_M_S * 3) + phase) * 0.6;
      this.legs[0].rotation.x = sw;
      this.legs[1].rotation.x = -sw;
      this.arms[0].rotation.x = -sw * 0.8;
      this.arms[1].rotation.x = sw * 0.8;
    } else {
      if (this.pose === 'seated') y -= 0.2;
      y += Math.sin(time * 2 + phase) * 0.012;
    }
    this.group.position.y = y;
  }
}

export class CharacterFactory {
  constructor(
    private readonly tk: Toolkit,
    private readonly labels: LabelFactory | null = null,
  ) {}

  /** The list of part names this factory builds from (PROMPT.md §10.4). */
  get partNames(): readonly PartName[] {
    return PART_NAMES;
  }

  private part(mesh: THREE.Object3D, name: PartName): void {
    mesh.name = name;
    mesh.userData['part'] = name;
  }

  /** A standing, walking or seated person. Feet are at y = 0 of the returned group. */
  create(role: Role, appearance: AppearanceSpec, parent: THREE.Object3D, withMarker = true): Character {
    const tk = this.tk;
    const o = roleStyle(role, appearance, tk.P);
    const skin = skinColor(appearance);
    const hair = hairColor(appearance);
    const g = new THREE.Group();
    const legs: THREE.Group[] = [];
    const arms: THREE.Group[] = [];
    (['legL', 'legR'] as const).forEach((name, i) => {
      const pivot = new THREE.Group();
      pivot.position.set(i === 0 ? -0.13 : 0.13, 0.85, 0);
      this.part(tk.box(0.22, 0.8, 0.26, o.bottom, 0, -0.4, 0, pivot), name);
      g.add(pivot);
      legs.push(pivot);
    });
    const torso = tk.box(0.6, 0.7, 0.34, o.top, 0, 1.2, 0, g);
    this.part(torso, 'torso');
    if (o.detail) {
      const badge = tk.box(0.12, 0.12, 0.02, o.detail, 0.15, 1.38, 0.18, g, { outline: false });
      this.part(badge, 'torso');
    }
    (['armL', 'armR'] as const).forEach((name, i) => {
      const pivot = new THREE.Group();
      pivot.position.set(i === 0 ? -0.4 : 0.4, 1.5, 0);
      this.part(tk.box(0.18, 0.62, 0.2, o.top, 0, -0.31, 0, pivot), name);
      this.part(tk.box(0.18, 0.12, 0.2, skin, 0, -0.68, 0, pivot, { outline: false }), i === 0 ? 'handL' : 'handR');
      g.add(pivot);
      arms.push(pivot);
    });
    if (appearance.headscarf) {
      const scarf = scarfColor(appearance);
      // The head block sits inside the scarf; the scarf box wraps it and the plain skin panel is the only
      // thing on the front.
      this.part(tk.box(0.42, 0.42, 0.42, skin, 0, 1.8, 0, g), 'head');
      this.part(tk.box(0.48, 0.52, 0.46, scarf, 0, 1.82, -0.02, g), 'scarf');
      this.part(tk.box(0.3, 0.3, 0.03, skin, 0, 1.8, 0.22, g, { outline: false }), 'facePanel');
      this.part(tk.box(0.54, 0.18, 0.42, scarf, 0, 1.52, -0.02, g), 'scarfDrape');
    } else {
      this.part(tk.box(0.42, 0.42, 0.42, skin, 0, 1.8, 0, g), 'head');
      this.part(tk.box(0.44, 0.14, 0.44, hair, 0, 2.04, 0, g), 'hairCap');
      this.part(tk.box(0.44, 0.34, 0.1, hair, 0, 1.86, -0.2, g), 'hairBack');
    }
    g.position.y = SLAB;
    parent.add(g);
    const c = new Character(g, [legs[0] as THREE.Group, legs[1] as THREE.Group], [arms[0] as THREE.Group, arms[1] as THREE.Group], tk.mapC(skin));
    c.baseY = SLAB;
    if (withMarker && this.labels) c.marker = this.labels.marker(tk.mapC(o.mark), g, 0, 2.75, 0, 0.5);
    return c;
  }

  /**
   * A person lying down: head, hair (or headscarf) and shoulders. Used inside a bed (the blanket belongs to
   * the bed) and on a table. Coordinates are bed-local with the head toward -z, as in the prototype.
   */
  createLying(appearance: AppearanceSpec, parent: THREE.Object3D, kind: 'bed' | 'table'): THREE.Group {
    const tk = this.tk;
    const skin = skinColor(appearance);
    const g = new THREE.Group();
    const headY = kind === 'bed' ? 0.86 : 1.2;
    const headZ = kind === 'bed' ? -0.72 : -1.0;
    this.part(tk.box(0.36, 0.36, 0.36, skin, 0, headY, headZ, g), 'head');
    if (appearance.headscarf) {
      this.part(tk.box(0.4, 0.4, 0.4, scarfColor(appearance), 0, headY, headZ - 0.01, g), 'scarf');
    } else {
      this.part(tk.box(0.38, 0.36, 0.1, hairColor(appearance), 0, headY, headZ - 0.21, g, { outline: false }), 'hairBack');
    }
    if (kind === 'bed') this.part(tk.box(0.8, 0.2, 0.3, tk.P.shoulder, 0, 0.72, -0.4, g), 'torso');
    else this.part(tk.box(0.4, 0.3, 1.4, tk.P.gown, 0, 1.17, -0.8, g), 'torso');
    parent.add(g);
    return g;
  }
}

/** Result of the faceless audit of one character (PROMPT.md §10.4). */
export interface FaceAudit {
  ok: boolean;
  problems: string[];
}

const EPS = 1e-6;

/**
 * Checks that a character group has no facial features: every part is on the allowed list; there is at most
 * one `facePanel`, a single box with one material whose color is the skin color; and nothing but the
 * `facePanel` sits on the front face of the head. A person lying on their back faces up, so the front is
 * +y for lying models and +z for everyone else.
 */
export function auditFace(root: THREE.Object3D, skin: string, front: '+z' | '+y' = '+z'): FaceAudit {
  const problems: string[] = [];
  const allowed = new Set<string>(PART_NAMES);
  const meshes: { mesh: THREE.Mesh; part: string }[] = [];
  root.traverse((o) => {
    const part = o.userData['part'] as string | undefined;
    if (part !== undefined) {
      if (!allowed.has(part)) problems.push(`part ${part} is not allowed`);
      if (o instanceof THREE.Mesh) meshes.push({ mesh: o as THREE.Mesh, part });
    } else if (o instanceof THREE.Mesh) {
      problems.push(`mesh ${o.name || o.uuid} has no part name`);
    }
  });
  const panels = meshes.filter((m) => m.part === 'facePanel');
  if (panels.length > 1) problems.push(`${panels.length} facePanel parts`);
  const panel = panels[0];
  if (panel) {
    if (!(panel.mesh.geometry instanceof THREE.BoxGeometry)) problems.push('facePanel is not a box');
    const mat = panel.mesh.material;
    if (Array.isArray(mat)) problems.push('facePanel has several materials');
    else if (!('color' in mat) || '#' + (mat as THREE.MeshToonMaterial).color.getHexString() !== skin.toLowerCase()) {
      problems.push('facePanel color is not the skin color');
    }
    if (panel.mesh.children.some((c) => c instanceof THREE.LineSegments)) problems.push('facePanel has an outline');
  }
  const head = meshes.find((m) => m.part === 'head');
  if (head) {
    // Measure in the character's own frame, so the check does not depend on which way the person faces.
    root.updateWorldMatrix(true, true);
    const toRoot = new THREE.Matrix4().copy(root.matrixWorld).invert();
    const box = (m: THREE.Mesh): THREE.Box3 => {
      m.updateWorldMatrix(true, false);
      m.geometry.computeBoundingBox();
      const local = m.geometry.boundingBox as THREE.Box3;
      return local.clone().applyMatrix4(new THREE.Matrix4().multiplyMatrices(toRoot, m.matrixWorld));
    };
    const hb = box(head.mesh);
    const [a, b, c] = front === '+z' ? (['x', 'y', 'z'] as const) : (['x', 'z', 'y'] as const);
    const frontPlane = hb.max[c];
    const middle = (hb.min[c] + hb.max[c]) / 2;
    for (const m of meshes) {
      if (m.part === 'facePanel' || m === head) continue;
      const pb = box(m.mesh);
      const overlaps =
        pb.min[a] < hb.max[a] - EPS && pb.max[a] > hb.min[a] + EPS && pb.min[b] < hb.max[b] - EPS && pb.max[b] > hb.min[b] + EPS;
      // A part is a patch on the front face if it lies entirely in the front half of the head and reaches
      // the front plane. Hair and scarves wrap around the head (they start behind its middle), so they are not.
      if (overlaps && pb.min[c] >= middle - EPS && pb.max[c] >= frontPlane - EPS) {
        problems.push(`${m.part} sits on the front face of the head`);
      }
    }
  }
  return { ok: problems.length === 0, problems };
}
