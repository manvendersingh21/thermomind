/**
 * Small geometry toolkit: shape helpers that return already-transformed BufferGeometries, and a
 * Bucket that collects them (normalised to non-indexed position/normal/color) and merges them into
 * a single geometry — one draw call per bucket.
 */
import * as THREE from "three";
import type { Vec3 } from "../../types";

const _m = new THREE.Matrix4();
const _q = new THREE.Quaternion();
const _e = new THREE.Euler();
const _p = new THREE.Vector3();
const _s = new THREE.Vector3();
const _a = new THREE.Vector3();
const _b = new THREE.Vector3();
const _up = new THREE.Vector3(0, 1, 0);

export const v3 = (p: Vec3) => new THREE.Vector3(p[0], p[1], p[2]);

/** Apply translation / rotation (XYZ Euler, radians) / scale to a geometry in place. */
export function place(
  g: THREE.BufferGeometry,
  pos: Vec3 = [0, 0, 0],
  rot: Vec3 = [0, 0, 0],
  scale: Vec3 = [1, 1, 1],
): THREE.BufferGeometry {
  _e.set(rot[0], rot[1], rot[2]);
  _q.setFromEuler(_e);
  _p.set(pos[0], pos[1], pos[2]);
  _s.set(scale[0], scale[1], scale[2]);
  _m.compose(_p, _q, _s);
  g.applyMatrix4(_m);
  return g;
}

/** Non-indexed position + normal arrays of a geometry (expands the index if present). */
function flatArrays(g: THREE.BufferGeometry): { p: Float32Array; n: Float32Array } {
  if (!g.getAttribute("normal")) g.computeVertexNormals();
  const pa = g.getAttribute("position") as THREE.BufferAttribute;
  const na = g.getAttribute("normal") as THREE.BufferAttribute;
  const src = pa.array as Float32Array;
  const nsrc = na.array as Float32Array;
  const index = g.index;
  if (!index) {
    return {
      p: src.length === pa.count * 3 ? (src as Float32Array) : Float32Array.from(src),
      n: nsrc.length === na.count * 3 ? (nsrc as Float32Array) : Float32Array.from(nsrc),
    };
  }
  const idx = index.array;
  const p = new Float32Array(idx.length * 3);
  const n = new Float32Array(idx.length * 3);
  for (let i = 0; i < idx.length; i++) {
    const j = idx[i] * 3;
    const o = i * 3;
    p[o] = src[j];
    p[o + 1] = src[j + 1];
    p[o + 2] = src[j + 2];
    n[o] = nsrc[j];
    n[o + 1] = nsrc[j + 1];
    n[o + 2] = nsrc[j + 2];
  }
  return { p, n };
}

function concat(chunks: { p: Float32Array; n: Float32Array; c?: THREE.Color }[], withColor: boolean): THREE.BufferGeometry {
  let total = 0;
  for (const ch of chunks) total += ch.p.length;
  const P = new Float32Array(total);
  const N = new Float32Array(total);
  const C = withColor ? new Float32Array(total) : null;
  let o = 0;
  for (const ch of chunks) {
    P.set(ch.p, o);
    N.set(ch.n, o);
    if (C && ch.c) {
      const { r, g, b } = ch.c;
      for (let i = o; i < o + ch.p.length; i += 3) {
        C[i] = r;
        C[i + 1] = g;
        C[i + 2] = b;
      }
    }
    o += ch.p.length;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(P, 3));
  g.setAttribute("normal", new THREE.BufferAttribute(N, 3));
  if (C) g.setAttribute("color", new THREE.BufferAttribute(C, 3));
  g.computeBoundingSphere();
  return g;
}

/**
 * Collects geometries with a flat per-part vertex colour and merges them into one non-indexed
 * position/normal/color geometry (one draw call).
 */
export class Bucket {
  private chunks: { p: Float32Array; n: Float32Array; c: THREE.Color }[] = [];
  private colors = new Map<string, THREE.Color>();

  add(g: THREE.BufferGeometry, color: THREE.ColorRepresentation): void {
    const key = String(color);
    let c = this.colors.get(key);
    if (!c) {
      c = new THREE.Color(color);
      this.colors.set(key, c);
    }
    const { p, n } = flatArrays(g);
    this.chunks.push({ p, n, c });
    g.dispose();
  }

  get size(): number {
    return this.chunks.length;
  }

  /** Merge everything collected so far. */
  build(): THREE.BufferGeometry {
    const g = concat(this.chunks, true);
    this.chunks = [];
    return g;
  }
}

/** Plain merge (position + normal) for single-material dynamic meshes. */
export function mergePlain(parts: THREE.BufferGeometry[]): THREE.BufferGeometry {
  const chunks = parts.map((g) => {
    const a = flatArrays(g);
    g.dispose();
    return a;
  });
  return concat(chunks, false);
}

// ---------------------------------------------------------------------------------------------
// Templates: unit shapes transformed with a tight loop (much cheaper than constructing a new
// BoxGeometry / CylinderGeometry for each of the ~2k small parts).

const _nm = new THREE.Matrix3();
const templates = new Map<string, { p: Float32Array; n: Float32Array }>();

function template(key: string, make: () => THREE.BufferGeometry) {
  let t = templates.get(key);
  if (!t) {
    const g = make();
    t = flatArrays(g);
    t = { p: Float32Array.from(t.p), n: Float32Array.from(t.n) };
    g.dispose();
    templates.set(key, t);
  }
  return t;
}

/** New geometry = template transformed by matrix (positions) and its normal matrix (normals). */
function fromTemplate(t: { p: Float32Array; n: Float32Array }, m: THREE.Matrix4): THREE.BufferGeometry {
  const e = m.elements;
  _nm.getNormalMatrix(m);
  const k = _nm.elements;
  const len = t.p.length;
  const P = new Float32Array(len);
  const N = new Float32Array(len);
  const tp = t.p;
  const tn = t.n;
  for (let i = 0; i < len; i += 3) {
    const x = tp[i];
    const y = tp[i + 1];
    const z = tp[i + 2];
    P[i] = e[0] * x + e[4] * y + e[8] * z + e[12];
    P[i + 1] = e[1] * x + e[5] * y + e[9] * z + e[13];
    P[i + 2] = e[2] * x + e[6] * y + e[10] * z + e[14];
    const a = tn[i];
    const b = tn[i + 1];
    const c = tn[i + 2];
    let nx = k[0] * a + k[3] * b + k[6] * c;
    let ny = k[1] * a + k[4] * b + k[7] * c;
    let nz = k[2] * a + k[5] * b + k[8] * c;
    const l = Math.hypot(nx, ny, nz) || 1;
    nx /= l;
    ny /= l;
    nz /= l;
    N[i] = nx;
    N[i + 1] = ny;
    N[i + 2] = nz;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(P, 3));
  g.setAttribute("normal", new THREE.BufferAttribute(N, 3));
  return g;
}

const unitBox = () => template("box", () => new THREE.BoxGeometry(1, 1, 1));
const unitCyl = (seg: number, open: boolean) =>
  template(`cyl${seg}${open ? "o" : ""}`, () => new THREE.CylinderGeometry(1, 1, 1, seg, 1, open));

function composeM(pos: Vec3, rot: Vec3, scale: Vec3): THREE.Matrix4 {
  _e.set(rot[0], rot[1], rot[2]);
  _q.setFromEuler(_e);
  _p.set(pos[0], pos[1], pos[2]);
  _s.set(scale[0], scale[1], scale[2]);
  return _m.compose(_p, _q, _s);
}

// ---------------------------------------------------------------------------------------------
// Shape helpers. All return a new geometry already in world (or caller-local) coordinates.

export function box(w: number, h: number, d: number, pos: Vec3, rot: Vec3 = [0, 0, 0]): THREE.BufferGeometry {
  return fromTemplate(unitBox(), composeM(pos, rot, [w, h, d]));
}

/** Axis-aligned box from min/max corners. */
export function boxMM(x0: number, y0: number, z0: number, x1: number, y1: number, z1: number): THREE.BufferGeometry {
  return box(x1 - x0, y1 - y0, z1 - z0, [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2]);
}

/** Cylinder / cone along +X from x0 to x1 (radius r0 at x0, r1 at x1), axis at (y, z). */
export function cylX(
  r0: number,
  r1: number,
  x0: number,
  x1: number,
  y: number,
  z: number,
  seg = 20,
  open = false,
): THREE.BufferGeometry {
  // CylinderGeometry: axis +Y, radiusTop at +Y. Rotating by -90° about Z maps +Y → +X.
  if (r0 === r1) return fromTemplate(unitCyl(seg, open), composeM([(x0 + x1) / 2, y, z], [0, 0, -Math.PI / 2], [r0, x1 - x0, r0]));
  const g = new THREE.CylinderGeometry(r1, r0, x1 - x0, seg, 1, open);
  return place(g, [(x0 + x1) / 2, y, z], [0, 0, -Math.PI / 2]);
}

/** Vertical cylinder from y0 to y1 at (x, z). */
export function cylY(r0: number, r1: number, y0: number, y1: number, x: number, z: number, seg = 16, open = false) {
  if (r0 === r1) return fromTemplate(unitCyl(seg, open), composeM([x, (y0 + y1) / 2, z], [0, 0, 0], [r0, y1 - y0, r0]));
  const g = new THREE.CylinderGeometry(r1, r0, y1 - y0, seg, 1, open);
  return place(g, [x, (y0 + y1) / 2, z]);
}

/** Cylinder along +Z from z0 to z1 at (x, y). */
export function cylZ(r0: number, r1: number, z0: number, z1: number, x: number, y: number, seg = 16, open = false) {
  if (r0 === r1) return fromTemplate(unitCyl(seg, open), composeM([x, y, (z0 + z1) / 2], [Math.PI / 2, 0, 0], [r0, z1 - z0, r0]));
  const g = new THREE.CylinderGeometry(r1, r0, z1 - z0, seg, 1, open);
  return place(g, [x, y, (z0 + z1) / 2], [Math.PI / 2, 0, 0]);
}

function betweenMatrix(a: Vec3, b: Vec3, sx: number, sz: number): THREE.Matrix4 {
  _a.set(a[0], a[1], a[2]);
  _b.set(b[0], b[1], b[2]);
  _p.subVectors(_b, _a);
  const len = _p.length();
  _p.divideScalar(len || 1);
  _q.setFromUnitVectors(_up, _p);
  _p.copy(_a).add(_b).multiplyScalar(0.5);
  _s.set(sx, len, sz);
  return _m.compose(_p, _q, _s);
}

/** Round bar between two points. */
export function rod(a: Vec3, b: Vec3, r: number, seg = 8): THREE.BufferGeometry {
  return fromTemplate(unitCyl(seg, false), betweenMatrix(a, b, r, r));
}

/** Square-section beam between two points. */
export function beam(a: Vec3, b: Vec3, w: number, d = w): THREE.BufferGeometry {
  return fromTemplate(unitBox(), betweenMatrix(a, b, w, d));
}

/** Ring (torus) with its axis along X. */
export function torusX(R: number, r: number, x: number, y: number, z: number, seg = 32, tubeSeg = 6) {
  return place(new THREE.TorusGeometry(R, r, tubeSeg, seg), [x, y, z], [0, Math.PI / 2, 0]);
}

/** Ring (torus) with its axis along Y (lying flat). */
export function torusY(R: number, r: number, x: number, y: number, z: number, seg = 32, tubeSeg = 6) {
  return place(new THREE.TorusGeometry(R, r, tubeSeg, seg), [x, y, z], [Math.PI / 2, 0, 0]);
}

/** Ring (torus) with its axis along Z. */
export function torusZ(R: number, r: number, x: number, y: number, z: number, seg = 24, tubeSeg = 6) {
  return place(new THREE.TorusGeometry(R, r, tubeSeg, seg), [x, y, z]);
}

export function sphere(r: number, pos: Vec3, scale: Vec3 = [1, 1, 1], seg = 16): THREE.BufferGeometry {
  return place(new THREE.SphereGeometry(r, seg, Math.max(6, Math.round(seg * 0.6))), pos, [0, 0, 0], scale);
}

/** Hemisphere dome along ±X (sign = +1 bulges to +X). */
export function domeX(r: number, depth: number, x: number, y: number, z: number, sign: 1 | -1, seg = 20) {
  const g = new THREE.SphereGeometry(r, seg, 8, 0, Math.PI * 2, 0, Math.PI / 2); // dome toward +Y
  return place(g, [x, y, z], [0, 0, sign > 0 ? -Math.PI / 2 : Math.PI / 2], [1, depth / r, 1]);
}

/** Tube along a centripetal Catmull-Rom curve through the points. */
export function tubeAlong(points: Vec3[], r: number, tubular = 64, radial = 8): THREE.BufferGeometry {
  const curve = new THREE.CatmullRomCurve3(points.map(v3), false, "centripetal");
  return new THREE.TubeGeometry(curve, tubular, r, radial, false);
}

/** Polyline tube (straight segments), for thin impulse lines / cables. */
export function polyRod(points: Vec3[], r: number, seg = 6): THREE.BufferGeometry[] {
  const out: THREE.BufferGeometry[] = [];
  for (let i = 0; i < points.length - 1; i++) out.push(rod(points[i], points[i + 1], r, seg));
  return out;
}

/** A sagging conductor between two points (parabolic sag, metres of drop at mid-span). */
export function sagLine(a: Vec3, b: Vec3, sag: number, r: number, n = 16): THREE.BufferGeometry {
  const pts: THREE.Vector3[] = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    pts.push(
      new THREE.Vector3(
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t - sag * 4 * t * (1 - t),
        a[2] + (b[2] - a[2]) * t,
      ),
    );
  }
  const curve = new THREE.CatmullRomCurve3(pts, false, "centripetal");
  return new THREE.TubeGeometry(curve, n * 2, r, 5, false);
}

/** Lathe around the Y axis from (r, y) profile pairs, placed at (x, 0, z). */
export function lathe(profile: [number, number][], x: number, z: number, seg = 32): THREE.BufferGeometry {
  const g = new THREE.LatheGeometry(
    profile.map(([r, y]) => new THREE.Vector2(r, y)),
    seg,
  );
  return place(g, [x, 0, z]);
}

/** Copy of a geometry with reversed winding and negated normals (an inner skin for open shells). */
export function flipped(g: THREE.BufferGeometry): THREE.BufferGeometry {
  const n = g.index ? g.toNonIndexed() : g.clone();
  if (!n.getAttribute("normal")) n.computeVertexNormals();
  const p = n.getAttribute("position") as THREE.BufferAttribute;
  const nn = n.getAttribute("normal") as THREE.BufferAttribute;
  for (const attr of [p, nn]) {
    const a = attr.array as Float32Array;
    for (let i = 0; i < attr.count; i += 3) {
      for (let k = 0; k < 3; k++) {
        const i1 = (i + 1) * 3 + k;
        const i2 = (i + 2) * 3 + k;
        const t = a[i1];
        a[i1] = a[i2];
        a[i2] = t;
      }
    }
  }
  const na = nn.array as Float32Array;
  for (let i = 0; i < na.length; i++) na[i] = -na[i];
  return n;
}

/** Both skins of an open surface (outer + flipped inner), so it reads from either side. */
export function twoSided(g: THREE.BufferGeometry): THREE.BufferGeometry[] {
  return [flipped(g), g];
}

/**
 * Duct transition along +X from a circle (at x0) to a rounded rectangle (superellipse, at x1).
 * Returns an indexed open surface with smooth normals.
 */
export function roundToRect(
  x0: number,
  x1: number,
  circle: { cy: number; cz: number; r: number },
  rect: { cy: number; cz: number; hy: number; hz: number },
  seg = 40,
  rings = 8,
  n = 6,
): THREE.BufferGeometry {
  const pos: number[] = [];
  const idx: number[] = [];
  const e = 2 / n;
  for (let i = 0; i <= rings; i++) {
    const t = i / rings;
    const k = t * t * (3 - 2 * t);
    const x = x0 + (x1 - x0) * t;
    for (let j = 0; j <= seg; j++) {
      const a = (j / seg) * Math.PI * 2;
      const c = Math.cos(a);
      const s = Math.sin(a);
      const zc = circle.cz + circle.r * c;
      const yc = circle.cy + circle.r * s;
      const zr = rect.cz + rect.hz * Math.sign(c) * Math.pow(Math.abs(c), e);
      const yr = rect.cy + rect.hy * Math.sign(s) * Math.pow(Math.abs(s), e);
      pos.push(x, yc + (yr - yc) * k, zc + (zr - zc) * k);
    }
  }
  for (let i = 0; i < rings; i++) {
    for (let j = 0; j < seg; j++) {
      const a = i * (seg + 1) + j;
      const b = a + seg + 1;
      idx.push(a, b, a + 1, b, b + 1, a + 1);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

/**
 * Box whose bottom and top rectangles differ (hopper / duct taper). Each rectangle is given as
 * centre x/z and half extents.
 */
export function taperBox(
  y0: number,
  bot: { cx: number; cz: number; hx: number; hz: number },
  y1: number,
  top: { cx: number; cz: number; hx: number; hz: number },
): THREE.BufferGeometry {
  const g = new THREE.BoxGeometry(1, 1, 1);
  const p = g.getAttribute("position") as THREE.BufferAttribute;
  for (let i = 0; i < p.count; i++) {
    const isTop = p.getY(i) > 0;
    const r = isTop ? top : bot;
    p.setXYZ(i, r.cx + Math.sign(p.getX(i)) * r.hx, isTop ? y1 : y0, r.cz + Math.sign(p.getZ(i)) * r.hz);
  }
  g.computeVertexNormals();
  return g;
}
