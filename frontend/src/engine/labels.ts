/**
 * Text and marker sprites: room labels with live counts (512x128 canvases), the red "!" sprite, and the
 * always-visible X-ray markers (PROMPT.md §10.2, §10.5). Ported from `label`, `bangTexture` and `marker` in
 * reference/engine/pulse3d.js.
 */
import * as THREE from 'three';

import type { Toolkit } from './materials';

export const LABEL_WIDTH = 512;
export const LABEL_HEIGHT = 128;
const FONT_NAME = '"Pixelify Sans", monospace';
const FONT_SUB = '"VT323", monospace';

export interface LabelSprite extends THREE.Sprite {
  userData: { setText: (text: string, sub: string, subColor: string) => void; text: string; sub: string };
}

export class LabelFactory {
  private readonly redraws: (() => void)[] = [];
  private readonly markTex = new Map<string, THREE.CanvasTexture>();
  private bangTex: THREE.CanvasTexture | null = null;

  constructor(private readonly tk: Toolkit) {}

  /** Redraw every label (call after fonts finish loading). */
  redrawAll(): void {
    this.redraws.forEach((f) => f());
  }

  /** A label sprite with a title and a short colored count, redrawable through `userData.setText`. */
  label(text: string, sub: string, subColor: string, x: number, y: number, z: number, w: number, parent: THREE.Object3D): LabelSprite {
    const tk = this.tk;
    const cv = tk.createCanvas();
    cv.width = LABEL_WIDTH;
    cv.height = LABEL_HEIGHT;
    const tex = new THREE.CanvasTexture(cv);
    tex.magFilter = THREE.NearestFilter;
    tex.minFilter = THREE.NearestFilter;
    const state = { text, sub, subColor };
    const draw = (): void => {
      const g = cv.getContext('2d');
      if (!g) throw new Error('2D canvas is not available for labels');
      g.imageSmoothingEnabled = false;
      g.setTransform(2, 0, 0, 2, 0, 0);
      g.clearRect(0, 0, 256, 64);
      g.fillStyle = tk.mapC(tk.P.labelBg);
      g.fillRect(0, 4, 256, 54);
      g.fillStyle = tk.st.outlineColor;
      g.fillRect(0, 56, 256, 6);
      g.textBaseline = 'middle';
      g.font = `700 26px ${FONT_NAME}`;
      const tw = g.measureText(state.text).width;
      g.font = `400 30px ${FONT_SUB}`;
      const sw = state.sub ? g.measureText(state.sub).width + 12 : 0;
      const x0 = Math.max(6, (256 - tw - sw) / 2);
      g.font = `700 26px ${FONT_NAME}`;
      g.fillStyle = tk.P.labelInk;
      g.fillText(state.text, x0, 31);
      if (state.sub) {
        g.font = `400 30px ${FONT_SUB}`;
        g.fillStyle = state.subColor || tk.P.labelInk;
        g.fillText(state.sub, x0 + tw + 12, 32);
      }
      tex.needsUpdate = true;
    };
    draw();
    this.redraws.push(draw);
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false })) as unknown as LabelSprite;
    s.renderOrder = 10;
    s.position.set(x, y, z);
    const ww = (w || 5.5) * 1.25;
    s.scale.set(ww, ww / 4, 1);
    s.userData = {
      text,
      sub,
      setText: (t, sb, color) => {
        if (state.text === t && state.sub === sb && state.subColor === color) return;
        state.text = t;
        state.sub = sb;
        state.subColor = color;
        s.userData.text = t;
        s.userData.sub = sb;
        draw();
      },
    };
    parent.add(s);
    return s;
  }

  /** The red "!" texture shown over high-risk patients. */
  bangTexture(): THREE.CanvasTexture {
    if (this.bangTex) return this.bangTex;
    const cv = this.tk.createCanvas();
    cv.width = 16;
    cv.height = 16;
    const g = cv.getContext('2d');
    if (!g) throw new Error('2D canvas is not available for sprites');
    g.fillStyle = '#ffffff';
    g.fillRect(0, 0, 16, 16);
    g.fillStyle = this.tk.P.high;
    g.fillRect(1, 1, 14, 14);
    g.fillStyle = '#ffffff';
    g.fillRect(7, 3, 2, 7);
    g.fillRect(7, 11, 2, 2);
    const t = new THREE.CanvasTexture(cv);
    t.magFilter = THREE.NearestFilter;
    t.minFilter = THREE.NearestFilter;
    this.bangTex = t;
    return t;
  }

  /** Markers are hidden until X-ray is on; new markers follow the current setting. */
  readonly markers = new Set<THREE.Sprite>();
  private markersVisible = false;

  setMarkersVisible(visible: boolean): void {
    this.markersVisible = visible;
    this.markers.forEach((m) => (m.visible = visible));
  }

  private markerTexture(color: string): THREE.CanvasTexture {
    let tex = this.markTex.get(color);
    if (!tex) {
      const cv = this.tk.createCanvas();
      cv.width = 12;
      cv.height = 12;
      const g = cv.getContext('2d');
      if (!g) throw new Error('2D canvas is not available for markers');
      g.fillStyle = this.tk.st.outlineColor;
      g.fillRect(2, 0, 8, 12);
      g.fillRect(0, 2, 12, 8);
      g.fillStyle = color;
      g.fillRect(3, 1, 6, 10);
      g.fillRect(1, 3, 10, 6);
      g.fillStyle = '#ffffff';
      g.fillRect(3, 3, 2, 2);
      tex = new THREE.CanvasTexture(cv);
      tex.magFilter = THREE.NearestFilter;
      tex.minFilter = THREE.NearestFilter;
      this.markTex.set(color, tex);
    }
    return tex;
  }

  /** A pixel marker sprite of `color`, always drawn on top (`depthTest: false`). */
  marker(color: string, parent: THREE.Object3D, x: number, y: number, z: number, size = 0.5): THREE.Sprite {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.markerTexture(color), depthTest: false }));
    s.renderOrder = 12;
    s.scale.set(size, size, 1);
    s.position.set(x, y, z);
    s.visible = this.markersVisible;
    s.userData['markerColor'] = color;
    parent.add(s);
    this.markers.add(s);
    return s;
  }

  tintMarker(s: THREE.Sprite, color: string): void {
    if (s.userData['markerColor'] === color) return;
    s.userData['markerColor'] = color;
    s.material.map = this.markerTexture(color);
    s.material.needsUpdate = true;
  }

  removeMarker(s: THREE.Sprite): void {
    s.parent?.remove(s);
    this.markers.delete(s);
  }
}
