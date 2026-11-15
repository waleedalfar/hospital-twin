/**
 * Highlights the entities an answer is about (PROMPT.md §9.1): a pulsing ring on the floor under each one and an
 * X-ray marker above it that is drawn through walls. Pure scene objects, no renderer, so it can be unit tested.
 */
import * as THREE from 'three';

import type { RenderedEntity } from './entities';

export const PULSE_HZ = 1.3;
export const RING_COLOR = 0xffd166;

/** The ring's scale at `time` seconds: it breathes between 1 and 1.35 times its size. */
export function pulseScale(time: number): number {
  return 1 + 0.175 * (1 + Math.sin(time * PULSE_HZ * 2 * Math.PI));
}

interface Mark {
  group: THREE.Group;
  ring: THREE.Mesh;
  marker: THREE.Mesh;
}

export class Highlighter {
  private readonly marks = new Map<string, Mark>();
  private ids: string[] = [];
  readonly group = new THREE.Group();

  constructor(parent: THREE.Object3D) {
    this.group.name = 'highlights';
    parent.add(this.group);
  }

  /** Replace the highlighted ids. An empty list clears all highlights. */
  set(ids: readonly string[]): void {
    this.ids = [...new Set(ids)];
    for (const [id, mark] of [...this.marks]) {
      if (!this.ids.includes(id)) {
        this.group.remove(mark.group);
        mark.ring.geometry.dispose();
        mark.marker.geometry.dispose();
        this.marks.delete(id);
      }
    }
  }

  get highlighted(): readonly string[] {
    return this.ids;
  }

  /** How many rings are currently in the scene (some ids may belong to entities that are not drawn). */
  get drawn(): number {
    return [...this.marks.values()].filter((m) => m.group.visible).length;
  }

  private make(id: string): Mark {
    const group = new THREE.Group();
    group.name = `highlight-${id}`;
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.55, 0.75, 24),
      new THREE.MeshBasicMaterial({ color: RING_COLOR, side: THREE.DoubleSide, transparent: true, opacity: 0.95 }),
    );
    ring.rotation.x = -Math.PI / 2;
    const marker = new THREE.Mesh(new THREE.ConeGeometry(0.28, 0.6, 4), new THREE.MeshBasicMaterial({ color: RING_COLOR, depthTest: false, transparent: true }));
    marker.rotation.x = Math.PI; // a downward arrow
    marker.position.y = 2.6;
    marker.renderOrder = 999;
    group.add(ring, marker);
    this.group.add(group);
    const mark = { group, ring, marker };
    this.marks.set(id, mark);
    return mark;
  }

  /** Place the rings under the entities that are drawn (hidden floors give hidden rings) and pulse them. */
  update(rendered: readonly RenderedEntity[], time: number, floorVisible: (level: number) => boolean = () => true): void {
    const byId = new Map(rendered.map((r) => [r.id, r]));
    for (const id of this.ids) {
      const r = byId.get(id);
      const mark = this.marks.get(id) ?? (r ? this.make(id) : undefined);
      if (!mark) continue;
      mark.group.visible = r !== undefined && (r.floor === null || floorVisible(r.floor));
      if (!r) continue;
      mark.group.position.set(r.position.x, r.position.y + 0.08, r.position.z);
      const s = pulseScale(time);
      mark.ring.scale.set(s, s, s);
      mark.marker.position.y = 2.6 + 0.15 * Math.sin(time * 4);
    }
  }
}
