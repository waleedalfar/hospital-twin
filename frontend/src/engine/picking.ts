/**
 * Click picking (PROMPT.md §10.5): a click on a patient (head or blanket) or on a person selects them. A
 * click is a pointer press and release that moved fewer than 5 pixels. Only meshes whose whole parent chain
 * is visible can be picked, so hidden floors never catch clicks.
 */
import * as THREE from 'three';

export const CLICK_MOVE_LIMIT_PX = 5;

export function visibleChain(o: THREE.Object3D | null): boolean {
  for (let cur = o; cur; cur = cur.parent) if (!cur.visible) return false;
  return true;
}

/** Entity id stored on a picked mesh or one of its parents (`userData.entityId`), if any. */
export function entityIdOf(o: THREE.Object3D | null): string | null {
  for (let cur = o; cur; cur = cur.parent) {
    const id = cur.userData['entityId'] as string | undefined;
    if (id) return id;
  }
  return null;
}

export class Picker {
  private readonly ray = new THREE.Raycaster();

  /** `nx`, `ny` are normalized device coordinates (-1..1). Returns the id of the first visible hit. */
  pick(nx: number, ny: number, camera: THREE.Camera, targets: THREE.Object3D[]): string | null {
    this.ray.setFromCamera(new THREE.Vector2(nx, ny), camera);
    const hits = this.ray.intersectObjects(targets, true);
    for (const h of hits) {
      if (!visibleChain(h.object)) continue;
      if (h.object instanceof THREE.LineSegments) continue;
      const id = entityIdOf(h.object);
      if (id) return id;
    }
    return null;
  }
}

/** True when a press-release pair counts as a click rather than a drag. */
export function isClick(movedPx: number): boolean {
  return movedPx < CLICK_MOVE_LIMIT_PX;
}
