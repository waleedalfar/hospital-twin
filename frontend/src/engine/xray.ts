/**
 * X-ray (PROMPT.md §10.5): walls drop to 7% opacity, floors to 55%, caps to 25%, outlines go faint, shell
 * meshes stop casting shadows, and markers float over every person. Transparent shell materials need
 * `depthWrite: false` and no shadow casting. Ported from `setXray()` in reference/engine/pulse3d.js.
 */
import * as THREE from 'three';

import type { LabelFactory } from './labels';
import type { ShellKind, Toolkit } from './materials';

export const XRAY_OPACITY: Record<ShellKind, number> = { wall: 0.07, floor: 0.55, cap: 0.25 };

export class Xray {
  on = false;
  private readonly cache = new Map<string, THREE.Material>();

  constructor(
    private readonly tk: Toolkit,
    private readonly labels: LabelFactory,
  ) {}

  /** Switch X-ray on or off. Returns true if the state changed. */
  set(on: boolean): boolean {
    if (on === this.on) return false;
    this.on = on;
    for (const m of this.tk.shellMeshes) {
      const kind = m.userData['shell'] as ShellKind;
      if (on) {
        if (!m.userData['orig']) m.userData['orig'] = m.material;
        const orig = m.userData['orig'] as THREE.Material;
        const key = orig.uuid + kind;
        let mat = this.cache.get(key);
        if (!mat) {
          mat = orig.clone();
          mat.transparent = true;
          mat.opacity = XRAY_OPACITY[kind];
          mat.depthWrite = false;
          this.cache.set(key, mat);
        }
        m.material = mat;
        m.castShadow = false;
        m.children.forEach((c) => {
          if (c instanceof THREE.LineSegments) c.material = this.tk.faintLine;
        });
      } else if (m.userData['orig']) {
        m.material = m.userData['orig'] as THREE.Material;
        m.castShadow = true;
        m.children.forEach((c) => {
          if (c instanceof THREE.LineSegments) c.material = this.tk.lineMat;
        });
      }
    }
    this.labels.setMarkersVisible(on);
    return true;
  }

  /** Opacity of the first wall and floor mesh, for tests and the debug API. */
  opacities(): { wall: number; floor: number } {
    const read = (kind: ShellKind): number => {
      const m = this.tk.shellMeshes.find((s) => s.userData['shell'] === kind);
      const mat = m?.material;
      return mat && !Array.isArray(mat) ? mat.opacity : 1;
    };
    return { wall: read('wall'), floor: read('floor') };
  }
}
