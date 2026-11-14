/**
 * Turns live entities into things in the scene (PROMPT.md §10.6): characters for people who walk, stand or
 * sit; lying patients inside beds and on tables; markers, risk-colored monitors. Entities are created,
 * updated and removed by `sync()`; moves follow the server path between `depart` and `arrive`.
 */
import * as THREE from 'three';

import { setBedPatient, setRisk, type BedView } from './beds';
import { SLAB, skinColor, type Character, type CharacterFactory, type CharacterPose, type Role } from './characters';
import type { BuildingView } from './building';
import type { LabelFactory } from './labels';
import type { Layout, LayoutIndex } from './layout';
import type { Toolkit } from './materials';
import { parseTimes, positionAt } from './motion';
import type { Entity } from '../state/wsTypes';

export interface RenderedEntity {
  id: string;
  kind: Entity['kind'];
  floor: number | null;
  room: string | null;
  bed: string | null;
  position: { x: number; y: number; z: number };
  pose: string;
  mode: 'bed' | 'table' | 'character';
}

export interface LayerHost {
  floorY(level: number): number;
  floorVisible(level: number): boolean;
  carVisible(): boolean;
  xray(): boolean;
}

interface CharEntry {
  entity: Entity;
  character: Character;
  times: number[] | null;
  phase: number;
  /** Where the entity rests when it is not moving (from its location). */
  rest: { x: number; z: number; level: number; yaw: number; pose: CharacterPose } | null;
}

interface TableEntry {
  entity: Entity;
  group: THREE.Group;
  marker: THREE.Sprite;
  level: number;
}

function phaseOf(id: string): number {
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) % 997;
  return h / 100;
}

export class EntityLayer {
  private readonly chars = new Map<string, CharEntry>();
  private readonly tables = new Map<string, TableEntry>();
  private readonly bedOwner = new Map<string, string>();
  /** Problems found while placing entities (an entity with no place in the layout). Shown by the debug API. */
  readonly problems: string[] = [];
  private entities = new Map<string, Entity>();

  constructor(
    private readonly tk: Toolkit,
    private readonly labels: LabelFactory,
    private readonly factory: CharacterFactory,
    private readonly building: BuildingView,
    private readonly layout: Layout,
    private readonly idx: LayoutIndex,
    private readonly scene: THREE.Object3D,
    private readonly host: LayerHost,
  ) {}

  private isMoving(e: Entity, simNow: number): boolean {
    if (!e.move) return false;
    const arrive = Date.parse(e.move.arrive);
    return simNow < arrive;
  }

  /** Apply the full set of entities (a snapshot, or the store's state after events). */
  sync(entities: readonly Entity[], simNow: number): void {
    this.problems.length = 0;
    this.entities = new Map(entities.map((e) => [e.id, e]));
    const wantedBeds = new Map<string, Entity>();
    const seenChars = new Set<string>();
    const seenTables = new Set<string>();
    for (const e of entities) {
      const moving = this.isMoving(e, simNow);
      const spot = e.location.spot ? this.idx.spots.get(e.location.spot) : undefined;
      if (!moving && e.location.bed && this.idx.beds.has(e.location.bed)) {
        wantedBeds.set(e.location.bed, e);
      } else if (!moving && spot?.kind === 'table') {
        seenTables.add(e.id);
        this.ensureTable(e, spot.floor, spot.x, spot.z, spot.rotation);
      } else if (e.location.vehicle || e.location.floor === null) {
        continue; // inside a vehicle: not drawn in the building
      } else {
        seenChars.add(e.id);
        this.ensureChar(e);
      }
    }
    for (const id of [...this.chars.keys()]) if (!seenChars.has(id)) this.removeChar(id);
    for (const id of [...this.tables.keys()]) if (!seenTables.has(id)) this.removeTable(id);
    this.syncBeds(wantedBeds);
  }

  private syncBeds(wanted: Map<string, Entity>): void {
    this.bedOwner.clear();
    for (const [bedId, view] of this.building.beds) {
      const e = wanted.get(bedId);
      const floor = this.building.floors[view.bed.floor];
      if (!floor) continue;
      if (!e) {
        if (view.patientId !== null) setBedPatient(this.tk, this.factory, this.labels, view, floor.g, null, null);
        continue;
      }
      setBedPatient(this.tk, this.factory, this.labels, view, floor.g, e.id, e.appearance);
      for (const m of view.pickables) m.userData['entityId'] = e.id;
      setRisk(this.tk, this.labels, view, floor.g, e.risk?.level ?? null);
      this.bedOwner.set(bedId, e.id);
    }
  }

  private roleOf(e: Entity): Role {
    return e.kind;
  }

  private restOf(e: Entity): CharEntry['rest'] {
    const loc = e.location;
    if (loc.spot) {
      const seat = this.idx.seats.get(loc.spot);
      if (seat) {
        const fx = Math.sin(seat.rotation) * 0.05;
        const fz = Math.cos(seat.rotation) * 0.05;
        return { x: seat.x + fx, z: seat.z + fz, level: seat.floor, yaw: seat.rotation, pose: 'seated' };
      }
      const spot = this.idx.spots.get(loc.spot);
      if (spot) return { x: spot.x, z: spot.z, level: spot.floor, yaw: spot.rotation, pose: 'standing' };
    }
    return null;
  }

  private ensureChar(e: Entity): void {
    let entry = this.chars.get(e.id);
    if (!entry) {
      const character = this.factory.create(this.roleOf(e), e.appearance, this.scene);
      character.group.userData['entityId'] = e.id;
      character.group.name = `entity:${e.id}`;
      entry = { entity: e, character, times: null, phase: phaseOf(e.id), rest: null };
      this.chars.set(e.id, entry);
    }
    entry.entity = e;
    entry.times = e.move ? parseTimes(e.move.times) : null;
    entry.rest = this.restOf(e);
    if (!entry.rest && !e.move) this.problems.push(`${e.id} has no place: ${JSON.stringify(e.location)}`);
  }

  private removeChar(id: string): void {
    const entry = this.chars.get(id);
    if (!entry) return;
    if (entry.character.marker) this.labels.removeMarker(entry.character.marker);
    this.scene.remove(entry.character.group);
    this.chars.delete(id);
  }

  private ensureTable(e: Entity, level: number, x: number, z: number, rotation: number): void {
    const floor = this.building.floors[level];
    if (!floor) return;
    let entry = this.tables.get(e.id);
    if (!entry) {
      const group = new THREE.Group();
      group.position.set(x, SLAB + 0.55, z);
      group.rotation.y = rotation + Math.PI;
      floor.g.add(group);
      this.factory.createLying(e.appearance, group, 'table');
      group.userData['entityId'] = e.id;
      const marker = this.labels.marker(this.tk.mapC(this.tk.P.gown), floor.g, x, SLAB + 2.3, z, 0.6);
      entry = { entity: e, group, marker, level };
      this.tables.set(e.id, entry);
    }
    entry.entity = e;
  }

  private removeTable(id: string): void {
    const entry = this.tables.get(id);
    if (!entry) return;
    this.labels.removeMarker(entry.marker);
    entry.group.parent?.remove(entry.group);
    this.tables.delete(id);
  }

  /** Per frame: move walkers along their paths, place resting people, follow the floors, animate. */
  update(simNow: number, time: number): void {
    const e0 = this.layout.building.elevator;
    for (const entry of this.chars.values()) {
      const { entity, character } = entry;
      let x = 0;
      let z = 0;
      let level = 0;
      let yaw = character.group.rotation.y;
      let pose: CharacterPose = 'standing';
      let visible = true;
      if (entity.move && entry.times) {
        const p = positionAt(this.idx, entity.move.path, entry.times, simNow, yaw);
        ({ x, z, level, yaw } = p);
        pose = p.moving ? 'walking' : 'standing';
        if (p.riding) {
          visible = this.host.carVisible();
          pose = 'standing';
          x = (e0.x1 + e0.x2) / 2;
        }
        const arrived = simNow >= (entry.times[entry.times.length - 1] as number);
        if (arrived && entry.rest) {
          ({ x, z, level, yaw, pose } = entry.rest);
        }
      } else if (entry.rest) {
        ({ x, z, level, yaw, pose } = entry.rest);
      } else {
        visible = false;
      }
      if (character.pose !== pose) character.setPose(pose);
      character.group.position.x = x;
      character.group.position.z = z;
      character.group.rotation.y = yaw;
      const lo = Math.floor(level);
      const hi = Math.min(this.layout.building.levels, lo + 1);
      const frac = level - lo;
      const floorY = this.host.floorY(lo) + (this.host.floorY(hi) - this.host.floorY(lo)) * frac;
      character.animate(time, entry.phase, floorY);
      if (!(entity.move && !visible)) visible = visible && this.host.floorVisible(Math.round(level));
      character.group.visible = visible;
    }
    for (const t of this.tables.values()) t.group.visible = this.host.floorVisible(t.level);
  }

  /** Everything a click can hit. */
  pickTargets(): THREE.Object3D[] {
    const out: THREE.Object3D[] = [...this.building.beds.values()].flatMap((b) => b.pickables);
    for (const c of this.chars.values()) out.push(c.character.group);
    for (const t of this.tables.values()) out.push(t.group);
    return out;
  }

  /** The bed view that holds the entity with this id, if it lies in a bed. */
  bedOf(entityId: string): BedView | null {
    for (const [bedId, owner] of this.bedOwner) if (owner === entityId) return this.building.beds.get(bedId) ?? null;
    return null;
  }

  characterOf(entityId: string): Character | null {
    return this.chars.get(entityId)?.character ?? null;
  }

  entity(id: string): Entity | undefined {
    return this.entities.get(id);
  }

  /** Every rendered character with its world position (used by the debug API and the e2e tests). */
  rendered(): RenderedEntity[] {
    const out: RenderedEntity[] = [];
    for (const [id, c] of this.chars) {
      const p = c.character.group.position;
      out.push({
        id,
        kind: c.entity.kind,
        floor: c.entity.location.floor,
        room: c.entity.location.room ?? null,
        bed: null,
        position: { x: p.x, y: p.y, z: p.z },
        pose: c.character.pose,
        mode: 'character',
      });
    }
    for (const [bedId, id] of this.bedOwner) {
      const view = this.building.beds.get(bedId);
      const e = this.entities.get(id);
      if (!view || !e) continue;
      const w = new THREE.Vector3();
      view.group.getWorldPosition(w);
      out.push({ id, kind: e.kind, floor: view.bed.floor, room: view.bed.room, bed: bedId, position: { x: w.x, y: w.y, z: w.z }, pose: 'lying', mode: 'bed' });
    }
    for (const [id, t] of this.tables) {
      const w = new THREE.Vector3();
      t.group.getWorldPosition(w);
      out.push({ id, kind: t.entity.kind, floor: t.level, room: t.entity.location.room ?? null, bed: null, position: { x: w.x, y: w.y, z: w.z }, pose: 'lying', mode: 'table' });
    }
    return out.sort((a, b) => a.id.localeCompare(b.id));
  }

  /** Characters (standing, walking, seated) that exist, for the faceless audit. */
  allCharacters(): { id: string; character: Character }[] {
    return [...this.chars].map(([id, c]) => ({ id, character: c.character }));
  }

  /** Lying models in beds and on tables, for the faceless audit. */
  lyingModels(): { id: string; group: THREE.Object3D; skin: string }[] {
    const out: { id: string; group: THREE.Object3D; skin: string }[] = [];
    for (const view of this.building.beds.values()) {
      const e = view.patientId ? this.entities.get(view.patientId) : undefined;
      if (view.lying && e) out.push({ id: e.id, group: view.lying, skin: this.skinOf(e) });
    }
    for (const [id, t] of this.tables) out.push({ id, group: t.group, skin: this.skinOf(t.entity) });
    return out;
  }

  private skinOf(e: Entity): string {
    return this.tk.mapC(skinColor(e.appearance));
  }
}
