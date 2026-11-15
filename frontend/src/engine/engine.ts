/**
 * The 3D engine: renderer at 1/pixel-factor resolution upscaled with `image-rendering: pixelated`, toon
 * lighting, the building, live entities, cameras, presets, cutaway, exploded view, X-ray, night mode, picking
 * and the debug API (PROMPT.md §10). Ported from `mount()` in reference/engine/pulse3d.js.
 */
import * as THREE from 'three';

import { auditFace } from './characters';
import { CharacterFactory } from './characters';
import { buildBuilding, floorTargets, roofTarget, FLOOR_HEIGHT, type BuildingView } from './building';
import { CameraController, look, presetById, type CamState, type CameraMode, type ViewLevel } from './camera';
import { countsOf, installDebug, type FrameStats, type TwinDebug, type ViewInfo } from './debug';
import { EntityLayer } from './entities';
import { frameDelta } from './frame';
import { Highlighter } from './highlight';
import { LabelFactory } from './labels';
import { labelFor, toneColor } from './labelsLive';
import { LAYOUT, LayoutIndex, type Layout } from './layout';
import { Toolkit, type CanvasFactory } from './materials';
import { DEFAULT_PIXEL_FACTOR, MAX_PIXEL_FACTOR, MIN_PIXEL_FACTOR, STYLES, type StyleName } from './palette';
import { isClick, Picker } from './picking';
import { VehicleLayer } from './vehicles';
import { Xray } from './xray';
import type { VehicleAtHospital } from '../state/types';
import type { Entity } from '../state/wsTypes';

export interface EngineOptions {
  canvas: HTMLCanvasElement;
  hospitalName: string;
  width?: number;
  height?: number;
  cameraMode?: CameraMode;
  night?: boolean;
  pixelFactor?: number;
  layout?: Layout;
  createCanvas?: CanvasFactory;
  /** Sim time in ms since the epoch; entities move along their paths against it. */
  simClock?: () => number;
  /** Freeze animation time (screenshot tests use `?freeze=1`). */
  frozen?: boolean;
  onPick?: (entityId: string | null) => void;
  onView?: (v: { view: ViewLevel; exploded: boolean; preset: string | null }) => void;
}

export function styleFor(mode: CameraMode, night: boolean): StyleName {
  return night ? 'neon' : mode === 'iso' ? 'iso' : 'classic';
}

export class Engine {
  readonly layout: Layout;
  private readonly idx: LayoutIndex;
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private tk!: Toolkit;
  private labels!: LabelFactory;
  private factory!: CharacterFactory;
  private building!: BuildingView;
  private layer!: EntityLayer;
  private vehicleLayer!: VehicleLayer;
  private vehicles: readonly VehicleAtHospital[] = [];
  private xray!: Xray;
  private sun!: THREE.DirectionalLight;
  private readonly cam: CameraController;
  private readonly picker = new Picker();
  private readonly ring = new THREE.Group();
  private highlighter: Highlighter | undefined;
  private width: number;
  private height: number;
  private pixel: number;
  private night: boolean;
  private view: ViewLevel = 'all';
  private exploded = false;
  private presetId: string | null = null;
  private selected: string | null = null;
  private entities: readonly Entity[] = [];
  private carLevel = 0;
  private time = 0;
  private last = 0;
  private raf = 0;
  private dead = false;
  private frames = 0;
  private lastFrameMs = 0;
  private fpsWindow: number[] = [];
  private frozen: boolean;
  private rotorSpin = false;
  private drag: { x: number; y: number; moved: number } | null = null;
  private readonly cleanup: (() => void)[] = [];

  constructor(private readonly opts: EngineOptions) {
    this.layout = opts.layout ?? LAYOUT;
    this.idx = new LayoutIndex(this.layout);
    this.width = opts.width ?? 1280;
    this.height = opts.height ?? 744;
    this.pixel = clampPixel(opts.pixelFactor ?? DEFAULT_PIXEL_FACTOR);
    this.night = opts.night ?? false;
    this.frozen = opts.frozen ?? false;
    this.renderer = new THREE.WebGLRenderer({ canvas: opts.canvas, antialias: false });
    this.renderer.setPixelRatio(1);
    this.renderer.shadowMap.enabled = true;
    this.cam = new CameraController(opts.cameraMode ?? 'iso', this.width / this.height);
    this.applyPixel();
    this.buildScene();
    this.attachInput();
    this.preset('outside', false);
    installDebug(this.debugApi());
    this.last = performance.now();
    this.raf = requestAnimationFrame((t) => this.frame(t));
  }

  // ---- scene -----------------------------------------------------------------------------------------

  private get styleName(): StyleName {
    return styleFor(this.cam.mode, this.night);
  }

  private buildScene(): void {
    this.scene.clear();
    const st = STYLES[this.styleName];
    this.tk = new Toolkit(this.styleName, this.opts.createCanvas);
    this.labels = new LabelFactory(this.tk);
    this.factory = new CharacterFactory(this.tk, this.labels);
    this.scene.background = new THREE.Color(this.tk.mapC(this.tk.P.sky));
    this.scene.fog = st.fog ? new THREE.Fog(this.tk.mapC(this.tk.P.sky), st.fog[0], st.fog[1]) : null;
    this.scene.add(new THREE.HemisphereLight(st.hemi[0], st.hemi[1], st.hemi[2]));
    this.sun = new THREE.DirectionalLight(st.sun[0], st.sun[1]);
    this.sun.position.set(30, 60, 25);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(1024, 1024);
    Object.assign(this.sun.shadow.camera, { left: -50, right: 50, top: 50, bottom: -50, near: 1, far: 200 });
    this.sun.shadow.camera.updateProjectionMatrix();
    this.scene.add(this.sun);
    this.building = buildBuilding(this.tk, this.labels, this.layout, this.opts.hospitalName, this.scene);
    this.xray = new Xray(this.tk, this.labels);
    this.layer = new EntityLayer(this.tk, this.labels, this.factory, this.building, this.layout, this.idx, this.scene, {
      floorY: (l) => this.floorY(l),
      floorVisible: (l) => this.floorVisible(l),
      carVisible: () => this.carVisible(),
      xray: () => this.xray.on,
    });
    this.vehicleLayer = new VehicleLayer(this.tk, this.scene, this.layout, this.building);
    const keep = this.highlighter?.highlighted ?? [];
    this.highlighter = new Highlighter(this.scene);
    this.highlighter.set(keep);
    this.vehicleLayer.sync(this.vehicles);
    this.buildRing();
    this.applyView(true);
    if ('fonts' in document) {
      void Promise.all([document.fonts.load('700 26px "Pixelify Sans"'), document.fonts.load('30px "VT323"')])
        .then(() => this.labels.redrawAll())
        .catch((e: unknown) => console.error('Fonts did not load; labels use fallback fonts', e));
    }
    this.layer.sync(this.entities, this.simNow());
    this.refreshLabels();
  }

  private buildRing(): void {
    const rm = this.tk.B(this.tk.P.ring);
    const o = { outline: false, cast: false } as const;
    this.ring.clear();
    this.tk.box(1.7, 0.08, 0.14, rm, 0, 0.05, -1.35, this.ring, o);
    this.tk.box(1.7, 0.08, 0.14, rm, 0, 0.05, 1.35, this.ring, o);
    this.tk.box(0.14, 0.08, 2.7, rm, -0.85, 0.05, 0, this.ring, o);
    this.tk.box(0.14, 0.08, 2.7, rm, 0.85, 0.05, 0, this.ring, o);
    this.ring.visible = false;
  }

  private simNow(): number {
    return this.opts.simClock ? this.opts.simClock() : Date.now();
  }

  floorY(level: number): number {
    if (level >= this.layout.building.levels) return this.building.roof.position.y;
    return this.building.floors[level]?.y ?? level * FLOOR_HEIGHT;
  }

  floorVisible(level: number): boolean {
    const f = this.building.floors[level];
    return f ? f.g.visible : this.building.roof.visible;
  }

  private carVisible(): boolean {
    return this.building.car.visible;
  }

  // ---- state in -------------------------------------------------------------------------------------

  /** Apply the entities of the current hospital. */
  setEntities(entities: readonly Entity[]): void {
    this.entities = entities;
    this.layer.sync(entities, this.simNow());
    this.refreshLabels();
  }

  /** Vehicles on the hospital's grounds (ambulances in the bay, the helicopter on the roof). */
  setVehicles(vehicles: readonly VehicleAtHospital[]): void {
    this.vehicles = vehicles;
    this.vehicleLayer.sync(vehicles);
  }

  /** Resize the canvas area (CSS pixels). The render resolution stays 1/pixel-factor of it. */
  resize(width: number, height: number): void {
    this.width = Math.max(64, Math.round(width));
    this.height = Math.max(40, Math.round(height));
    this.cam.resize(this.width / this.height);
    this.applyPixel();
  }

  setFrozen(on: boolean): void {
    this.frozen = on;
  }

  /** The hospital's name on the entrance sign. */
  setHospitalName(name: string): void {
    this.building.entranceSign?.userData.setText(name.toUpperCase(), '', '');
  }

  private refreshLabels(): void {
    for (const floor of this.layout.floors) {
      const view = this.building.floors[floor.level];
      if (!view) continue;
      for (const room of floor.rooms.filter((r) => r.kind === 'room')) {
        const label = view.labels.get(room.id);
        if (!label) continue;
        const t = labelFor(this.layout, room, this.entities);
        label.userData.setText(room.name.toUpperCase(), t.sub, toneColor(t.tone, this.tk.P));
      }
    }
  }

  setRotorSpinning(on: boolean): void {
    this.rotorSpin = on;
  }

  // ---- views -----------------------------------------------------------------------------------------

  private applyView(snap = false): void {
    const { floors, roof } = this.building;
    const targets = floorTargets(floors.length, this.view, this.exploded, this.xray.on);
    floors.forEach((f, i) => {
      f.g.visible = this.view === 'all' || this.exploded || f.level <= this.view;
      const showLabels = this.exploded || (this.view !== 'all' && f.level === this.view);
      f.labels.forEach((s, id) => (s.visible = id === '__entrance__' ? this.view === 'all' || this.exploded || this.view === 0 : showLabels));
      f.ty = targets[i] ?? f.ty;
      if (snap) {
        f.y = f.ty;
        f.g.position.y = f.y;
      }
    });
    roof.visible = this.view === 'all' || this.exploded;
    if (snap) roof.position.y = roofTarget(floors.length, this.view, this.exploded, this.xray.on);
  }

  setView(view: ViewLevel, exploded: boolean): void {
    this.view = view;
    this.exploded = exploded;
    this.presetId = null;
    this.applyView();
    this.emitView();
  }

  private emitView(): void {
    this.opts.onView?.({ view: this.view, exploded: this.exploded, preset: this.presetId });
  }

  /** Move to a preset camera: eased by default, instantly when `animate` is false. */
  preset(id: string, animate = true): void {
    const p = presetById(id);
    if (!p) throw new Error(`Unknown preset ${id}`);
    this.view = p.view;
    this.exploded = p.exploded;
    this.presetId = id;
    this.applyView(!animate);
    if (animate) this.cam.flyTo(this.cam.mode === 'iso' ? { ...p.iso } : { ...p.free }, performance.now());
    else {
      this.cam.jump(p);
      this.floorsSnap();
    }
    this.emitView();
  }

  private floorsSnap(): void {
    this.building.floors.forEach((f) => {
      f.y = f.ty;
      f.g.position.y = f.y;
    });
  }

  setXray(on: boolean): void {
    if (this.xray.set(on)) this.applyView();
  }

  setNight(on: boolean): void {
    if (on === this.night) return;
    this.night = on;
    this.rebuild();
  }

  setCameraMode(mode: CameraMode): void {
    if (mode === this.cam.mode) return;
    const wasXray = this.xray.on;
    const before = this.styleName;
    this.cam.setMode(mode);
    if (this.presetId) this.cam.jump(presetById(this.presetId) ?? (presetById('outside') as NonNullable<ReturnType<typeof presetById>>));
    if (before !== this.styleName) this.rebuild();
    if (wasXray) this.setXray(true);
  }

  private rebuild(): void {
    const wasXray = this.xray.on;
    const keep = { view: this.view, exploded: this.exploded };
    this.disposeScene();
    this.buildScene();
    this.view = keep.view;
    this.exploded = keep.exploded;
    this.applyView(true);
    if (wasXray) this.xray.set(true);
    this.applyView(true);
  }

  private disposeScene(): void {
    this.scene.traverse((o) => {
      if (o instanceof THREE.Mesh) {
        (o.geometry as THREE.BufferGeometry).dispose();
      }
    });
  }

  setPixelFactor(n: number): void {
    this.pixel = clampPixel(n);
    this.applyPixel();
  }

  private applyPixel(): void {
    this.renderer.setSize(Math.max(64, Math.round(this.width / this.pixel)), Math.max(40, Math.round(this.height / this.pixel)), false);
  }

  // ---- selection -------------------------------------------------------------------------------------

  /** Mark the entities an answer is about with a pulsing ring and an X-ray marker. An empty list clears them. */
  highlight(ids: readonly string[]): void {
    this.highlighter?.set(ids);
  }

  select(id: string | null): void {
    this.selected = id;
  }

  /** Fly to the selected entity's bed (or to the person). */
  focusSelected(): void {
    const id = this.selected;
    if (!id) return;
    const bed = this.layer.bedOf(id);
    const now = performance.now();
    if (bed) {
      const level = bed.bed.floor;
      this.view = level;
      this.exploded = false;
      this.presetId = null;
      this.applyView();
      const by = level * FLOOR_HEIGHT;
      if (this.cam.mode === 'iso') this.cam.flyTo({ tx: bed.bed.x, ty: by, tz: bed.bed.z, az: this.cam.ortho.az, el: 0.7, zoom: 3.2 }, now);
      else {
        const l = look(bed.bed.x + 2.5, by + 4.5, bed.bed.z + (bed.bed.rotation ? -4 : 4), bed.bed.x, by + 0.8, bed.bed.z);
        this.cam.flyTo({ ...l }, now);
      }
      this.emitView();
      return;
    }
    const c = this.layer.characterOf(id);
    const e = this.layer.entity(id);
    if (!c || !e || e.location.floor === null) return;
    const level = e.location.floor;
    this.view = level;
    this.exploded = false;
    this.applyView();
    const by = level * FLOOR_HEIGHT;
    const p = c.group.position;
    if (this.cam.mode === 'iso') this.cam.flyTo({ tx: p.x, ty: by, tz: p.z, az: this.cam.ortho.az, el: 0.7, zoom: 3.2 }, now);
    else this.cam.flyTo({ ...look(p.x + 2.5, by + 4.5, p.z + 4, p.x, by + 0.8, p.z) }, now);
    this.emitView();
  }

  // ---- input -----------------------------------------------------------------------------------------

  private attachInput(): void {
    const c = this.opts.canvas;
    c.tabIndex = 0;
    const on = <K extends keyof HTMLElementEventMap>(type: K, fn: (e: HTMLElementEventMap[K]) => void): void => {
      c.addEventListener(type, fn as EventListener);
      this.cleanup.push(() => c.removeEventListener(type, fn as EventListener));
    };
    on('keydown', (e) => {
      if (CONTROLS.has(e.code)) {
        e.preventDefault();
        this.cam.keys[e.code] = true;
      }
    });
    on('keyup', (e) => {
      this.cam.keys[e.code] = false;
    });
    on('blur', () => {
      for (const k of Object.keys(this.cam.keys)) this.cam.keys[k] = false;
    });
    on('pointerdown', (e) => {
      c.focus();
      try {
        c.setPointerCapture(e.pointerId);
      } catch (err) {
        console.warn('Pointer capture failed', err);
      }
      this.drag = { x: e.clientX, y: e.clientY, moved: 0 };
      this.cam.cancelTween();
    });
    on('pointermove', (e) => {
      if (!this.drag) return;
      const mx = e.clientX - this.drag.x;
      const my = e.clientY - this.drag.y;
      this.drag.x = e.clientX;
      this.drag.y = e.clientY;
      this.drag.moved += Math.abs(mx) + Math.abs(my);
      this.cam.drag(mx, my);
    });
    on('pointerup', (e) => {
      const d = this.drag;
      this.drag = null;
      if (d && isClick(d.moved)) {
        const b = c.getBoundingClientRect();
        this.pickAt(((e.clientX - b.left) / b.width) * 2 - 1, -((e.clientY - b.top) / b.height) * 2 + 1);
      }
    });
    on('wheel', (e) => {
      e.preventDefault();
      this.cam.wheel(e.deltaY);
    });
  }

  /** Pick at normalized device coordinates and select the hit entity. */
  pickAt(nx: number, ny: number): string | null {
    const id = this.picker.pick(nx, ny, this.cam.camera, this.layer.pickTargets());
    if (id) {
      this.selected = id;
      this.opts.onPick?.(id);
    }
    return id;
  }

  // ---- frame -----------------------------------------------------------------------------------------

  private frame(now: number): void {
    if (this.dead) return;
    const t0 = performance.now();
    const dt = frameDelta(now, this.last);
    this.last = Math.max(this.last, now);
    if (!this.frozen) this.time += dt;
    const { floors, roof } = this.building;
    const k = Math.min(1, dt * 6);
    floors.forEach((f) => {
      f.y += (f.ty - f.y) * k;
      f.g.position.y = f.y;
    });
    roof.position.y += (roofTarget(floors.length, this.view, this.exploded, this.xray.on) - roof.position.y) * k;
    this.updateCar();
    const sim = this.simNow();
    this.layer.update(sim, this.time);
    this.updateDecor(dt);
    this.vehicleLayer.update(this.time);
    this.updateRing();
    if (this.highlighter && this.highlighter.highlighted.length > 0) this.highlighter.update(this.layer.rendered(), this.time, (l) => this.building.floors[l]?.g.visible ?? true);
    this.cam.update(dt, now);
    this.renderer.render(this.scene, this.cam.camera);
    this.lastFrameMs = performance.now() - t0;
    this.frames++;
    this.fpsWindow.push(now);
    while (this.fpsWindow.length > 30) this.fpsWindow.shift();
    this.raf = requestAnimationFrame((t) => this.frame(t));
  }

  private updateCar(): void {
    const { floors, car } = this.building;
    const lv = this.carLevel;
    const lo = Math.max(0, Math.min(floors.length - 1, Math.floor(lv)));
    const hi = Math.min(floors.length - 1, lo + 1);
    const lowY = floors[lo]?.y ?? 0;
    const highY = floors[hi]?.y ?? lowY;
    car.position.y = lowY + (highY - lowY) * (lv - lo) + 0.3;
    car.visible = this.view === 'all' || this.exploded || lv <= (this.view) + 0.01;
  }

  private updateDecor(dt: number): void {
    const s = this.building.streetCar;
    s.position.set(((this.time * 12) % 180) - 90, 0, 26.2);
    s.rotation.y = Math.PI / 2;
    if (this.rotorSpin && this.building.rotor) this.building.rotor.rotation.y += dt * 9;
    for (const bed of this.building.beds.values()) {
      if (bed.blink) {
        const on = Math.floor(this.time * 3) % 2 === 1;
        (bed.glow.material as THREE.MeshBasicMaterial).color.set(on ? this.tk.P.high : '#200608');
      }
      if (bed.bang) bed.bang.position.y = bed.bangBase + Math.sin(this.time * 4 + bed.bed.x) * 0.15;
    }
  }

  private updateRing(): void {
    const id = this.selected;
    const bed = id ? this.layer.bedOf(id) : null;
    if (!bed) {
      this.ring.visible = false;
      return;
    }
    const floor = this.building.floors[bed.bed.floor];
    if (floor && this.ring.parent !== floor.g) floor.g.add(this.ring);
    this.ring.visible = true;
    this.ring.position.set(bed.bed.x, 0.3, bed.bed.z);
    this.ring.rotation.y = bed.bed.rotation;
  }

  /** Where an entity is on the canvas, in CSS pixels, or null if it is not drawn. Used by tests to click. */
  screenPoint(entityId: string): { x: number; y: number } | null {
    const r = this.layer.rendered().find((e) => e.id === entityId);
    if (!r) return null;
    const v = new THREE.Vector3(r.position.x, r.position.y + (r.mode === 'character' ? 1.5 : 0.9), r.position.z).project(this.cam.camera);
    const rect = this.opts.canvas.getBoundingClientRect();
    return { x: ((v.x + 1) / 2) * rect.width, y: ((1 - v.y) / 2) * rect.height };
  }

  /** Current camera state (mode and numbers), for tests and the HUD. */
  cameraState(): { mode: CameraMode; state: CamState; flying: boolean } {
    return { mode: this.cam.mode, state: this.cam.state, flying: this.cam.flying };
  }

  /** Set the elevator car's level (the entity layer reports the level of riders each frame). */
  setCarLevel(level: number): void {
    this.carLevel = level;
  }

  dispose(): void {
    this.dead = true;
    cancelAnimationFrame(this.raf);
    this.cleanup.forEach((f) => f());
    this.disposeScene();
    this.renderer.dispose();
  }

  // ---- debug -----------------------------------------------------------------------------------------

  private debugApi(): TwinDebug {
    return {
      entities: () => this.layer.rendered(),
      counts: () => countsOf(this.layer.rendered()),
      beds: () => {
        const out: Record<string, string> = {};
        for (const [id, v] of this.building.beds) if (v.patientId) out[id] = v.patientId;
        return out;
      },
      view: (): ViewInfo => ({
        mode: this.cam.mode,
        view: this.view,
        exploded: this.exploded,
        night: this.night,
        pixelFactor: this.pixel,
        preset: this.presetId,
        floorsVisible: this.building.floors.map((f) => f.g.visible),
        roofVisible: this.building.roof.visible,
        floorY: this.building.floors.map((f) => f.y),
      }),
      xray: () => ({
        on: this.xray.on,
        wallOpacity: this.xray.opacities().wall,
        floorOpacity: this.xray.opacities().floor,
        markersVisible: [...this.labels.markers].filter((m) => m.visible).length,
      }),
      selected: () => this.selected,
      highlighted: () => ({ ids: [...(this.highlighter?.highlighted ?? [])], drawn: this.highlighter?.drawn ?? 0 }),
      faceAudit: () => {
        const results: { id: string; audit: ReturnType<typeof auditFace> }[] = [];
        for (const { id, character } of this.layer.allCharacters()) results.push({ id, audit: auditFace(character.group, character.skin) });
        for (const l of this.layer.lyingModels()) results.push({ id: l.id, audit: auditFace(l.group, l.skin, '+y') });
        return { ok: results.every((r) => r.audit.ok), checked: results.length, results };
      },
      frameStats: (): FrameStats => {
        const w = this.fpsWindow;
        const span = w.length > 1 ? ((w[w.length - 1] as number) - (w[0] as number)) / 1000 : 0;
        const info = this.renderer.info.render;
        return { frames: this.frames, fps: span > 0 ? (w.length - 1) / span : 0, lastFrameMs: this.lastFrameMs, drawCalls: info.calls, triangles: info.triangles };
      },
      problems: () => [...this.layer.problems],
      vehicles: () => this.vehicleLayer.drawn(),
      screenPoint: (id) => this.screenPoint(id),
    };
  }
}

const CONTROLS = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE', 'Space', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ShiftLeft', 'ShiftRight']);

export function clampPixel(n: number): number {
  const v = Math.round(n || DEFAULT_PIXEL_FACTOR);
  return Math.max(MIN_PIXEL_FACTOR, Math.min(MAX_PIXEL_FACTOR, v));
}
