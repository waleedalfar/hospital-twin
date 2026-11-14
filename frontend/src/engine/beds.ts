/**
 * Hospital beds with a bedside monitor, a lying patient and a risk-colored screen. Ported from `bed()` in
 * reference/engine/pulse3d.js. Empty beds stay in the scene with a dark screen; a patient appears when the
 * live state says the bed is occupied.
 */
import * as THREE from 'three';

import { SLAB, type AppearanceSpec, type CharacterFactory } from './characters';
import type { LabelFactory } from './labels';
import type { Bed } from './layout';
import type { Toolkit } from './materials';
import { UNSCORED_MARKER } from './palette';

export type BedMode = 'empty' | 'patient';

export interface BedView {
  bed: Bed;
  group: THREE.Group;
  /** The monitor screen; its color is the patient's risk color. */
  glow: THREE.Mesh;
  marker: THREE.Sprite | null;
  bang: THREE.Sprite | null;
  /** Meshes a click can select (head and blanket). */
  pickables: THREE.Mesh[];
  patientId: string | null;
  riskLevel: 'low' | 'medium' | 'high' | null;
  blink: boolean;
  lying: THREE.Group | null;
  blanket: THREE.Mesh | null;
  bangBase: number;
}

export function buildBed(tk: Toolkit, bed: Bed, floorGroup: THREE.Object3D): BedView {
  const g = new THREE.Group();
  g.position.set(bed.x, SLAB, bed.z);
  g.rotation.y = bed.rotation;
  g.name = `bed:${bed.id}`;
  floorGroup.add(g);
  tk.box(1.1, 0.45, 2.1, tk.P.bedFrame, 0, 0.25, 0, g);
  tk.box(1.0, 0.15, 2.0, tk.P.sheet, 0, 0.55, 0, g);
  tk.box(1.1, 0.8, 0.12, tk.P.pole, 0, 0.6, -1.05, g);
  tk.box(0.7, 0.12, 0.4, tk.P.pillow, 0, 0.68, -0.7, g, { outline: false });
  tk.box(0.08, 1.6, 0.08, tk.P.pole, 0.78, 0.8, -0.9, g, { outline: false });
  tk.box(0.5, 0.42, 0.1, tk.P.monitor, 0.78, 1.7, -0.9, g);
  const glow = tk.box(0.4, 0.3, 0.12, tk.B(tk.P.screenOff), 0.78, 1.7, -0.88, g, { cast: false, outline: false });
  return {
    bed,
    group: g,
    glow,
    marker: null,
    bang: null,
    pickables: [],
    patientId: null,
    riskLevel: null,
    blink: false,
    lying: null,
    blanket: null,
    bangBase: SLAB + 2.9,
  };
}

/** Put a lying patient in the bed (or take them out when `appearance` is null). */
export function setBedPatient(
  tk: Toolkit,
  chars: CharacterFactory,
  labels: LabelFactory,
  view: BedView,
  floorGroup: THREE.Object3D,
  patientId: string | null,
  appearance: AppearanceSpec | null,
): void {
  if (view.patientId === patientId && (patientId === null) === (view.lying === null)) return;
  view.patientId = patientId;
  if (view.lying) {
    view.group.remove(view.lying);
    view.lying = null;
  }
  if (view.blanket) {
    view.group.remove(view.blanket);
    view.blanket = null;
  }
  if (view.marker) {
    labels.removeMarker(view.marker);
    view.marker = null;
  }
  if (view.bang) {
    floorGroup.remove(view.bang);
    view.bang = null;
  }
  view.pickables = [];
  view.blink = false;
  view.riskLevel = null;
  setScreen(tk, view, null);
  if (patientId === null || appearance === null) return;
  const lying = chars.createLying(appearance, view.group, 'bed');
  const blanket = tk.box(0.95, 0.25, 1.3, tk.P.blanket, 0, 0.75, 0.3, view.group);
  view.lying = lying;
  view.blanket = blanket;
  const head = lying.children.find((c) => c.userData['part'] === 'head');
  view.pickables = [head, blanket].filter((m): m is THREE.Mesh => m instanceof THREE.Mesh);
  for (const m of view.pickables) m.userData['bedId'] = view.bed.id;
  view.marker = labels.marker(tk.mapC(UNSCORED_MARKER), floorGroup, view.bed.x, SLAB + 2.0, view.bed.z, 0.6);
}

/** Color the monitor and marker for a risk level, and show the blinking "!" for high risk. */
export function setRisk(
  tk: Toolkit,
  labels: LabelFactory,
  view: BedView,
  floorGroup: THREE.Object3D,
  level: 'low' | 'medium' | 'high' | null,
): void {
  view.riskLevel = level;
  setScreen(tk, view, level);
  if (view.marker) {
    const color = level === null ? UNSCORED_MARKER : tk.P[level === 'medium' ? 'med' : level];
    labels.tintMarker(view.marker, tk.mapC(color));
  }
  const wantBang = level === 'high' && view.patientId !== null;
  if (wantBang && !view.bang) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: labels.bangTexture(), depthTest: false }));
    s.renderOrder = 11;
    s.scale.set(0.8, 0.8, 1);
    s.position.set(view.bed.x, view.bangBase, view.bed.z);
    floorGroup.add(s);
    view.bang = s;
  } else if (!wantBang && view.bang) {
    floorGroup.remove(view.bang);
    view.bang = null;
  }
  view.blink = wantBang;
}

function setScreen(tk: Toolkit, view: BedView, level: 'low' | 'medium' | 'high' | null): void {
  const color = level === null ? tk.P.screenOff : tk.P[level === 'medium' ? 'med' : level];
  (view.glow.material as THREE.MeshBasicMaterial).color.set(color);
}
