/**
 * Click picking (PROMPT.md §10.5): a click on a patient (head or blanket) or on a person selects them. A
 * click is a pointer press and release that moved fewer than 5 pixels. Only meshes whose whole parent chain
 * is visible can be picked, so hidden floors never catch clicks.
 */
import * as THREE from 'three';

export const CLICK_MOVE_LIMIT_PX = 5;
/** A preferred entity (a patient in a bed) wins over someone standing in front of it when it is this close behind. */
export const PREFER_RANGE_M = 1.5;

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

  /** `nx`, `ny` are normalized device coordinates (-1..1). Returns the id of the first visible hit, except that an
   *  entity for which `prefer` is true and which lies within `PREFER_RANGE_M` behind it wins: a nurse standing at a
   *  bedside must not make the patient in the bed impossible to click. */
  pick(nx: number, ny: number, camera: THREE.Camera, targets: THREE.Object3D[], prefer: (id: string) => boolean = () => false): string | null {
    this.ray.setFromCamera(new THREE.Vector2(nx, ny), camera);
    const hits = this.ray.intersectObjects(targets, true);
    let first: { id: string; distance: number } | null = null;
    for (const h of hits) {
      if (!visibleChain(h.object)) continue;
      if (h.object instanceof THREE.LineSegments) continue;
      const id = entityIdOf(h.object);
      if (!id) continue;
      if (first === null) {
        if (prefer(id)) return id;
        first = { id, distance: h.distance };
      } else if (h.distance - first.distance > PREFER_RANGE_M) {
        break;
      } else if (id !== first.id && prefer(id)) {
        return id;
      }
    }
    return first?.id ?? null;
  }
}

/** True when a press-release pair counts as a click rather than a drag. */
export function isClick(movedPx: number): boolean {
  return movedPx < CLICK_MOVE_LIMIT_PX;
}
