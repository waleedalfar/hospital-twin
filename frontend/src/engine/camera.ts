/**
 * Camera math, presets and input handling (PROMPT.md §10.5). The two modes are ported from the prototype:
 * isometric orthographic (azimuth 45 degrees, elevation atan(1/2) = 26.565 degrees; drag rotates, WASD pans,
 * E/Q raise and lower, wheel zooms) and free-fly perspective (drag looks, WASD moves, E/Q up and down, Shift
 * faster, wheel dollies). Moves between presets are eased over 1.2 s.
 */
import * as THREE from 'three';

export type CameraMode = 'iso' | 'free';

export interface OrthoState {
  tx: number;
  ty: number;
  tz: number;
  az: number;
  el: number;
  zoom: number;
}
export interface FreeState {
  x: number;
  y: number;
  z: number;
  yaw: number;
  pitch: number;
}
export type CamState = Record<string, number>;

export const ISO_AZIMUTH = Math.PI / 4;
export const ISO_ELEVATION = 0.4636; // atan(1/2) = 26.565 degrees, as in the prototype
export const ORTHO_HEIGHT = 46;
export const ORTHO_DISTANCE = 120;
export const FREE_FOV = 55;
export const TWEEN_MS = 1200;
export const FLOOR_H = 3.4;

export function look(px: number, py: number, pz: number, tx: number, ty: number, tz: number): FreeState {
  const dx = tx - px;
  const dy = ty - py;
  const dz = tz - pz;
  return { x: px, y: py, z: pz, yaw: Math.atan2(-dx, -dz), pitch: Math.atan2(dy, Math.hypot(dx, dz)) };
}

export type ViewLevel = 'all' | number;

export interface PresetDef {
  /** ASCII id used in code and URLs. */
  id: string;
  /** Text shown in the UI. */
  label: string;
  view: ViewLevel;
  exploded: boolean;
  free: FreeState;
  iso: OrthoState;
}

const iso = (tx: number, ty: number, tz: number, az: number, el: number, zoom: number): OrthoState => ({ tx, ty, tz, az, el, zoom });

/** The preset cameras, values copied from the prototype's PRESETS table. */
export const PRESETS: readonly PresetDef[] = [
  { id: 'outside', label: 'Outside', view: 'all', exploded: false, free: look(-34, 26, 44, 0, 4, 0), iso: iso(0, 5, 0, Math.PI / 4, 0.4636, 1) },
  { id: 'ground', label: 'Ground floor', view: 0, exploded: false, free: look(-4, 20, 26, 0, 0, 0), iso: iso(0, 0, 0, Math.PI / 4, 0.62, 1.25) },
  { id: 'floor2', label: 'Floor 2', view: 1, exploded: false, free: look(-4, 20 + FLOOR_H, 26, 0, FLOOR_H, 0), iso: iso(0, FLOOR_H, 0, Math.PI / 4, 0.62, 1.25) },
  { id: 'floor3', label: 'Floor 3', view: 2, exploded: false, free: look(-4, 20 + 2 * FLOOR_H, 26, 0, 2 * FLOOR_H, 0), iso: iso(0, 2 * FLOOR_H, 0, Math.PI / 4, 0.62, 1.25) },
  { id: 'exploded', label: 'Exploded', view: 'all', exploded: true, free: look(-46, 30, 52, 0, 10, 0), iso: iso(0, 12, 0, Math.PI / 4, 0.4636, 0.62) },
  { id: 'helipad', label: 'Helipad', view: 'all', exploded: false, free: look(22, 22, -26, 6, 3 * FLOOR_H, 0), iso: iso(6, 3 * FLOOR_H, 0, (-Math.PI / 4) * 3, 0.6, 2.2) },
  { id: 'front_door', label: 'Front door', view: 0, exploded: false, free: look(14, 1.7, 26, 14, 1.6, 0), iso: iso(14, 1, 12, 0, 0.3, 2.6) },
  { id: 'side', label: 'Side view', view: 1, exploded: false, free: look(-6, FLOOR_H + 4.5, 30, -6, FLOOR_H + 2.2, 0), iso: iso(-2, FLOOR_H + 1, 0, 0, 0.12, 1.5) },
  { id: 'icu', label: 'ICU close-up', view: 2, exploded: false, free: look(-3, 2 * FLOOR_H + 7, 4, -10, 2 * FLOOR_H + 0.6, -11.5), iso: iso(-9, 2 * FLOOR_H, -9, Math.PI / 5, 0.7, 2.8) },
];

export function presetById(id: string): PresetDef | undefined {
  return PRESETS.find((p) => p.id === id);
}

export function easeInOut(u: number): number {
  return u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2;
}

function wrapAngle(a: number): number {
  return Math.atan2(Math.sin(a), Math.cos(a));
}

/** Interpolate camera state `from` -> `to` at eased fraction `e`, taking the short way around for angles. */
export function lerpState(from: CamState, to: CamState, e: number): CamState {
  const out: CamState = { ...from };
  for (const k of Object.keys(to)) {
    const a = from[k] ?? 0;
    const b = to[k] ?? 0;
    let dv = b - a;
    if (k === 'yaw' || k === 'az') dv = wrapAngle(dv);
    out[k] = a + dv * e;
  }
  return out;
}

export interface Keys {
  [code: string]: boolean;
}
export const CONTROL_KEYS = ['KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE', 'Space', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ShiftLeft', 'ShiftRight'];

export class CameraController {
  mode: CameraMode;
  ortho: OrthoState = { ...ISO_DEFAULT };
  free: FreeState = look(-34, 26, 44, 0, 4, 0);
  camera: THREE.OrthographicCamera | THREE.PerspectiveCamera;
  private tween: { t0: number; from: CamState; to: CamState } | null = null;
  readonly keys: Keys = {};

  constructor(mode: CameraMode, private aspect: number) {
    this.mode = mode;
    this.camera = this.makeCamera(mode);
  }

  private makeCamera(mode: CameraMode): THREE.OrthographicCamera | THREE.PerspectiveCamera {
    if (mode === 'iso') {
      const h = ORTHO_HEIGHT;
      return new THREE.OrthographicCamera((-h * this.aspect) / 2, (h * this.aspect) / 2, h / 2, -h / 2, -500, 500);
    }
    const cam = new THREE.PerspectiveCamera(FREE_FOV, this.aspect, 0.1, 500);
    cam.rotation.order = 'YXZ';
    return cam;
  }

  setMode(mode: CameraMode): void {
    this.mode = mode;
    this.camera = this.makeCamera(mode);
    this.tween = null;
  }

  resize(aspect: number): void {
    this.aspect = aspect;
    const c = this.camera;
    if (c instanceof THREE.OrthographicCamera) {
      c.left = (-ORTHO_HEIGHT * aspect) / 2;
      c.right = (ORTHO_HEIGHT * aspect) / 2;
    } else c.aspect = aspect;
    c.updateProjectionMatrix();
  }

  get state(): CamState {
    return this.mode === 'iso' ? { ...this.ortho } : { ...this.free };
  }

  private setState(s: CamState): void {
    if (this.mode === 'iso') Object.assign(this.ortho, s);
    else Object.assign(this.free, s);
  }

  /** Jump to a preset without easing. */
  jump(p: PresetDef): void {
    this.tween = null;
    this.setState(this.mode === 'iso' ? { ...p.iso } : { ...p.free });
  }

  /** Ease to a state over TWEEN_MS starting at `now` (ms). */
  flyTo(to: CamState, now: number): void {
    this.tween = { t0: now, from: this.state, to };
  }

  get flying(): boolean {
    return this.tween !== null;
  }

  cancelTween(): void {
    this.tween = null;
  }

  drag(dx: number, dy: number): void {
    this.tween = null;
    if (this.mode === 'iso') {
      this.ortho.az -= dx * 0.006;
      this.ortho.el = Math.max(0.15, Math.min(1.35, this.ortho.el + dy * 0.004));
    } else {
      this.free.yaw -= dx * 0.005;
      this.free.pitch = Math.max(-1.5, Math.min(1.5, this.free.pitch - dy * 0.005));
    }
  }

  wheel(deltaY: number): void {
    this.tween = null;
    if (this.mode === 'iso') {
      this.ortho.zoom = Math.max(0.4, Math.min(5, this.ortho.zoom * (deltaY > 0 ? 0.9 : 1.1)));
      return;
    }
    const s = -deltaY * 0.02;
    const f = this.free;
    f.x += -Math.sin(f.yaw) * Math.cos(f.pitch) * s;
    f.y += Math.sin(f.pitch) * s;
    f.z += -Math.cos(f.yaw) * Math.cos(f.pitch) * s;
  }

  /** Advance the camera by `dt` seconds (clamped to >= 0) at time `now` (ms) and write it to the camera. */
  update(dt: number, now: number): void {
    const d = Math.max(0, dt);
    if (this.tween) {
      const u = Math.min(1, Math.max(0, (now - this.tween.t0) / TWEEN_MS));
      this.setState(lerpState(this.tween.from, this.tween.to, easeInOut(u)));
      if (u >= 1) this.tween = null;
    }
    const k = this.keys;
    const sp = (k['ShiftLeft'] || k['ShiftRight'] ? 30 : 10) * d;
    const yawN = this.mode === 'iso' ? this.ortho.az + Math.PI : this.free.yaw;
    const fx = -Math.sin(yawN);
    const fz = -Math.cos(yawN);
    const rx = Math.cos(yawN);
    const rz = -Math.sin(yawN);
    let mvx = 0;
    let mvz = 0;
    let mvy = 0;
    if (k['KeyW'] || k['ArrowUp']) {
      mvx += fx;
      mvz += fz;
    }
    if (k['KeyS'] || k['ArrowDown']) {
      mvx -= fx;
      mvz -= fz;
    }
    if (k['KeyD'] || k['ArrowRight']) {
      mvx += rx;
      mvz += rz;
    }
    if (k['KeyA'] || k['ArrowLeft']) {
      mvx -= rx;
      mvz -= rz;
    }
    if (k['KeyE'] || k['Space']) mvy += 1;
    if (k['KeyQ']) mvy -= 1;
    if (mvx || mvz || mvy) this.tween = null;
    if (this.mode === 'iso') {
      const o = this.ortho;
      const ps = sp / o.zoom;
      o.tx += mvx * ps;
      o.tz += mvz * ps;
      o.ty = Math.max(0, Math.min(30, o.ty + mvy * ps));
      const cam = this.camera;
      cam.position.set(
        o.tx + Math.sin(o.az) * Math.cos(o.el) * ORTHO_DISTANCE,
        o.ty + Math.sin(o.el) * ORTHO_DISTANCE,
        o.tz + Math.cos(o.az) * Math.cos(o.el) * ORTHO_DISTANCE,
      );
      cam.lookAt(o.tx, o.ty, o.tz);
      if (cam.zoom !== o.zoom) {
        cam.zoom = o.zoom;
        cam.updateProjectionMatrix();
      }
    } else {
      const f = this.free;
      f.x += mvx * sp;
      f.z += mvz * sp;
      f.y = Math.max(0.8, Math.min(120, f.y + mvy * sp));
      this.camera.position.set(f.x, f.y, f.z);
      this.camera.rotation.y = f.yaw;
      this.camera.rotation.x = f.pitch;
    }
  }
}

const ISO_DEFAULT: OrthoState = { tx: 0, ty: 5, tz: 0, az: ISO_AZIMUTH, el: ISO_ELEVATION, zoom: 1 };
