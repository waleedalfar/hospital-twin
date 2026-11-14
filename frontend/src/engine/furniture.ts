/**
 * Furniture and fixtures, placed from the layout's `props` list. Sizes and looks are ported from the room
 * builders in reference/engine/pulse3d.js; positions come from shared/layout.json.
 */
import * as THREE from 'three';

import { SLAB } from './characters';
import type { Prop } from './layout';
import { MEDS } from './palette';
import type { Toolkit } from './materials';

const WH = 3.0;

export interface FurnitureCtx {
  tk: Toolkit;
  /** Group of the floor the prop stands on (or the roof group). */
  parent: THREE.Object3D;
  /** Index of the prop among props of its type (rug colors alternate by position). */
  index: number;
  rotorOut: { rotor: THREE.Group | null };
}

export function chair(tk: Toolkit, parent: THREE.Object3D, x: number, z: number, rot: number): THREE.Group {
  const g = new THREE.Group();
  g.position.set(x, SLAB, z);
  g.rotation.y = rot;
  parent.add(g);
  tk.box(0.6, 0.1, 0.6, tk.P.chair, 0, 0.6, 0, g);
  tk.box(0.6, 0.6, 0.1, tk.P.chair, 0, 0.95, -0.3, g);
  tk.box(0.45, 0.5, 0.45, tk.P.chairBase, 0, 0.3, 0, g);
  return g;
}

/** Stairs: eight steps climbing along +z, in the corridor's west end. */
function stairs(c: FurnitureCtx, p: Prop): void {
  for (let s = 0; s < 8; s++) {
    c.tk.box(1.2, 0.2 + s * 0.4, 0.5, c.tk.P.slab, p.x, SLAB + (0.2 + s * 0.4) / 2, p.z - 1.55 + s * 0.45, c.parent, { shell: 'wall' });
  }
}

type Builder = (c: FurnitureCtx, p: Prop) => void;

const BUILDERS: Record<string, Builder> = {
  chair: (c, p) => {
    chair(c.tk, c.parent, p.x, p.z, p.rotation);
  },
  curtain: (c, p) => {
    c.tk.box(0.05, 2.0, 2.4, c.tk.P.curtain, p.x, SLAB + 1.15, p.z, c.parent, { shell: 'wall' });
  },
  ct_scanner: (c, p) => {
    c.tk.box(2.8, 2.4, 1.0, c.tk.P.machine, p.x, SLAB + 1.2, p.z, c.parent);
    c.tk.box(1.2, 1.2, 1.05, c.tk.P.monitor, p.x, SLAB + 1.3, p.z, c.parent, { outline: false });
  },
  ct_table: (c, p) => {
    c.tk.box(0.7, 0.7, 3.2, c.tk.P.machineDark, p.x, SLAB + 0.35, p.z, c.parent);
    c.tk.box(0.8, 0.12, 3.2, c.tk.P.sheet, p.x, SLAB + 0.76, p.z, c.parent);
  },
  shelf: (c, p) => {
    c.tk.box(0.7, 2.2, 4, c.tk.P.wood, p.x, SLAB + 1.1, p.z, c.parent);
    for (let row = 0; row < 3; row++) {
      for (let k = 0; k < 5; k++) {
        const color = MEDS[(row + k + Math.round(p.x)) % 4] ?? MEDS[0];
        c.tk.box(0.2, 0.3, 0.5, color, p.x + 0.4, SLAB + 0.5 + row * 0.7, p.z - 1.6 + k * 0.8, c.parent, { outline: false });
      }
    }
  },
  triage_desk: (c, p) => {
    c.tk.box(3, 1.0, 0.9, c.tk.P.wood, p.x, SLAB + 0.5, p.z, c.parent);
  },
  reception_desk: (c, p) => {
    c.tk.box(0.8, 1.0, 4, c.tk.P.wood, p.x, SLAB + 0.5, p.z, c.parent);
    c.tk.box(1.0, 0.1, 4.2, c.tk.P.woodDark, p.x, SLAB + 1.05, p.z, c.parent);
  },
  plant: (c, p) => {
    c.tk.box(0.6, 0.6, 0.6, c.tk.P.pot, p.x, SLAB + 0.3, p.z, c.parent);
    c.tk.box(0.9, 1.0, 0.9, c.tk.P.plant, p.x, SLAB + 1.1, p.z, c.parent);
  },
  or_table: (c, p) => {
    c.tk.box(1.0, 0.9, 2.4, c.tk.P.machineDark, p.x, SLAB + 0.45, p.z, c.parent);
    c.tk.box(1.0, 0.12, 2.2, c.tk.P.sheet, p.x, SLAB + 0.96, p.z, c.parent);
  },
  or_lamp: (c, p) => {
    c.tk.box(0.1, 1.4, 0.1, c.tk.P.pole, p.x, SLAB + WH - 0.7, p.z, c.parent, { outline: false });
    c.tk.box(1.4, 0.25, 1.4, c.tk.P.machine, p.x, SLAB + 2.1, p.z, c.parent);
    c.tk.box(1.1, 0.06, 1.1, c.tk.B(c.tk.P.lamp), p.x, SLAB + 1.96, p.z, c.parent, { outline: false, cast: false });
  },
  anesthesia_machine: (c, p) => {
    c.tk.box(0.8, 1.6, 0.8, c.tk.P.machineDark, p.x, SLAB + 0.8, p.z, c.parent);
  },
  glass_partition: (c, p) => {
    c.tk.box(0.06, 2.4, 2.6, c.tk.glass(), p.x, SLAB + 1.2, p.z, c.parent, { cast: false });
  },
  lab_bench: (c, p) => {
    c.tk.box(12, 0.9, 1.0, c.tk.P.machine, p.x, SLAB + 0.45, p.z, c.parent);
    for (let x = p.x - 4.5; x < p.x + 5; x += 2.5) c.tk.box(0.3, 0.5, 0.3, c.tk.P.machineDark, x, SLAB + 1.15, p.z, c.parent);
  },
  couch: (c, p) => {
    c.tk.box(4, 0.7, 1.2, c.tk.P.couch, p.x, SLAB + 0.35, p.z - 0.15, c.parent);
    c.tk.box(4, 0.8, 0.3, c.tk.P.couch, p.x, SLAB + 0.9, p.z + 0.45, c.parent);
  },
  coffee_table: (c, p) => {
    c.tk.box(1.8, 0.5, 1.0, c.tk.P.wood, p.x, SLAB + 0.25, p.z, c.parent);
  },
  vending_machine: (c, p) => {
    c.tk.box(1.2, 2.2, 0.8, c.tk.P.machineDark, p.x, SLAB + 1.1, p.z, c.parent);
    c.tk.box(0.9, 1.4, 0.05, c.tk.B(c.tk.P.vend), p.x, SLAB + 1.3, p.z - 0.43, c.parent, { outline: false, cast: false });
  },
  prayer_rug: (c, p) => {
    const colors = [c.tk.P.rug1, c.tk.P.rug2, c.tk.P.rug3];
    const rr = Math.floor(c.index / 4);
    const rc = c.index % 4;
    c.tk.box(1.4, 0.03, 2.4, colors[(rr + rc) % 3] ?? c.tk.P.rug1, p.x, SLAB + 0.03, p.z, c.parent, { cast: false });
    c.tk.box(1.0, 0.035, 0.3, c.tk.P.rug3, p.x, SLAB + 0.04, p.z - 0.9, c.parent, { cast: false, outline: false });
  },
  shoe_shelf: (c, p) => {
    c.tk.box(2.4, 0.8, 0.5, c.tk.P.wood, p.x, SLAB + 0.4, p.z, c.parent);
  },
  admin_desk: (c, p) => {
    c.tk.box(2.2, 0.8, 1.0, c.tk.P.wood, p.x, SLAB + 0.4, p.z, c.parent);
    c.tk.box(0.8, 0.5, 0.08, c.tk.P.monitor, p.x, SLAB + 1.1, p.z - 0.3, c.parent);
    c.tk.box(0.7, 0.4, 0.09, c.tk.B(c.tk.P.vend), p.x, SLAB + 1.1, p.z - 0.28, c.parent, { outline: false, cast: false });
  },
  stairs,
  hvac: (c, p) => {
    c.tk.box(3, 1.4, 2, c.tk.P.machineDark, p.x, 1.1, p.z, c.parent);
    c.tk.box(1.4, 0.2, 1.4, c.tk.P.pole, p.x, 1.9, p.z, c.parent);
  },
  elevator_machine_room: (c, p) => {
    c.tk.box(3, WH + 1.6, 4, c.tk.P.wallExt2, p.x, (WH + 1.6) / 2, p.z, c.parent, { shell: 'wall' });
  },
  helipad: (c, p) => {
    const m = c.tk.P.helipadMark;
    c.tk.box(p.w, 0.06, p.d, c.tk.P.helipad, p.x, 0.43, p.z, c.parent, { cast: false, shell: 'floor' });
    c.tk.box(0.8, 0.07, 5, m, p.x - 1.6, 0.45, p.z, c.parent, { cast: false, outline: false });
    c.tk.box(0.8, 0.07, 5, m, p.x + 1.6, 0.45, p.z, c.parent, { cast: false, outline: false });
    c.tk.box(2.4, 0.07, 0.8, m, p.x, 0.45, p.z, c.parent, { cast: false, outline: false });
  },
  helicopter: (c, p) => {
    const tk = c.tk;
    const heli = new THREE.Group();
    heli.position.set(p.x, 0.45, p.z);
    heli.name = 'helicopter';
    c.parent.add(heli);
    tk.box(2.0, 1.6, 3.2, tk.P.heli, 0, 1.2, 0, heli);
    tk.box(1.8, 0.8, 1.2, tk.P.glass, 0, 1.4, 1.4, heli, { outline: false });
    tk.box(0.5, 0.5, 3.6, tk.P.heli, 0, 1.4, -3.2, heli);
    tk.box(0.1, 1.0, 0.8, tk.P.heli, 0.3, 1.8, -4.8, heli);
    tk.box(0.15, 0.15, 3.4, tk.P.heliDark, -0.8, 0.15, 0, heli);
    tk.box(0.15, 0.15, 3.4, tk.P.heliDark, 0.8, 0.15, 0, heli);
    const rotor = new THREE.Group();
    rotor.position.set(0, 2.2, 0);
    heli.add(rotor);
    tk.box(8, 0.06, 0.35, tk.P.heliDark, 0, 0, 0, rotor, { cast: false });
    tk.box(0.35, 0.06, 8, tk.P.heliDark, 0, 0, 0, rotor, { cast: false });
    c.rotorOut.rotor = rotor;
    heli.userData['home'] = { x: p.x, y: 0.45, z: p.z };
  },
};

/** Prop types this module knows how to draw. Every type in the layout must be listed (a test checks it). */
export const PROP_TYPES = Object.keys(BUILDERS);

export function buildProp(c: FurnitureCtx, p: Prop): void {
  const build = BUILDERS[p.type];
  if (!build) throw new Error(`No builder for prop type ${p.type}`);
  build(c, p);
}
