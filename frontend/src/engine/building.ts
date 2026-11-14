/**
 * The hospital building, built from shared/layout.json (PROMPT.md §3, §10.2): slabs, room floors, walls,
 * exterior walls with window bands, stairs, the glass elevator shaft, furniture, beds, the roof with its
 * helipad and helicopter, the street, the ambulance bay, parking and trees. Ported from the floor builders
 * in reference/engine/pulse3d.js; positions come from the layout instead of being hardcoded.
 */
import * as THREE from 'three';

import { buildBed, type BedView } from './beds';
import { SLAB } from './characters';
import { buildProp, chair } from './furniture';
import type { LabelFactory, LabelSprite } from './labels';
import { LayoutIndex, type Floor, type Layout, type Room } from './layout';
import type { Toolkit } from './materials';
import { PARKED_CARS, PARKING_LOT, SIDEWALK, TREES } from './scenery';
import { exteriorSpans, interiorWalls } from './walls';

export const FLOOR_HEIGHT = 3.4;
export const WALL_HEIGHT = 3.0;
const EXPLODED_GAP = 6;
const XRAY_FLOOR_GAP = 3.5;

export interface FloorView {
  level: number;
  g: THREE.Group;
  labels: Map<string, LabelSprite>;
  /** Current and target height (the floors ease apart in exploded and X-ray views). */
  y: number;
  ty: number;
  beds: BedView[];
}

export interface BuildingView {
  floors: FloorView[];
  roof: THREE.Group;
  car: THREE.Group;
  carMaterial: THREE.Material;
  rotor: THREE.Group | null;
  heli: THREE.Object3D | null;
  entranceSign: LabelSprite | null;
  beds: Map<string, BedView>;
  streetCar: THREE.Group;
  environment: THREE.Group;
  /** Meshes that must stay out of X-ray processing (none today; reserved). */
  index: LayoutIndex;
}

/** Palette key for a room's floor color (the layout stores the prototype's key names). */
function floorColor(tk: Toolkit, room: Room): string {
  const key = room.color as keyof typeof tk.P;
  const color = tk.P[key];
  if (!color) throw new Error(`Room ${room.id} has unknown floor color key ${room.color}`);
  return color;
}

function floorRect(tk: Toolkit, g: THREE.Group, x1: number, x2: number, z1: number, z2: number, color: string): void {
  tk.box(x2 - x1, 0.02, z2 - z1, tk.tileMat(color, x2 - x1, z2 - z1, 2), (x1 + x2) / 2, SLAB + 0.01, (z1 + z2) / 2, g, {
    cast: false,
    outline: false,
    shell: 'floor',
  });
}

function wallSegment(tk: Toolkit, g: THREE.Group, axis: 'x' | 'z', at: number, lo: number, hi: number): void {
  const len = hi - lo;
  const mid = (lo + hi) / 2;
  if (axis === 'x') {
    tk.box(len, WALL_HEIGHT, 0.3, tk.P.wallInt, mid, SLAB + WALL_HEIGHT / 2, at, g, { shell: 'wall' });
    tk.box(len, 0.12, 0.36, tk.P.cap, mid, SLAB + WALL_HEIGHT + 0.06, at, g, { outline: false, shell: 'cap' });
  } else {
    tk.box(0.3, WALL_HEIGHT, len, tk.P.wallInt, at, SLAB + WALL_HEIGHT / 2, mid, g, { shell: 'wall' });
    tk.box(0.36, 0.12, len, tk.P.cap, at, SLAB + WALL_HEIGHT + 0.06, mid, g, { outline: false, shell: 'cap' });
  }
}

/** An exterior wall with a lower band, an upper band and a glass band with mullions. */
function extWall(tk: Toolkit, g: THREE.Group, axis: 'x' | 'z', fixed: number, a: number, b: number, lit: THREE.Material[]): void {
  const len = b - a;
  const mid = (a + b) / 2;
  const put = (h: number, y: number, color: string, mat?: THREE.Material): THREE.Mesh =>
    axis === 'x'
      ? tk.box(len, h, 0.4, mat ?? color, mid, y, fixed, g, { shell: 'wall' })
      : tk.box(0.4, h, len, mat ?? color, fixed, y, mid, g, { shell: 'wall' });
  put(1.0, SLAB + 0.5, tk.P.wallExt);
  put(0.6, SLAB + WALL_HEIGHT - 0.3, tk.P.wallExt2);
  const night = tk.st.night ? tk.B(tk.P.glassLit) : undefined;
  const glass = put(1.4, SLAB + 1.7, tk.P.glass, night);
  if (night) lit.push(glass.material as THREE.Material);
  for (let p = a + 2.5; p < b - 0.5; p += 2.5) {
    if (axis === 'x') tk.box(0.25, 1.4, 0.46, tk.P.wallExt, p, SLAB + 1.7, fixed, g, { outline: false, shell: 'wall' });
    else tk.box(0.46, 1.4, 0.25, tk.P.wallExt, fixed, SLAB + 1.7, p, g, { outline: false, shell: 'wall' });
  }
}

function buildFloor(
  tk: Toolkit,
  layout: Layout,
  floor: Floor,
  scene: THREE.Object3D,
  rotorOut: { rotor: THREE.Group | null },
): FloorView {
  const g = new THREE.Group();
  g.name = `floor:${floor.level}`;
  scene.add(g);
  const view: FloorView = { level: floor.level, g, labels: new Map(), y: floor.level * FLOOR_HEIGHT, ty: floor.level * FLOOR_HEIGHT, beds: [] };
  g.position.y = view.y;
  const fp = layout.building.footprint;
  tk.box(fp.x2 - fp.x1 + 0.4, SLAB, fp.z2 - fp.z1 + 0.4, tk.P.slab, 0, SLAB / 2, 0, g, { cast: floor.level > 0, shell: 'floor' });
  for (const room of floor.rooms) {
    if (room.kind === 'outside' || room.kind === 'roof') continue;
    const r = room.rect;
    floorRect(tk, g, r.x1, r.x2, r.z1, r.z2, floorColor(tk, room));
  }
  for (const w of interiorWalls(layout, floor)) wallSegment(tk, g, w.axis, w.at, w.lo, w.hi);
  const lit: THREE.Material[] = [];
  const bw = fp.z2 + 0.2;
  for (const [lo, hi] of exteriorSpans(layout, floor, 'south')) extWall(tk, g, 'x', bw, lo, hi, lit);
  extWall(tk, g, 'x', -bw, fp.x1 - 0.4, fp.x2 + 0.4, lit);
  extWall(tk, g, 'z', fp.x1 - 0.2, fp.z1, fp.z2, lit);
  extWall(tk, g, 'z', fp.x2 + 0.2, fp.z1, fp.z2, lit);
  // The glass elevator shaft (the car itself lives outside the floors).
  const e = layout.building.elevator;
  tk.box(0.1, WALL_HEIGHT, e.z2 - e.z1, tk.glass(), e.x1, SLAB + WALL_HEIGHT / 2, 0, g, { cast: false });
  tk.box(3, 0.1, 0.1, tk.P.cap, (e.x1 + e.x2) / 2, SLAB + WALL_HEIGHT, e.z1, g, { outline: false });
  const counts = new Map<string, number>();
  for (const p of layout.props.filter((x) => x.floor === floor.level)) {
    const index = counts.get(p.type) ?? 0;
    counts.set(p.type, index + 1);
    buildProp({ tk, parent: g, index, rotorOut }, p);
  }
  return view;
}

function carShape(tk: Toolkit, parent: THREE.Object3D, color: string, x: number, z: number): void {
  tk.box(1.8, 0.9, 3.6, color, x, 0.55, z, parent);
  tk.box(1.6, 0.6, 2, color, x, 1.3, z - 0.2, parent);
  tk.box(1.62, 0.45, 0.05, tk.P.glass, x, 1.3, z + 0.82, parent, { outline: false });
}

function buildEnvironment(tk: Toolkit, layout: Layout, scene: THREE.Object3D): THREE.Group {
  const env = new THREE.Group();
  env.name = 'environment';
  scene.add(env);
  const o = { cast: false, outline: false } as const;
  tk.box(220, 0.2, 220, tk.st.texture ? tk.tileMat(tk.P.grass, 220, 220, 4) : tk.P.grass, 0, -0.1, 0, env, o);
  const street = layout.outside.street_z;
  tk.box(220, 0.06, layout.outside.street_width, tk.P.road, 0, 0.03, street, env, o);
  for (let dx = -108; dx < 110; dx += 6) tk.box(3, 0.08, 0.3, tk.P.dash, dx, 0.05, street, env, o);
  tk.box(SIDEWALK.w, 0.08, SIDEWALK.d, tk.P.sidewalk, 0, 0.04, SIDEWALK.z, env, { cast: false });
  const bay = layout.outside.ambulance_bay;
  tk.box(bay.x2 - bay.x1, 0.06, bay.z2 - bay.z1, tk.P.asphalt, (bay.x1 + bay.x2) / 2, 0.03, (bay.z1 + bay.z2) / 2, env, o);
  tk.box(PARKING_LOT.w, 0.06, PARKING_LOT.d, tk.P.asphalt, PARKING_LOT.x, 0.03, PARKING_LOT.z, env, o);
  for (const [color, x, z] of PARKED_CARS) carShape(tk, env, color, x, z);
  for (const [x, z] of TREES) {
    tk.box(0.6, 1.4, 0.6, tk.P.trunk, x, 0.7, z, env);
    tk.box(2.6, 2.2, 2.6, tk.P.tree, x, 2.4, z, env);
    tk.box(1.6, 1.0, 1.6, tk.P.tree2, x, 4.0, z, env);
  }
  return env;
}

export function buildBuilding(
  tk: Toolkit,
  labels: LabelFactory,
  layout: Layout,
  hospitalName: string,
  scene: THREE.Object3D,
): BuildingView {
  const index = new LayoutIndex(layout);
  const environment = buildEnvironment(tk, layout, scene);
  const rotorOut: { rotor: THREE.Group | null } = { rotor: null };
  const floors = layout.floors.filter((f) => f.level < layout.building.levels).map((f) => buildFloor(tk, layout, f, scene, rotorOut));

  const beds = new Map<string, BedView>();
  for (const bed of layout.beds) {
    const floor = floors[bed.floor];
    if (!floor) throw new Error(`Bed ${bed.id} is on missing floor ${bed.floor}`);
    const bedView = buildBed(tk, bed, floor.g);
    floor.beds.push(bedView);
    beds.set(bed.id, bedView);
  }

  // Room labels (text only; counts are filled in from live state) and the entrance.
  for (const floor of layout.floors) {
    const view = floors[floor.level];
    if (!view) continue;
    for (const room of floor.rooms.filter((r) => r.kind === 'room')) {
      view.labels.set(room.id, labels.label(room.name.toUpperCase(), '', '', room.label_x, SLAB + WALL_HEIGHT + 1.2, room.label_z, 5.5, view.g));
    }
  }
  const ground = floors[0];
  let entranceSign: LabelSprite | null = null;
  const entrance = layout.floors[0]?.doors.find((d) => d.kind === 'entrance');
  if (ground && entrance) {
    const cx = (entrance.start + entrance.end) / 2;
    tk.box(6, 0.5, 1.2, tk.P.ambStripe, cx, SLAB + WALL_HEIGHT - 0.2, entrance.at + 1, ground.g, { shell: 'wall' });
    entranceSign = labels.label(hospitalName.toUpperCase(), '', '', cx, SLAB + WALL_HEIGHT + 0.9, entrance.at + 1.4, 8, ground.g);
    ground.labels.set('__entrance__', entranceSign);
  }

  // Roof.
  const fp = layout.building.footprint;
  const roof = new THREE.Group();
  roof.name = 'roof';
  scene.add(roof);
  tk.box(fp.x2 - fp.x1 + 0.4, 0.4, fp.z2 - fp.z1 + 0.4, tk.P.roof, 0, 0.2, 0, roof, { shell: 'floor' });
  tk.box(fp.x2 - fp.x1 + 0.4, 0.8, 0.4, tk.P.wallExt2, 0, 0.8, fp.z1 - 0.2, roof, { shell: 'wall' });
  tk.box(fp.x2 - fp.x1 + 0.4, 0.8, 0.4, tk.P.wallExt2, 0, 0.8, fp.z2 + 0.2, roof, { shell: 'wall' });
  tk.box(0.4, 0.8, fp.z2 - fp.z1 + 0.4, tk.P.wallExt2, fp.x1 - 0.2, 0.8, 0, roof, { shell: 'wall' });
  tk.box(0.4, 0.8, fp.z2 - fp.z1 + 0.4, tk.P.wallExt2, fp.x2 + 0.2, 0.8, 0, roof, { shell: 'wall' });
  const roofCounts = new Map<string, number>();
  for (const p of layout.props.filter((x) => x.floor === layout.roof.level)) {
    const idx = roofCounts.get(p.type) ?? 0;
    roofCounts.set(p.type, idx + 1);
    buildProp({ tk, parent: roof, index: idx, rotorOut }, p);
  }
  roof.position.y = layout.building.levels * FLOOR_HEIGHT;
  const heli = roof.getObjectByName('helicopter') ?? null;

  // Elevator car.
  const car = new THREE.Group();
  car.name = 'elevator-car';
  scene.add(car);
  const e = layout.building.elevator;
  const carBox = tk.box(2.6, 2.8, 3.4, tk.P.machine, 0, 1.4, 0, car, { shell: 'wall' });
  tk.box(2.4, 0.1, 3.2, tk.P.slab, 0, 0.05, 0, car, { outline: false });
  car.position.set((e.x1 + e.x2) / 2, SLAB, 0);

  // The car that drives along the street.
  const streetCar = new THREE.Group();
  streetCar.name = 'street-car';
  scene.add(streetCar);
  carShape(tk, streetCar, '#c9d2e3', 0, 0);

  return {
    floors,
    roof,
    car,
    carMaterial: carBox.material as THREE.Material,
    rotor: rotorOut.rotor,
    heli,
    entranceSign,
    beds,
    streetCar,
    environment,
    index,
  };
}

/** Target heights of the floors for a view, in meters. */
export function floorTargets(levels: number, view: 'all' | number, exploded: boolean, xray: boolean): number[] {
  const gap = exploded ? FLOOR_HEIGHT + EXPLODED_GAP : xray && view === 'all' ? FLOOR_HEIGHT + XRAY_FLOOR_GAP : FLOOR_HEIGHT;
  return Array.from({ length: levels }, (_, i) => i * gap);
}

export function roofTarget(levels: number, view: 'all' | number, exploded: boolean, xray: boolean): number {
  const top = (levels - 1) * (exploded ? FLOOR_HEIGHT + EXPLODED_GAP : xray && view === 'all' ? FLOOR_HEIGHT + XRAY_FLOOR_GAP : FLOOR_HEIGHT) + FLOOR_HEIGHT;
  return exploded ? top + EXPLODED_GAP : xray && view === 'all' ? top + XRAY_FLOOR_GAP : top;
}

export { chair };
