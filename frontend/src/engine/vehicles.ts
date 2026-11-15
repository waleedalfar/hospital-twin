/**
 * Ambulances in the bay and the helicopter on the roof, driven by the live vehicle list of the hospital
 * (PROMPT.md §10.2). Ported from `ambulance()` in reference/engine/pulse3d.js. Vehicles that are away on a
 * call are not drawn here (the network map shows them on the road).
 */
import * as THREE from 'three';

import type { BuildingView } from './building';
import type { Layout } from './layout';
import type { Toolkit } from './materials';
import type { VehicleAtHospital } from '../state/types';

interface AmbulanceModel {
  group: THREE.Group;
  a: THREE.MeshBasicMaterial;
  b: THREE.MeshBasicMaterial;
  status: string;
}

export const SIREN_RED = '#e5484d';
export const SIREN_RED_DIM = '#5a1418';
export const SIREN_BLUE = '#3b6fd6';
export const SIREN_BLUE_DIM = '#14244a';

function buildAmbulance(tk: Toolkit, scene: THREE.Object3D): AmbulanceModel {
  const g = new THREE.Group();
  tk.box(2.2, 2.0, 3.2, tk.P.ambBody, 0, 1.3, -0.4, g);
  tk.box(2.2, 1.4, 1.4, tk.P.ambBody, 0, 1.0, 1.9, g);
  tk.box(2.0, 0.6, 0.05, tk.P.glass, 0, 1.35, 2.61, g, { outline: false });
  tk.box(2.26, 0.25, 4.6, tk.P.ambStripe, 0, 0.9, 0.3, g, { outline: false });
  for (const [x, z] of [[-1.05, -1.3], [1.05, -1.3], [-1.05, 1.5], [1.05, 1.5]] as const) tk.box(0.3, 0.6, 0.6, tk.P.monitor, x, 0.35, z, g);
  const a = new THREE.MeshBasicMaterial({ color: SIREN_RED });
  const b = new THREE.MeshBasicMaterial({ color: SIREN_BLUE });
  tk.box(0.4, 0.25, 0.3, a, -0.5, 2.42, 1.0, g, { outline: false, cast: false });
  tk.box(0.4, 0.25, 0.3, b, 0.5, 2.42, 1.0, g, { outline: false, cast: false });
  scene.add(g);
  return { group: g, a, b, status: '' };
}

export class VehicleLayer {
  private readonly ambulances = new Map<string, AmbulanceModel>();

  constructor(
    private readonly tk: Toolkit,
    private readonly scene: THREE.Object3D,
    private readonly layout: Layout,
    private readonly building: BuildingView,
  ) {}

  /** Show the vehicles that are on the hospital's grounds. */
  sync(vehicles: readonly VehicleAtHospital[]): void {
    const present = new Set<string>();
    for (const v of vehicles) {
      if (v.kind === 'helicopter') {
        if (this.building.heli) this.building.heli.visible = true;
        continue;
      }
      const slot = this.layout.outside.ambulance_slots.find((s) => s.id === v.slot);
      if (!slot) continue;
      present.add(v.id);
      let model = this.ambulances.get(v.id);
      if (!model) {
        model = buildAmbulance(this.tk, this.scene);
        this.ambulances.set(v.id, model);
      }
      model.group.position.set(slot.x, 0, slot.z);
      model.group.rotation.y = slot.rotation;
      model.status = v.status;
    }
    if (this.building.heli && !vehicles.some((v) => v.kind === 'helicopter')) this.building.heli.visible = false;
    for (const [id, model] of [...this.ambulances]) {
      if (present.has(id)) continue;
      this.scene.remove(model.group);
      this.ambulances.delete(id);
    }
  }

  /** Flash the lights of ambulances that are unloading. */
  update(time: number): void {
    const on = Math.floor(time * 6) % 2 === 0;
    for (const m of this.ambulances.values()) {
      const flashing = m.status === 'unloading';
      m.a.color.set(flashing && !on ? SIREN_RED_DIM : SIREN_RED);
      m.b.color.set(flashing && on ? SIREN_BLUE_DIM : SIREN_BLUE);
    }
  }

  /** Ids and slots of the ambulances currently drawn (debug and tests). */
  drawn(): { id: string; x: number; z: number }[] {
    return [...this.ambulances].map(([id, m]) => ({ id, x: m.group.position.x, z: m.group.position.z }));
  }
}
