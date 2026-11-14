/** Typed access to shared/layout.json, the single source of truth for the building (PROMPT.md §3). */
import layoutJson from '../../../shared/layout.json';

export interface Rect {
  x1: number;
  x2: number;
  z1: number;
  z2: number;
}
export type Facing = 'north' | 'south' | 'east' | 'west';
export interface Room {
  id: string;
  name: string;
  floor: number;
  unit: string;
  kind: 'room' | 'corridor' | 'elevator' | 'outside' | 'roof';
  rect: Rect;
  color: string;
  label_x: number;
  label_z: number;
}
export interface Door {
  id: string;
  floor: number;
  rooms: [string, string];
  wall: string;
  axis: 'x' | 'z';
  at: number;
  start: number;
  end: number;
  kind: 'door' | 'opening' | 'entrance' | 'elevator';
  node: string;
}
export interface Floor {
  level: number;
  name: string;
  rooms: Room[];
  doors: Door[];
}
export interface Bed {
  id: string;
  room: string;
  floor: number;
  unit: string;
  x: number;
  z: number;
  rotation: number;
  head: Facing;
  spot: string;
}
export interface Seat {
  id: string;
  room: string;
  floor: number;
  kind: 'waiting' | 'triage' | 'lounge' | 'desk';
  x: number;
  z: number;
  facing: Facing;
  rotation: number;
  node: string;
}
export interface Spot {
  id: string;
  room: string;
  floor: number;
  kind: string;
  x: number;
  z: number;
  facing: Facing;
  rotation: number;
  bed: string | null;
  node: string;
}
export interface Prop {
  id: string;
  type: string;
  room: string;
  floor: number;
  x: number;
  z: number;
  w: number;
  d: number;
  rotation: number;
  blocks: boolean;
  target: string | null;
}
export interface GraphNode {
  id: string;
  floor: number;
  x: number;
  z: number;
  room: string;
}
export interface AmbulanceSlot {
  id: string;
  x: number;
  z: number;
  rotation: number;
  spot: string;
}
export interface Layout {
  version: number;
  units: 'meters';
  building: {
    footprint: Rect;
    levels: number;
    floor_height: number;
    slab: number;
    wall_height: number;
    corridor: Rect;
    stairs: Rect;
    elevator: Rect;
  };
  hospitals: { id: string; name: string; lat: number; lon: number; helipad: boolean }[];
  care_units: { id: string; name: string; clinical: boolean; capacity: number }[];
  floors: Floor[];
  beds: Bed[];
  seats: Seat[];
  spots: Spot[];
  props: Prop[];
  outside: {
    ambulance_bay: Rect;
    ambulance_slots: AmbulanceSlot[];
    street_z: number;
    street_width: number;
    entrance_node: string;
    curb_spot: string;
  };
  roof: {
    level: number;
    helipad_x: number;
    helipad_z: number;
    helipad_size: number;
    helicopter_x: number;
    helicopter_z: number;
    helipad_spot: string;
  };
  graph: { nodes: GraphNode[]; edges: { a: string; b: string; kind: 'walk' | 'door' | 'elevator'; length: number }[] };
}

/** The layout file as imported by the bundler. */
export const LAYOUT: Layout = layoutJson as unknown as Layout;

/** Lookups built once for a layout. */
export class LayoutIndex {
  readonly beds = new Map<string, Bed>();
  readonly seats = new Map<string, Seat>();
  readonly spots = new Map<string, Spot>();
  readonly nodes = new Map<string, GraphNode>();
  readonly rooms = new Map<string, Room>();

  constructor(readonly layout: Layout) {
    layout.beds.forEach((b) => this.beds.set(b.id, b));
    layout.seats.forEach((s) => this.seats.set(s.id, s));
    layout.spots.forEach((s) => this.spots.set(s.id, s));
    layout.graph.nodes.forEach((n) => this.nodes.set(n.id, n));
    layout.floors.forEach((f) => f.rooms.forEach((r) => this.rooms.set(r.id, r)));
  }

  get levels(): number {
    return this.layout.building.levels;
  }
}
