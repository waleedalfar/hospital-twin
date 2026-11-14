/**
 * Materials, boxes and textures: the shared "toolkit" every scene module builds with. Ported from the
 * closure helpers inside `mount()` of reference/engine/pulse3d.js: toon shading with a banded gradient map
 * (NearestFilter), black outlines via EdgesGeometry, 16 px checker floor tiles.
 */
import * as THREE from 'three';

import { mix, paletteFor, shade, STYLES, type Palette, type StyleDef, type StyleName } from './palette';

export type CanvasFactory = () => HTMLCanvasElement;

export interface BoxOptions {
  cast?: boolean;
  outline?: boolean;
  shell?: ShellKind;
}

/** Which parts of the building turn see-through in X-ray mode (PROMPT.md §10.5). */
export type ShellKind = 'floor' | 'wall' | 'cap';

export const TILE_PIXELS = 16;

export class Toolkit {
  readonly st: StyleDef;
  readonly P: Palette;
  readonly grad: THREE.DataTexture | null;
  readonly lineMat: THREE.LineBasicMaterial;
  readonly faintLine: THREE.LineBasicMaterial;
  /** Wall, cap and floor meshes that X-ray makes transparent. */
  readonly shellMeshes: THREE.Mesh[] = [];
  private readonly mats = new Map<string, THREE.Material>();
  private readonly geos = new Map<string, THREE.BoxGeometry>();
  private readonly edges = new Map<string, THREE.EdgesGeometry>();
  private readonly tileCache = new Map<string, THREE.Material>();

  constructor(
    readonly styleName: StyleName,
    readonly createCanvas: CanvasFactory = () => document.createElement('canvas'),
  ) {
    this.st = STYLES[styleName];
    this.P = paletteFor(styleName);
    this.grad = this.st.toon > 0 ? this.makeGradient(this.st.toon) : null;
    this.lineMat = new THREE.LineBasicMaterial({ color: this.st.outlineColor });
    this.faintLine = new THREE.LineBasicMaterial({ color: this.st.outlineColor, transparent: true, opacity: 0.22 });
  }

  /** Apply the style's color mapping (night tint, iso warm tint). */
  mapC(c: string): string {
    return this.st.map ? this.st.map(c) : c;
  }

  private makeGradient(n: number): THREE.DataTexture {
    const d = new Uint8Array(n * 4);
    for (let g = 0; g < n; g++) {
      const v = Math.round(255 * (0.35 + (0.65 * g) / (n - 1)));
      d[g * 4] = v;
      d[g * 4 + 1] = v;
      d[g * 4 + 2] = v;
      d[g * 4 + 3] = 255;
    }
    const tex = new THREE.DataTexture(d, n, 1, THREE.RGBAFormat);
    tex.minFilter = THREE.NearestFilter;
    tex.magFilter = THREE.NearestFilter;
    tex.needsUpdate = true;
    return tex;
  }

  /** Lit material for a color (toon with the banded gradient, or Lambert when the style has no toon steps). */
  M(color: string): THREE.Material {
    const key = 'm' + color;
    let mat = this.mats.get(key);
    if (!mat) {
      const col = this.mapC(color);
      mat = this.grad
        ? new THREE.MeshToonMaterial({ color: col, gradientMap: this.grad })
        : new THREE.MeshLambertMaterial({ color: col });
      this.mats.set(key, mat);
    }
    return mat;
  }

  /** Unlit material (screens, lamps, lit windows). Not tinted by the style map, as in the prototype. */
  B(color: string): THREE.MeshBasicMaterial {
    return new THREE.MeshBasicMaterial({ color });
  }

  private geo(w: number, h: number, d: number): { key: string; geometry: THREE.BoxGeometry } {
    const key = `${w}_${h}_${d}`;
    let geometry = this.geos.get(key);
    if (!geometry) {
      geometry = new THREE.BoxGeometry(w, h, d);
      this.geos.set(key, geometry);
      this.edges.set(key, new THREE.EdgesGeometry(geometry));
    }
    return { key, geometry };
  }

  /** A box mesh with outline edges, added to `parent`. */
  box(
    w: number,
    h: number,
    d: number,
    color: string | THREE.Material,
    x: number,
    y: number,
    z: number,
    parent: THREE.Object3D,
    o: BoxOptions = {},
  ): THREE.Mesh {
    const { key, geometry } = this.geo(w, h, d);
    const m = new THREE.Mesh(geometry, typeof color === 'string' ? this.M(color) : color);
    m.position.set(x, y, z);
    m.castShadow = o.cast !== false;
    m.receiveShadow = true;
    const edges = this.edges.get(key);
    if (this.st.outline && o.outline !== false && edges) m.add(new THREE.LineSegments(edges, this.lineMat));
    if (o.shell) {
      m.userData['shell'] = o.shell;
      this.shellMeshes.push(m);
    }
    parent.add(m);
    return m;
  }

  /** 16 px checker floor texture for a room color, repeated to the room size. */
  tileMat(color: string, w: number, d: number, size = 2): THREE.Material {
    if (!this.st.texture) return this.M(color);
    const key = `${color}|${w}|${d}|${size}`;
    const cached = this.tileCache.get(key);
    if (cached) return cached;
    const cv = this.createCanvas();
    cv.width = TILE_PIXELS;
    cv.height = TILE_PIXELS;
    const x = cv.getContext('2d');
    if (!x) throw new Error('2D canvas is not available for floor textures');
    x.fillStyle = this.mapC(color);
    x.fillRect(0, 0, 16, 16);
    x.fillStyle = this.mapC(shade(color, -0.07));
    x.fillRect(0, 0, 8, 8);
    x.fillRect(8, 8, 8, 8);
    x.fillStyle = this.mapC(shade(color, -0.14));
    x.fillRect(0, 0, 16, 1);
    x.fillRect(0, 0, 1, 16);
    const t = new THREE.CanvasTexture(cv);
    t.magFilter = THREE.NearestFilter;
    t.minFilter = THREE.NearestFilter;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(w / size, d / size);
    const mat = this.grad
      ? new THREE.MeshToonMaterial({ map: t, gradientMap: this.grad })
      : new THREE.MeshLambertMaterial({ map: t });
    this.tileCache.set(key, mat);
    return mat;
  }

  /** A translucent glass material (shaft, partitions). */
  glass(opacity = 0.35): THREE.MeshLambertMaterial {
    return new THREE.MeshLambertMaterial({ color: this.mapC(this.P.glass), transparent: true, opacity });
  }

  mix(a: string, b: string, t: number): string {
    return mix(a, b, t);
  }
}
