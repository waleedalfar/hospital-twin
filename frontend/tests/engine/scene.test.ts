import * as THREE from 'three';
import { beforeEach, describe, expect, it } from 'vitest';

import { setBedPatient, setRisk } from '../../src/engine/beds';
import { buildBuilding, floorTargets, roofTarget, type BuildingView } from '../../src/engine/building';
import { EntityLayer, type LayerHost } from '../../src/engine/entities';
import { PROP_TYPES } from '../../src/engine/furniture';
import { VehicleLayer, SIREN_RED, SIREN_RED_DIM } from '../../src/engine/vehicles';
import { LAYOUT, LayoutIndex } from '../../src/engine/layout';
import { labelFor, toneColor, toneFor } from '../../src/engine/labelsLive';
import { Xray, XRAY_OPACITY } from '../../src/engine/xray';
import { Picker, entityIdOf, isClick, visibleChain } from '../../src/engine/picking';
import { countsOf, installDebug } from '../../src/engine/debug';
import type { Entity } from '../../src/state/wsTypes';
import { loadSnapshot, makeKit } from './helpers';

const idx = new LayoutIndex(LAYOUT);
const snap = loadSnapshot();
const SIM_NOW = Date.parse(snap.sim_time);

function setup(style: 'iso' | 'classic' | 'neon' = 'iso') {
  const kit = makeKit(style);
  const scene = new THREE.Scene();
  const building = buildBuilding(kit.tk, kit.labels, LAYOUT, 'Mercy General', scene);
  const host: LayerHost = { floorY: (l) => building.floors[l]?.y ?? building.roof.position.y, floorVisible: () => true, carVisible: () => true, xray: () => false };
  const layer = new EntityLayer(kit.tk, kit.labels, kit.chars, building, LAYOUT, idx, scene, host);
  return { ...kit, scene, building, layer };
}

describe('building from the layout', () => {
  let b: BuildingView;
  beforeEach(() => {
    b = setup().building;
  });

  it('has three floors, a roof, an elevator car and 29 beds', () => {
    expect(b.floors).toHaveLength(3);
    expect(b.beds.size).toBe(29);
    expect(b.roof.name).toBe('roof');
    expect(b.car.name).toBe('elevator-car');
    expect(b.heli).not.toBeNull();
    expect(b.rotor).not.toBeNull();
  });

  it('places every bed where the layout says, rotated as the layout says', () => {
    for (const bed of LAYOUT.beds) {
      const v = b.beds.get(bed.id)!;
      expect(v.group.position.x).toBe(bed.x);
      expect(v.group.position.z).toBe(bed.z);
      expect(v.group.rotation.y).toBe(bed.rotation);
    }
  });

  it('every prop type in the layout has a builder, and every builder is used', () => {
    const used = new Set(LAYOUT.props.map((p) => p.type));
    for (const t of used) expect(PROP_TYPES).toContain(t);
    for (const t of PROP_TYPES) expect(used.has(t)).toBe(true);
  });

  it('labels every room, with the hospital name on the entrance sign', () => {
    const rooms = LAYOUT.floors.flatMap((f) => f.rooms.filter((r) => r.kind === 'room'));
    expect(rooms).toHaveLength(15);
    let labelled = 0;
    b.floors.forEach((f) => (labelled += [...f.labels.keys()].filter((k) => k !== '__entrance__').length));
    expect(labelled).toBe(15);
    expect(b.entranceSign?.userData.text).toBe('MERCY GENERAL');
  });

  it('the floor stack is 3.4 m apart; exploded gap is 6 m; X-ray spreads 3.5 m', () => {
    expect(floorTargets(3, 'all', false, false)).toEqual([0, 3.4, 6.8]);
    expect(floorTargets(3, 'all', true, false).map((v) => +v.toFixed(2))).toEqual([0, 9.4, 18.8]);
    expect(floorTargets(3, 'all', false, true).map((v) => +v.toFixed(2))).toEqual([0, 6.9, 13.8]);
    expect(floorTargets(3, 0, false, true)).toEqual([0, 3.4, 6.8]); // X-ray only spreads when all floors show
    expect(roofTarget(3, 'all', false, false)).toBeCloseTo(10.2);
    expect(roofTarget(3, 'all', true, false)).toBeCloseTo(28.2);
    expect(roofTarget(3, 'all', false, true)).toBeCloseTo(20.7);
  });

  it('the scene has no walls on the elevator side of the corridor ends and no gameboy style', () => {
    expect(b.index.layout.building.elevator.x1).toBe(17);
  });

  it('works in every style', () => {
    for (const style of ['iso', 'classic', 'neon'] as const) expect(setup(style).building.beds.size).toBe(29);
  });
});

describe('entities in the scene (recorded snapshot fixture)', () => {
  it('renders every entity in the building: counts match the snapshot', () => {
    const { layer } = setup();
    layer.sync(snap.entities, SIM_NOW);
    const inBuilding = snap.entities.filter((e) => e.location.floor !== null && !e.location.vehicle);
    const rendered = layer.rendered();
    expect(rendered).toHaveLength(inBuilding.length);
    expect(countsOf(rendered)).toEqual(
      inBuilding.reduce<Record<string, number>>((o, e) => ({ ...o, [e.kind]: (o[e.kind] ?? 0) + 1 }), {}),
    );
    expect(layer.problems).toEqual([]);
  });

  it('puts a lying patient in each occupied bed, at that bed', () => {
    const { layer, building } = setup();
    layer.sync(snap.entities, SIM_NOW);
    const inBed = snap.entities.filter((e) => e.location.bed && !(e.move && Date.parse(e.move.arrive) > SIM_NOW));
    expect(inBed.length).toBeGreaterThan(10);
    for (const e of inBed) {
      const v = building.beds.get(e.location.bed as string)!;
      expect(v.patientId).toBe(e.id);
      expect(v.lying).not.toBeNull();
    }
    const rendered = layer.rendered().filter((r) => r.mode === 'bed');
    expect(rendered).toHaveLength(inBed.length);
    for (const r of rendered) {
      const bed = LAYOUT.beds.find((b) => b.id === r.bed)!;
      expect(r.position.x).toBeCloseTo(bed.x);
      expect(r.position.z).toBeCloseTo(bed.z);
    }
  });

  it('colors monitors and markers by risk and shows "!" only for high risk', () => {
    const { layer, building, tk } = setup();
    layer.sync(snap.entities, SIM_NOW);
    const icu3 = snap.entities.find((e) => e.location.bed === 'ICU-3')!;
    expect(icu3.risk?.level).toBe('high');
    const v = building.beds.get('ICU-3')!;
    expect(v.bang).not.toBeNull();
    expect(v.blink).toBe(true);
    expect('#' + (v.glow.material as THREE.MeshBasicMaterial).color.getHexString()).toBe(tk.P.high);
    const levels = new Set(snap.entities.map((e) => e.risk?.level));
    expect(levels.has('low') && levels.has('medium') && levels.has('high')).toBe(true);
    for (const [id, bed] of building.beds) {
      if (bed.patientId === null) {
        expect(bed.bang).toBeNull();
        expect('#' + (bed.glow.material as THREE.MeshBasicMaterial).color.getHexString()).toBe(tk.P.screenOff);
      } else if (bed.riskLevel !== 'high') {
        expect(bed.bang, id).toBeNull();
      }
    }
  });

  it('removes people who leave and empties vacated beds', () => {
    const { layer, building } = setup();
    layer.sync(snap.entities, SIM_NOW);
    const withoutIcu = snap.entities.filter((e) => e.location.bed !== 'ICU-3');
    layer.sync(withoutIcu, SIM_NOW);
    expect(building.beds.get('ICU-3')?.patientId).toBeNull();
    expect(building.beds.get('ICU-3')?.pickables).toEqual([]);
    layer.sync([], SIM_NOW);
    expect(layer.rendered()).toEqual([]);
    expect(building.beds.get('ICU-1')?.patientId).toBeNull();
  });

  it('seats seated patients on their chairs and animates walkers along their path', () => {
    const { layer } = setup();
    layer.sync(snap.entities, SIM_NOW);
    layer.update(SIM_NOW, 0);
    const seated = snap.entities.filter((e) => e.location.spot?.startsWith('W-') && !e.move);
    expect(seated.length).toBeGreaterThan(2);
    for (const e of seated) {
      const seat = idx.seats.get(e.location.spot as string)!;
      const r = layer.rendered().find((x) => x.id === e.id)!;
      expect(r.position.x).toBeCloseTo(seat.x, 1);
      expect(r.position.z).toBeCloseTo(seat.z, 1);
      expect(r.pose).toBe('seated');
    }
    const walker = snap.entities.find((e) => e.move && !e.location.bed)!;
    const times = walker.move!.times.map(Date.parse);
    layer.update((times[0]! + times[times.length - 1]!) / 2, 1);
    const mid = layer.rendered().find((x) => x.id === walker.id)!;
    expect(['walking', 'standing']).toContain(mid.pose);
  });

  it('passes the faceless audit for every character, in every style', () => {
    for (const style of ['iso', 'classic', 'neon'] as const) {
      const { layer } = setup(style);
      layer.sync(snap.entities, SIM_NOW);
      for (const { id, character } of layer.allCharacters()) expect(character.partNames().length, id).toBeGreaterThan(8);
      for (const l of layer.lyingModels()) expect(l.group.children.length).toBeGreaterThan(0);
    }
  });

  it('draws a patient on the operating table lying down', () => {
    const { layer } = setup();
    const table = LAYOUT.spots.find((s) => s.kind === 'table' && s.room === 'OR')!;
    const patient: Entity = {
      id: 'P-0001',
      kind: 'patient',
      location: { floor: 1, room: 'OR', spot: table.id },
      appearance: { skin: 1, hair: 1, headscarf: false },
      pose: 'lying',
    };
    layer.sync([patient], SIM_NOW);
    const r = layer.rendered()[0]!;
    expect(r.mode).toBe('table');
    expect(r.pose).toBe('lying');
    expect(layer.lyingModels()).toHaveLength(1);
    layer.sync([], SIM_NOW);
    expect(layer.rendered()).toEqual([]);
  });

  it('reports an entity with no place instead of guessing one', () => {
    const { layer } = setup();
    layer.sync([{ id: 'N-1', kind: 'nurse', location: { floor: 0, room: 'ER' }, appearance: { skin: 0, hair: 0, headscarf: false }, pose: 'standing' }], SIM_NOW);
    expect(layer.problems[0]).toContain('N-1 has no place');
    layer.update(SIM_NOW, 0);
    expect(layer.allCharacters()[0]?.character.group.visible).toBe(false);
  });

  it('draws an EMT who is walking a patient in, but not one sitting in the ambulance', () => {
    const { layer } = setup();
    const t0 = new Date(SIM_NOW - 1000).toISOString();
    const t1 = new Date(SIM_NOW + 30_000).toISOString();
    const emt: Entity = {
      id: 'E-9',
      kind: 'emt',
      location: { floor: 0, room: 'OUTSIDE', vehicle: 'AMB-mercy-1' },
      appearance: { skin: 0, hair: 0, headscarf: false },
      pose: 'walking',
      move: { path: ['f0-CURB', 'f0-entrance'], times: [t0, t1], depart: t0, arrive: t1 },
    };
    layer.sync([emt], SIM_NOW);
    expect(layer.rendered().map((r) => r.id)).toEqual(['E-9']);
    layer.sync([{ ...emt, move: null }], SIM_NOW);
    expect(layer.rendered()).toEqual([]);
  });

  it('does not draw people inside vehicles', () => {
    const { layer } = setup();
    layer.sync([{ id: 'E-1', kind: 'emt', location: { floor: null, room: null, vehicle: 'AMB-mercy-1' }, appearance: { skin: 0, hair: 0, headscarf: false }, pose: 'standing' }], SIM_NOW);
    expect(layer.rendered()).toEqual([]);
  });

  it('a rider in the elevator is placed in the car', () => {
    const { layer } = setup();
    const now = SIM_NOW;
    const t0 = new Date(now - 10_000).toISOString();
    const t1 = new Date(now + 10_000).toISOString();
    const rider: Entity = {
      id: 'N-2',
      kind: 'nurse',
      location: { floor: 2, room: 'CORR-2', spot: 'ICU-ws-1' },
      appearance: { skin: 0, hair: 0, headscarf: false },
      pose: 'walking',
      move: { path: ['f0-ELEV', 'f2-ELEV'], times: [t0, t1], depart: t0, arrive: t1 },
    };
    layer.sync([rider], now);
    layer.update(now, 0);
    const r = layer.rendered()[0]!;
    expect(r.position.x).toBe(18.5);
    expect(r.position.y).toBeCloseTo(3.4 + 0.3, 1); // half way up between floor 0 and floor 2
  });

  it('floors hidden by a cutaway hide their people', () => {
    const kit = setup();
    const host: LayerHost = { floorY: () => 0, floorVisible: (l) => l !== 1, carVisible: () => true, xray: () => false };
    const layer = new EntityLayer(kit.tk, kit.labels, kit.chars, kit.building, LAYOUT, idx, kit.scene, host);
    layer.sync(snap.entities.filter((e) => !e.location.bed && !e.move), SIM_NOW);
    layer.update(SIM_NOW, 0);
    for (const { id, character } of layer.allCharacters()) {
      const floor = snap.entities.find((e) => e.id === id)?.location.floor;
      expect(character.group.visible, id).toBe(floor !== 1);
    }
  });
});

describe('vehicles on the grounds', () => {
  it('parks ambulances in their bay slots, flashes unloading ones, and shows the helicopter only while it is home', () => {
    const { tk, scene, building } = setup();
    const layer = new VehicleLayer(tk, scene, LAYOUT, building);
    layer.sync([
      { id: 'AMB-mercy-1', kind: 'ambulance', status: 'at_base', slot: 'AMB-slot-1' },
      { id: 'AMB-mercy-2', kind: 'ambulance', status: 'unloading', slot: 'AMB-slot-3' },
      { id: 'HELI-mercy', kind: 'helicopter', status: 'at_base', slot: null },
    ]);
    const slots = LAYOUT.outside.ambulance_slots;
    expect(layer.drawn()).toEqual([
      { id: 'AMB-mercy-1', x: slots[0]!.x, z: slots[0]!.z },
      { id: 'AMB-mercy-2', x: slots[2]!.x, z: slots[2]!.z },
    ]);
    expect(building.heli?.visible).toBe(true);
    layer.update(0); // 0 s: lights on the first phase
    layer.update(0.2);
    const colors = new Set<string>();
    for (let t = 0; t < 1; t += 0.05) {
      layer.update(t);
      colors.add(scene.children.length.toString());
    }
    expect(colors.size).toBeGreaterThan(0);
    expect(SIREN_RED).not.toBe(SIREN_RED_DIM);
    layer.sync([{ id: 'AMB-mercy-2', kind: 'ambulance', status: 'unloading', slot: 'AMB-slot-3' }]);
    expect(layer.drawn().map((d) => d.id)).toEqual(['AMB-mercy-2']);
    expect(building.heli?.visible).toBe(false);
    layer.sync([{ id: 'AMB-x', kind: 'ambulance', status: 'at_base', slot: 'no-such-slot' }]);
    expect(layer.drawn()).toEqual([]);
  });
});

describe('beds', () => {
  it('toggles a patient, risk color, marker and blinking "!"', () => {
    const { tk, labels, chars, building } = setup();
    const view = building.beds.get('ICU-1')!;
    const floor = building.floors[2]!;
    setBedPatient(tk, chars, labels, view, floor.g, 'P-1', { skin: 1, hair: 2, headscarf: true });
    expect(view.pickables).toHaveLength(2);
    expect(view.marker).not.toBeNull();
    setRisk(tk, labels, view, floor.g, 'high');
    expect(view.bang).not.toBeNull();
    setRisk(tk, labels, view, floor.g, 'medium');
    expect(view.bang).toBeNull();
    expect(view.blink).toBe(false);
    setBedPatient(tk, chars, labels, view, floor.g, null, null);
    expect(view.lying).toBeNull();
    expect(view.marker).toBeNull();
  });
});

describe('X-ray', () => {
  it('drops walls to 7%, floors to 55%, caps to 25%, stops shadows, and shows markers', () => {
    const { tk, labels, layer } = setup();
    layer.sync(snap.entities, SIM_NOW);
    const x = new Xray(tk, labels);
    expect(XRAY_OPACITY).toEqual({ wall: 0.07, floor: 0.55, cap: 0.25 });
    expect(x.opacities()).toEqual({ wall: 1, floor: 1 });
    expect([...labels.markers].every((m) => !m.visible)).toBe(true);
    expect(x.set(true)).toBe(true);
    expect(x.set(true)).toBe(false);
    expect(x.opacities()).toEqual({ wall: 0.07, floor: 0.55 });
    for (const m of tk.shellMeshes) {
      expect(m.castShadow).toBe(false);
      const mat = m.material as THREE.Material;
      expect(mat.transparent).toBe(true);
      expect(mat.depthWrite).toBe(false);
    }
    const markers = [...labels.markers];
    expect(markers.length).toBeGreaterThan(20);
    expect(markers.every((m) => m.visible && !m.material.depthTest)).toBe(true);
    expect(x.set(false)).toBe(true);
    expect(x.opacities()).toEqual({ wall: 1, floor: 1 });
    expect(tk.shellMeshes.every((m) => m.castShadow)).toBe(true);
    expect([...labels.markers].every((m) => !m.visible)).toBe(true);
  });
});

describe('live room labels', () => {
  it('counts occupied beds, people waiting and the operating table', () => {
    const rooms = Object.fromEntries(LAYOUT.floors.flatMap((f) => f.rooms.map((r) => [r.id, r])));
    expect(labelFor(LAYOUT, rooms['ICU']!, snap.entities).sub).toBe(`${snap.entities.filter((e) => e.location.room === 'ICU' && e.location.bed).length}/6`);
    expect(labelFor(LAYOUT, rooms['WAITING']!, snap.entities).sub).toBe(String(snap.entities.filter((e) => e.kind === 'patient' && e.location.room === 'WAITING').length));
    expect(labelFor(LAYOUT, rooms['OR']!, []).sub).toBe('OR-1');
    expect(labelFor(LAYOUT, rooms['LAB']!, snap.entities)).toEqual({ sub: '', tone: '' });
    expect(labelFor(LAYOUT, rooms['ER']!, []).sub).toBe('0/6');
  });
  it('colors by fullness', () => {
    expect(toneFor(0.3)).toBe('low');
    expect(toneFor(0.6)).toBe('med');
    expect(toneFor(0.85)).toBe('high');
    expect(toneColor('', makeKit().tk.P)).toBe('');
    expect(toneColor('high', makeKit().tk.P)).toBe('#e5484d');
  });
});

describe('picking', () => {
  it('selects the entity behind a click, skips hidden meshes and outlines, and tells clicks from drags', () => {
    const parent = new THREE.Group();
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshBasicMaterial());
    mesh.userData['entityId'] = 'P-7';
    parent.add(mesh);
    const cam = new THREE.OrthographicCamera(-5, 5, 5, -5, 0.1, 100);
    cam.position.set(0, 0, 10);
    cam.lookAt(0, 0, 0);
    cam.updateMatrixWorld();
    parent.updateMatrixWorld(true);
    const picker = new Picker();
    expect(picker.pick(0, 0, cam, [parent])).toBe('P-7');
    expect(picker.pick(0.95, 0.95, cam, [parent])).toBeNull();
    parent.visible = false;
    expect(visibleChain(mesh)).toBe(false);
    expect(picker.pick(0, 0, cam, [parent])).toBeNull();
    expect(entityIdOf(mesh)).toBe('P-7');
    expect(entityIdOf(null)).toBeNull();
    expect(isClick(0)).toBe(true);
    expect(isClick(4.9)).toBe(true);
    expect(isClick(5)).toBe(false);
  });
});

describe('picking a patient behind a person', () => {
  function scene(gap: number, frontId = 'N-14'): { cam: THREE.OrthographicCamera; root: THREE.Group } {
    const root = new THREE.Group();
    const make = (id: string, z: number): void => {
      const m = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 0.2), new THREE.MeshBasicMaterial());
      m.userData['entityId'] = id;
      m.position.z = z;
      root.add(m);
    };
    make(frontId, 1); // the nurse stands in front, nearer the camera
    make('P-0412', 1 - gap); // the patient lies behind her
    const cam = new THREE.OrthographicCamera(-5, 5, 5, -5, 0.1, 100);
    cam.position.set(0, 0, 10);
    cam.lookAt(0, 0, 0);
    cam.updateMatrixWorld();
    root.updateMatrixWorld(true);
    return { cam, root };
  }
  const prefersPatients = (id: string): boolean => id.startsWith('P-');

  it('selects the patient when they are just behind someone standing at the bedside', () => {
    const { cam, root } = scene(0.8);
    const picker = new Picker();
    expect(picker.pick(0, 0, cam, [root])).toBe('N-14'); // without a preference the nearest wins
    expect(picker.pick(0, 0, cam, [root], prefersPatients)).toBe('P-0412');
  });
  it('still selects the person when the patient is far behind them, or when nobody is preferred', () => {
    const { cam, root } = scene(4);
    const picker = new Picker();
    expect(picker.pick(0, 0, cam, [root], prefersPatients)).toBe('N-14');
    expect(picker.pick(0, 0, cam, [root], () => false)).toBe('N-14');
  });
  it('takes a preferred entity that is the nearest hit as it is', () => {
    const { cam, root } = scene(0.8, 'P-0001');
    expect(new Picker().pick(0, 0, cam, [root], prefersPatients)).toBe('P-0001');
  });
});

describe('debug API', () => {
  it('is always present and read-only', () => {
    installDebug();
    expect(window.__TWIN_DEBUG__.entities()).toEqual([]);
    expect(window.__TWIN_DEBUG__.view().mode).toBe('iso');
    expect(window.__TWIN_DEBUG__.faceAudit().ok).toBe(true);
    expect(window.__TWIN_DEBUG__.frameStats().frames).toBe(0);
    expect(window.__TWIN_DEBUG__.problems()).toEqual([]);
    expect(Object.isFrozen(window.__TWIN_DEBUG__)).toBe(true);
    expect(() => {
      (window.__TWIN_DEBUG__ as unknown as { entities: unknown }).entities = 1;
    }).toThrow();
    for (const k of ['counts', 'beds', 'xray', 'selected'] as const) expect(window.__TWIN_DEBUG__[k]()).toBeDefined();
  });
});
