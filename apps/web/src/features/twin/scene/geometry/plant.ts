/**
 * Procedural geometry for the whole plant. Everything is built once, merged into a few buckets
 * (static finishes + dynamic parts) and handed to Equipment.tsx.
 *
 * Positions come from layout.ts (EQUIPMENT_BY_ID hit boxes, shaft heights and FLOW_PATHS).
 */
import * as THREE from "three";
import { EQUIPMENT_BY_ID as E, FLOW_PATHS, GT_AXIS_Y, ST_AXIS_Y } from "../../layout";
import type { Vec3 } from "../../types";
import { FINISHES, PAL, PIPE_STYLE, type Finish } from "../materials";
import {
  beam,
  box,
  boxMM,
  Bucket,
  cylX,
  cylY,
  cylZ,
  domeX,
  flipped,
  lathe,
  mergePlain,
  place,
  polyRod,
  rod,
  roundToRect,
  sagLine,
  sphere,
  taperBox,
  torusX,
  torusY,
  torusZ,
  tubeAlong,
  twoSided,
  v3,
} from "./builder";

const Y = GT_AXIS_Y;
const SY = ST_AXIS_Y;
const PI = Math.PI;

/** Pressure gauge on the compressor discharge casing (dial faces +Z, tilted up toward the camera). */
export const GAUGE = { pos: [-6.95, Y + 1.68, 0.05] as Vec3, tilt: -0.35, needleZ: 0.045 };

export interface PlantGeometry {
  statics: Record<Finish, THREE.BufferGeometry>;
  /** GT rotor (compressor + turbine + coupling shaft), local to the GT axis (y = 0, z = 0). */
  rotor: THREE.BufferGeometry;
  /** Semi-transparent compressor / combustor / turbine casings (vertex coloured). */
  casing: THREE.BufferGeometry;
  filterFace: THREE.BufferGeometry;
  cans: THREE.BufferGeometry;
  genGlow: THREE.BufferGeometry;
  /** Needle local to the gauge pivot, pointing +Y. */
  needle: THREE.BufferGeometry;
  lamp52g: THREE.BufferGeometry;
  lampHvsg: THREE.BufferGeometry;
  gsuTank: THREE.BufferGeometry;
}

type Add = (f: Finish, g: THREE.BufferGeometry | THREE.BufferGeometry[], color: string) => void;

export function buildPlant(): PlantGeometry {
  const buckets = Object.fromEntries(FINISHES.map((f) => [f, new Bucket()])) as Record<Finish, Bucket>;
  const add: Add = (f, g, color) => {
    for (const x of Array.isArray(g) ? g : [g]) buckets[f].add(x, color);
  };
  const rotor = new Bucket();
  const casing = new Bucket();
  const dyn = {
    filterFace: [] as THREE.BufferGeometry[],
    cans: [] as THREE.BufferGeometry[],
    genGlow: [] as THREE.BufferGeometry[],
    lamp52g: [] as THREE.BufferGeometry[],
    lampHvsg: [] as THREE.BufferGeometry[],
    gsuTank: [] as THREE.BufferGeometry[],
  };

  ground(add);
  ambientStation(add);
  filterHouse(add, dyn.filterFace);
  gasTurbine(add, rotor, casing, dyn.cans);
  fuelSkid(add);
  hrsg(add);
  stack(add);
  steamBlock(add);
  coolingTower(add);
  generator(add, dyn.genGlow);
  electrical(add, dyn);
  busbarAndLine(add);
  pipes(add);

  const statics = Object.fromEntries(FINISHES.map((f) => [f, buckets[f].build()])) as Record<
    Finish,
    THREE.BufferGeometry
  >;

  // Needle: pivot at origin, pointing +Y.
  const needle = mergePlain([
    box(0.028, 0.25, 0.012, [0, 0.095, 0]),
    box(0.04, 0.06, 0.012, [0, -0.03, 0]),
    cylZ(0.032, 0.032, -0.008, 0.014, 0, 0, 12),
  ]);

  return {
    statics,
    rotor: rotor.build(),
    casing: casing.build(),
    filterFace: mergePlain(dyn.filterFace),
    cans: mergePlain(dyn.cans),
    genGlow: mergePlain(dyn.genGlow),
    needle,
    lamp52g: mergePlain(dyn.lamp52g),
    lampHvsg: mergePlain(dyn.lampHvsg),
    gsuTank: mergePlain(dyn.gsuTank),
  };
}

// =============================================================================================
// Ground: foundation pads, bund floor, switchyard gravel, roads.

function ground(add: Add) {
  const C = PAL.concrete;
  add("matte", boxMM(-18.2, 0, -2.8, 0.8, 0.15, 2.8), C); // GT train
  add("matte", boxMM(0.8, 0, -3.4, 11.8, 0.15, 3.4), C); // HRSG + stack
  add("matte", boxMM(-3.8, 0, 7.6, 6.2, 0.15, 12.4), C); // ST block
  add("matte", boxMM(-15.9, 0, 3.0, -14.1, 0.12, 4.8), C); // 52G
  add("matte", boxMM(-6.5, 0, -7.1, -3.5, 0.12, -4.9), C); // fuel skid
  add("matte", boxMM(-12.8, 0, 11.9, 5.2, 0.06, 15.3), PAL.gravel); // switchyard
  // Roads with dashed centre lines.
  add("matte", boxMM(-26, 0, -11, 26, 0.03, -8.4), PAL.road);
  add("matte", boxMM(-23, 0, -8.4, -20.4, 0.03, 21), PAL.road);
  for (let x = -24; x < 25; x += 2.4) add("matte", boxMM(x, 0.03, -9.75, x + 1.2, 0.04, -9.65), PAL.roadLine);
  for (let z = -7.5; z < 20; z += 2.4) add("matte", boxMM(-21.75, 0.03, z, -21.65, 0.04, z + 1.2), PAL.roadLine);
}

// =============================================================================================

function ambientStation(add: Add) {
  const [ax, , az] = E.ambient_station.pos;
  add("matte", boxMM(ax - 0.45, 0, az - 0.45, ax + 1.0, 0.2, az + 0.45), PAL.concreteDark);
  add("metal", cylY(0.06, 0.045, 0.2, 4.35, ax, az, 10), PAL.steel);
  add("metal", rod([ax, 4.35, az], [ax, 4.75, az], 0.012, 5), PAL.steelDark); // lightning rod
  // Stevenson screen on its stand.
  const sx = ax + 0.6;
  for (const dx of [-0.17, 0.17])
    for (const dz of [-0.14, 0.14]) add("metal", rod([sx + dx, 0.2, az + dz], [sx + dx, 1.25, az + dz], 0.022, 6), PAL.steelDark);
  add("paint", box(0.52, 0.55, 0.44, [sx, 1.5, az]), PAL.white);
  for (let i = 0; i < 4; i++) add("paint", box(0.55, 0.025, 0.47, [sx, 1.3 + i * 0.12, az]), PAL.white);
  add("paint", box(0.62, 0.05, 0.54, [sx, 1.81, az], [0, 0, 0.08]), PAL.white);
  // Logger box + solar panel on the mast.
  add("paint", box(0.26, 0.34, 0.16, [ax, 1.1, az + 0.12]), PAL.steelLight);
  add("paint", box(0.42, 0.025, 0.3, [ax - 0.1, 2.6, az - 0.22], [-0.7, 0, 0]), "#1e3a8a");
  // Crossarm with sensors.
  add("metal", beam([ax - 0.55, 3.65, az], [ax + 0.55, 3.65, az], 0.05), PAL.steel);
  add("paint", cylY(0.06, 0.06, 3.45, 3.65, ax - 0.5, az, 10), PAL.white);
  add("paint", cylY(0.05, 0.05, 3.65, 3.85, ax + 0.5, az, 10), PAL.white);
  // Cup anemometer.
  add("metal", cylY(0.04, 0.04, 4.35, 4.5, ax, az, 8), PAL.steelDark);
  for (let k = 0; k < 3; k++) {
    const a = (k * 2 * PI) / 3;
    const tip: Vec3 = [ax + Math.cos(a) * 0.28, 4.45, az + Math.sin(a) * 0.28];
    add("metal", rod([ax, 4.45, az], tip, 0.012, 5), PAL.steelDark);
    add("paint", sphere(0.065, tip, [1, 0.8, 1], 10), PAL.dark);
  }
}

// =============================================================================================

function filterHouse(add: Add, face: THREE.BufferGeometry[]) {
  const { pos, size } = E.filter_house;
  const [fx, fy] = pos;
  const x0 = fx - size[0] / 2 + 0.3; // -12.0
  const x1 = fx + size[0] / 2; // -8.7
  const y0 = fy - size[1] / 2; // 5.9
  const y1 = fy + size[1] / 2; // 9.1
  const hz = size[2] / 2 - 0.05; // 2.55

  add("metal", boxMM(x0, y0, -hz, x1, y1, hz), PAL.steelLight);
  add("metal", boxMM(x0 - 0.45, y1, -hz - 0.12, x1 + 0.1, y1 + 0.12, hz + 0.12), PAL.steel); // roof / canopy
  add("metal", boxMM(x0 - 0.05, y0 - 0.1, -hz - 0.05, x1 + 0.05, y0 + 0.02, hz + 0.05), PAL.steelDark); // sill

  // -X face: filter elements (dynamic colour) behind a framed grid.
  const fw = 2 * hz - 0.2;
  const fh = y1 - y0 - 0.3;
  face.push(place(new THREE.PlaneGeometry(fw, fh), [x0 - 0.015, fy, 0], [0, -PI / 2, 0]));
  const cols = 6;
  const rows = 4;
  const cw = fw / cols;
  const ch = fh / rows;
  for (let c = 0; c < cols; c++)
    for (let r = 0; r < rows; r++) {
      const cz = -fw / 2 + cw * (c + 0.5);
      const cy = fy - fh / 2 + ch * (r + 0.5);
      for (const dz of [-0.2, 0.2])
        for (const dy of [-0.16, 0.16]) face.push(cylX(0.13, 0.13, x0 - 0.1, x0 - 0.01, cy + dy, cz + dz, 12));
    }
  for (let c = 0; c <= cols; c++)
    add("metal", boxMM(x0 - 0.13, fy - fh / 2 - 0.04, -fw / 2 + cw * c - 0.04, x0, fy + fh / 2 + 0.04, -fw / 2 + cw * c + 0.04), PAL.steelDark);
  for (let r = 0; r <= rows; r++)
    add("metal", boxMM(x0 - 0.13, fy - fh / 2 + ch * r - 0.035, -fw / 2, x0, fy - fh / 2 + ch * r + 0.035, fw / 2), PAL.steelDark);

  // ±Z sides: two tiers of weather hoods with louvre fins underneath.
  for (const s of [-1, 1]) {
    for (const ty of [7.45, 8.6]) {
      add("metal", box(x1 - x0 - 0.2, 0.04, 0.6, [(x0 + x1) / 2, ty, s * (hz + 0.24)], [s * 0.55, 0, 0]), PAL.steel);
      for (const ex of [x0 + 0.12, x1 - 0.12]) add("metal", box(0.04, 0.5, 0.42, [ex, ty - 0.2, s * (hz + 0.2)]), PAL.steel);
      for (let k = 1; k <= 3; k++)
        add("metal", box(x1 - x0 - 0.3, 0.025, 0.16, [(x0 + x1) / 2, ty - 0.12 * k - 0.04, s * (hz + 0.08)], [s * 0.7, 0, 0]), PAL.steelDark);
    }
  }

  // Support structure.
  const lx = [x0 + 0.15, x1 - 0.15];
  const lz = [-2.35, 2.35];
  for (const x of lx)
    for (const z of lz) {
      add("metal", boxMM(x - 0.11, 0.15, z - 0.11, x + 0.11, y0 - 0.1, z + 0.11), PAL.steelDark);
      add("metal", boxMM(x - 0.22, 0.15, z - 0.22, x + 0.22, 0.2, z + 0.22), PAL.steelDeep);
    }
  for (const z of lz) {
    add("metal", beam([lx[0], 3.6, z], [lx[1], 3.6, z], 0.12), PAL.steelDark);
    add("metal", beam([lx[0], 3.6, z], [lx[1], y0 - 0.15, z], 0.08), PAL.steelDark);
    add("metal", beam([lx[1], 3.6, z], [lx[0], y0 - 0.15, z], 0.08), PAL.steelDark);
    add("metal", beam([lx[0], 0.3, z], [lx[1], 3.5, z], 0.07), PAL.steelDark);
  }
  for (const x of lx) add("metal", beam([x, y0 - 0.16, -2.35], [x, y0 - 0.16, 2.35], 0.14), PAL.steelDark);

  // Hopper + down-duct + compressor inlet plenum (centred on the GT axis at x ≈ -10.5).
  const dx0 = -11.0;
  const dx1 = -10.0;
  add("metal", taperBox(5.2, { cx: -10.5, cz: 0, hx: 0.5, hz: 1.5 }, y0, { cx: (x0 + x1) / 2, cz: 0, hx: 1.4, hz: 2.3 }), PAL.steel);
  add("metal", boxMM(dx0, 4.0, -1.5, dx1, 5.2, 1.5), PAL.steelLight);
  add("metal", boxMM(dx0 - 0.06, 5.1, -1.56, dx1 + 0.06, 5.2, 1.56), PAL.steelDark);
  add("metal", boxMM(dx0 - 0.06, 4.0, -1.56, dx1 + 0.06, 4.1, 1.56), PAL.steelDark);
  add("metal", boxMM(dx0, Y - 1.8, -1.8, dx1, Y + 1.8, 1.8), PAL.steelLight); // plenum
  for (const x of [dx0 + 0.02, dx1 - 0.02])
    for (const yy of [Y - 0.9, Y, Y + 0.9]) add("metal", boxMM(x - 0.05, yy - 0.04, -1.86, x + 0.05, yy + 0.04, 1.86), PAL.steel);
  add("metal", boxMM(dx0 + 0.1, 0.15, -1.6, dx1 - 0.1, Y - 1.8, 1.6), PAL.steelDeep);

  // AFDP transmitter with two impulse lines to the filter house.
  const [tx, ty, tz] = E.afdp_tx.pos;
  add("paint", box(0.3, 0.36, 0.2, [tx, ty, tz]), PAL.blue);
  add("paint", cylZ(0.12, 0.12, tz - 0.08, tz + 0.12, tx, ty + 0.3, 14), PAL.white);
  add("metal", boxMM(tx - 0.05, ty - 0.05, hz, tx + 0.05, ty + 0.05, tz - 0.1), PAL.steelDark);
  add("metal", box(0.36, 0.08, 0.16, [tx, ty - 0.22, tz]), PAL.steelDark);
  add("metal", polyRod([[tx - 0.12, ty - 0.26, tz], [tx - 0.12, ty - 0.36, tz], [x0 + 0.4, ty - 0.36, tz], [x0 + 0.4, ty - 0.36, hz]], 0.022), PAL.steel);
  add("metal", polyRod([[tx + 0.12, ty - 0.26, tz], [tx + 0.12, ty - 0.46, tz], [x1 - 0.5, ty - 0.46, tz], [x1 - 0.5, ty - 0.46, hz]], 0.022), PAL.steel);
}

// =============================================================================================

/** Compressor casing radius at x (cone 1.5 → 1.0 over x -10..-6). */
const rC = (x: number) => 1.5 + ((x + 10) / 4) * -0.5;
/** Turbine casing radius at x (1.1 → 1.7 over x -4.4..-2). */
const rT = (x: number) => 1.1 + ((x + 4.4) / 2.4) * 0.6;

function bladeRow(
  rotor: Bucket,
  x: number,
  hub: number,
  tip: number,
  n: number,
  chord: number,
  twist: number,
  color: string,
) {
  rotor.add(cylX(hub + 0.03, hub + 0.03, x - chord * 0.35, x + chord * 0.35, 0, 0, 20), color);
  const len = tip - hub;
  for (let k = 0; k < n; k++) {
    const g = new THREE.BoxGeometry(chord, len, 0.028);
    g.rotateY(twist);
    g.translate(0, hub + len / 2, 0);
    g.rotateX((k / n) * PI * 2);
    g.translate(x, 0, 0);
    rotor.add(g, color);
  }
}

function gasTurbine(add: Add, rotor: Bucket, casing: Bucket, cans: THREE.BufferGeometry[]) {
  const CAS = "#c3cfdc";
  const CAS_WARM = "#d9c3a8";

  // Base skid along the train.
  add("metal", boxMM(-10, 0.15, -1.25, -1.9, 0.4, 1.25), PAL.steelDeep);

  // --- Compressor x -10..-6 ---------------------------------------------------------------
  casing.add(cylX(1.5, 1.0, -10, -6, Y, 0, 32, true), CAS);
  for (const x of [-10, -9, -8, -7, -6]) add("metal", torusX(rC(x) + 0.01, 0.045, x, Y, 0, 36, 6), PAL.steelDark);
  add("metal", boxMM(-9.65, 0.4, -0.7, -9.25, Y - rC(-9.45) + 0.08, 0.7), PAL.steelDark);
  add("metal", boxMM(-6.75, 0.4, -0.55, -6.35, Y - rC(-6.55) + 0.08, 0.55), PAL.steelDark);

  // Rotor: coupling shaft + drum + 10 bladed stages.
  rotor.add(cylX(0.17, 0.17, -13.2, -9.9, 0, 0, 12), PAL.steel);
  for (const [a, b] of [
    [-12.35, -12.25],
    [-12.25, -12.15],
  ])
    rotor.add(cylX(0.38, 0.38, a, b, 0, 0, 20), PAL.steelDark);
  for (let k = 0; k < 8; k++) {
    const a = (k / 8) * PI * 2;
    rotor.add(box(0.26, 0.07, 0.07, [-12.25, Math.cos(a) * 0.3, Math.sin(a) * 0.3]), PAL.steelDeep);
  }
  rotor.add(cylX(0.55, 0.72, -10, -6, 0, 0, 24), PAL.steelLight);
  for (let i = 0; i < 10; i++) {
    const x = -9.72 + i * 0.37;
    const hub = 0.55 + ((x + 10) / 4) * 0.17;
    const tip = rC(x) - 0.08;
    bladeRow(rotor, x, hub, tip, 18, 0.22 - i * 0.01, 0.6, i % 2 ? PAL.steel : "#bcc5d0");
  }

  // --- Compressor discharge gauge (dial static, needle dynamic) -----------------------------
  const gm = new THREE.Matrix4().compose(
    v3(GAUGE.pos),
    new THREE.Quaternion().setFromEuler(new THREE.Euler(GAUGE.tilt, 0, 0)),
    new THREE.Vector3(1, 1, 1),
  );
  const gl = (g: THREE.BufferGeometry) => g.applyMatrix4(gm);
  add("metal", gl(cylZ(0.34, 0.34, -0.07, 0.025, 0, 0, 24)), PAL.steelDark);
  add("paint", gl(cylZ(0.3, 0.3, 0.025, 0.03, 0, 0, 24)), PAL.white);
  add("metal", gl(torusZ(0.31, 0.025, 0, 0, 0.03, 24, 6)), PAL.steel);
  for (let k = 0; k <= 8; k++) {
    const a = ((-120 + k * 30) * PI) / 180;
    const major = k % 2 === 0;
    add(
      "paint",
      gl(box(0.018, major ? 0.07 : 0.045, 0.01, [Math.sin(a) * 0.235, Math.cos(a) * 0.235, 0.034], [0, 0, -a])),
      k >= 7 ? PAL.red : PAL.dark,
    );
  }
  add("metal", rod([GAUGE.pos[0], Y + rC(GAUGE.pos[0]) - 0.05, 0], [GAUGE.pos[0], GAUGE.pos[1] - 0.3, 0.02], 0.04, 8), PAL.steelDark);

  // --- CDP transmitter -------------------------------------------------------------------
  const [cx, cy, cz] = E.cdp_tx.pos;
  add("paint", box(0.26, 0.3, 0.22, [cx, cy, cz]), PAL.blue);
  add("paint", cylX(0.12, 0.12, cx - 0.16, cx + 0.16, cy + 0.25, cz, 14), PAL.white);
  add("metal", box(0.22, 0.1, 0.22, [cx, cy - 0.2, cz]), PAL.steelDark);
  add("metal", polyRod([[cx, cy - 0.25, cz], [cx, cy - 0.5, cz - 0.1], [cx + 0.05, Y + 0.75, 0.66]], 0.022), PAL.steel);
  add("metal", rod([cx - 0.08, cy - 0.25, cz], [cx - 0.08, Y + 0.68, 0.8], 0.03, 6), PAL.steelDark);

  // --- Combustor x -6..-4.4 --------------------------------------------------------------
  casing.add(cylX(1.0, 1.62, -6.15, -5.95, Y, 0, 32, true), CAS);
  casing.add(cylX(1.62, 1.62, -5.95, -4.6, Y, 0, 32, true), CAS);
  casing.add(cylX(1.62, 1.1, -4.6, -4.4, Y, 0, 32, true), CAS_WARM);
  for (const x of [-5.95, -4.6]) add("metal", torusX(1.63, 0.055, x, Y, 0, 36, 6), PAL.steelDark);
  add("metal", boxMM(-5.45, 0.4, -0.8, -4.95, Y - 1.58, 0.8), PAL.steelDark);
  rotor.add(cylX(0.72, 0.62, -6, -4.4, 0, 0, 20), PAL.steelDark);

  const NC = 10;
  const ringR = 1.12;
  for (let k = 0; k < NC; k++) {
    const phi = ((k + 0.5) / NC) * PI * 2;
    const parts = [
      new THREE.CylinderGeometry(0.17, 0.2, 1.2, 14, 1, false),
      new THREE.SphereGeometry(0.2, 12, 6, 0, PI * 2, 0, PI / 2),
    ];
    parts[1].translate(0, -0.6, 0);
    parts[1].rotateX(PI); // dome toward the head (-Y before orienting)
    parts[1].translate(0, -1.2, 0);
    for (const g of parts) {
      g.rotateZ(-PI / 2); // axis +Y → +X (head toward -X)
      g.rotateZ(-0.22); // downstream end tilts toward the axis
      g.translate(-5.25, ringR, 0);
      g.rotateX(phi);
      g.translate(0, Y, 0);
      cans.push(g);
    }
  }
  // Fuel manifold + pigtails.
  const mx = -5.75;
  add("paint", torusX(1.45, 0.05, mx, Y, 0, 40, 6), PAL.fuel);
  for (let k = 0; k < NC; k++) {
    const phi = ((k + 0.5) / NC) * PI * 2;
    const c = Math.cos(phi);
    const s = Math.sin(phi);
    add("paint", rod([mx, Y + c * 1.45, s * 1.45], [-5.82, Y + c * 1.28, s * 1.28], 0.025, 5), PAL.fuel);
  }
  add("paint", rod([-5.2, Y, -1.4], [mx, Y, -1.45], 0.09, 8), PAL.fuel);
  add("paint", sphere(0.1, [-5.2, Y, -1.4], [1, 1, 1], 8), PAL.fuel);

  // --- Turbine x -4.4..-2 ----------------------------------------------------------------
  casing.add(cylX(1.1, 1.7, -4.4, -2.0, Y, 0, 32, true), CAS_WARM);
  for (const x of [-4.4, -3.2, -2.0]) add("metal", torusX(rT(x) + 0.01, 0.05, x, Y, 0, 36, 6), PAL.warmSteel);
  add("metal", boxMM(-2.75, 0.4, -0.9, -2.35, Y - rT(-2.55) + 0.08, 0.9), PAL.steelDark);
  rotor.add(cylX(0.62, 0.74, -4.4, -2.0, 0, 0, 24), "#a8977f");
  for (let i = 0; i < 4; i++) {
    const x = -4.1 + i * 0.58;
    const hub = 0.64 + i * 0.03;
    bladeRow(rotor, x, hub, rT(x) - 0.08, 26, 0.24, 0.5, PAL.warmSteel);
  }

  // --- Exhaust diffuser + round-to-rectangular transition into the HRSG -------------------
  const dif = cylX(1.7, 2.05, -2.0, -0.4, Y, 0, 32, true);
  add("metal", flipped(dif), PAL.steelDark);
  add("metal", dif, PAL.steel);
  for (const x of [-2.0, -1.2, -0.4]) add("metal", torusX(1.7 + ((x + 2) / 1.6) * 0.35 + 0.01, 0.05, x, Y, 0, 36, 6), PAL.steelDark);
  const tr = roundToRect(-0.4, 1.0, { cy: Y, cz: 0, r: 2.05 }, { cy: 3.0, cz: 0, hy: 2.45, hz: 2.35 }, 40, 8, 6);
  const [trIn, trOut] = twoSided(tr);
  add("metal", trIn, PAL.steelDark);
  add("metal", trOut, PAL.steel);
  add("metal", boxMM(-1.4, 0.15, -0.9, -1.0, Y - 1.85, 0.9), PAL.steelDark);
}

// =============================================================================================

function fuelSkid(add: Add) {
  const F = PAL.fuel;
  // Skid frame.
  add("metal", boxMM(-6.2, 0.12, -6.8, -3.8, 0.26, -5.2), PAL.steelDeep);
  for (const z of [-6.8, -5.2]) add("metal", boxMM(-6.25, 0.12, z - 0.06, -3.75, 0.3, z + 0.06), PAL.steelDark);
  for (const x of [-6.2, -5.0, -3.8]) add("metal", boxMM(x - 0.06, 0.12, -6.85, x + 0.06, 0.3, -5.15), PAL.steelDark);
  // Filter-separator vessel on saddles.
  const vz = -6.35;
  const vy = 0.95;
  add("paint", cylX(0.33, 0.33, -6.0, -4.9, vy, vz, 20), PAL.steelLight);
  add("paint", domeX(0.33, 0.22, -6.0, vy, vz, -1, 20), PAL.steelLight);
  add("paint", domeX(0.33, 0.22, -4.9, vy, vz, 1, 20), PAL.steelLight);
  for (const x of [-5.75, -5.15]) add("metal", boxMM(x - 0.07, 0.3, vz - 0.24, x + 0.07, vy - 0.22, vz + 0.24), PAL.steelDark);
  add("metal", cylY(0.07, 0.07, vy + 0.3, vy + 0.45, -5.45, vz, 10), PAL.steelDark);
  add("metal", cylY(0.11, 0.11, vy + 0.45, vy + 0.5, -5.45, vz, 12), PAL.steelDark);
  // Inlet from below grade → vessel.
  add("paint", cylY(0.075, 0.075, 0.12, vy, -3.95, vz, 10), F);
  add("paint", sphere(0.08, [-3.95, vy, vz], [1, 1, 1], 8), F);
  add("paint", cylX(0.075, 0.075, -4.7, -3.95, vy, vz, 10), F);
  // Vessel outlet → meter run → riser to the combustor fuel line.
  const mz = -5.6;
  add("paint", cylX(0.075, 0.075, -6.32, -6.15, vy, vz, 10), F);
  add("paint", sphere(0.08, [-6.32, vy, vz], [1, 1, 1], 8), F);
  add("paint", cylZ(0.075, 0.075, vz, mz, -6.32, vy, 10), F);
  add("paint", sphere(0.08, [-6.32, vy, mz], [1, 1, 1], 8), F);
  add("paint", cylX(0.075, 0.075, -6.32, -5.0, vy, mz, 10), F);
  add("paint", sphere(0.08, [-5.0, vy, mz], [1, 1, 1], 8), F);
  add("paint", cylY(0.075, 0.075, vy, 1.2, -5.0, mz, 10), F);
  add("paint", sphere(0.08, [-5.0, 1.2, mz], [1, 1, 1], 8), F);
  add("paint", cylZ(0.075, 0.075, mz, -5.2, -5.0, 1.2, 10), F);
  for (const x of [-6.05, -5.25]) add("metal", torusX(0.11, 0.03, x, vy, mz, 14, 5), PAL.steelDark);
  // Meter body + transmitter head.
  add("paint", box(0.32, 0.26, 0.26, [-5.65, vy, mz]), PAL.blue);
  add("paint", cylY(0.08, 0.08, vy + 0.13, vy + 0.3, -5.65, mz, 12), PAL.white);
  // Valves with yellow handwheels.
  const valve = (p: Vec3, stemUp: boolean) => {
    add("metal", sphere(0.11, p, [1.2, 1, 1], 10), PAL.steelDark);
    if (stemUp) {
      add("metal", cylY(0.02, 0.02, p[1], p[1] + 0.3, p[0], p[2], 6), PAL.steelDark);
      add("paint", torusY(0.12, 0.018, p[0], p[1] + 0.3, p[2], 18, 5), PAL.yellow);
      add("paint", box(0.24, 0.02, 0.02, [p[0], p[1] + 0.3, p[2]]), PAL.yellow);
      add("paint", box(0.02, 0.02, 0.24, [p[0], p[1] + 0.3, p[2]]), PAL.yellow);
    } else {
      add("metal", cylX(0.02, 0.02, p[0], p[0] + 0.28, p[1], p[2], 6), PAL.steelDark);
      add("paint", torusX(0.12, 0.018, p[0] + 0.28, p[1], p[2], 18, 5), PAL.yellow);
    }
  };
  valve([-6.0, vy, mz], true);
  valve([-5.3, vy, mz], true);
  valve([-3.95, 0.55, vz], false);
  // Local panel.
  add("paint", boxMM(-4.6, 0.3, -5.48, -4.05, 1.15, -5.26), PAL.steelLight);
  add("paint", boxMM(-4.52, 0.8, -5.26, -4.13, 1.05, -5.25), PAL.glass);
  // Fuel line support between skid and GT.
  add("metal", boxMM(-5.06, 0.0, -3.46, -4.94, 1.12, -3.34), PAL.steelDark);
  add("metal", boxMM(-5.25, 1.08, -3.46, -4.75, 1.12, -3.34), PAL.steelDark);
}

// =============================================================================================

function hrsg(add: Add) {
  const { pos, size } = E.hrsg;
  const x0 = pos[0] - size[0] / 2; // 1
  const x1 = pos[0] + size[0] / 2; // 8
  const y0 = pos[1] - size[1] / 2; // 0.5
  const y1 = pos[1] + size[1] / 2; // 8.5
  const z1 = size[2] / 2; // 2.5
  const t = 0.06;
  const P = PAL.steelLight;

  // Casing (the +Z face is cut away to show the tube banks).
  add("metal", boxMM(x0, y0, -z1, x1, y1, -z1 + t), P); // back
  add("metal", boxMM(x0, 5.45, -z1, x0 + t, y1, z1), P); // inlet end (above the transition)
  for (const s of [-1, 1]) add("metal", boxMM(x0, y0, s > 0 ? 2.35 : -z1, x0 + t, 5.45, s > 0 ? z1 : -2.35), P);
  add("metal", boxMM(x1 - t, y0, -z1, x1, y1, z1), P); // outlet end
  add("metal", boxMM(x0 - 0.05, y1 - 0.06, -z1 - 0.05, x1 + 0.05, y1 + 0.06, z1 + 0.05), PAL.steel); // roof
  add("metal", boxMM(x0, y0, -z1, x1, y0 + 0.08, z1), PAL.steelDark); // floor
  // Darker inner liner.
  add("metal", boxMM(x0 + t, y0 + 0.08, -z1 + t, x1 - t, y1 - 0.06, -z1 + t + 0.01), PAL.steelDeep);
  add("metal", boxMM(x1 - t - 0.01, y0 + 0.08, -z1 + t, x1 - t, y1 - 0.06, z1), PAL.steelDeep);
  add("metal", boxMM(x0 + t, 5.45, -z1 + t, x0 + t + 0.01, y1 - 0.06, z1), PAL.steelDeep);
  // Cut-away frame on +Z: corner columns, top fascia, bottom skirt, and a "cut" edge.
  add("metal", boxMM(x0, y0, z1 - 0.1, x0 + 0.35, y1, z1), P);
  add("metal", boxMM(x1 - 0.35, y0, z1 - 0.1, x1, y1, z1), P);
  add("metal", boxMM(x0, y1 - 0.45, z1 - 0.1, x1, y1, z1), P);
  add("metal", boxMM(x0, y0, z1 - 0.1, x1, y0 + 0.5, z1), P);
  add("paint", boxMM(x0 + 0.35, y0 + 0.5, z1 - 0.02, x0 + 0.42, y1 - 0.45, z1 + 0.005), PAL.yellow);
  add("paint", boxMM(x1 - 0.42, y0 + 0.5, z1 - 0.02, x1 - 0.35, y1 - 0.45, z1 + 0.005), PAL.yellow);

  // Stiffener ribs + buckstays.
  for (let x = x0 + 0.35; x < x1 - 0.1; x += 0.7) {
    add("metal", box(0.1, y1 - y0, 0.14, [x, (y0 + y1) / 2, -z1 - 0.07]), PAL.steel);
    add("metal", box(0.1, 0.45, 0.14, [x, y1 - 0.225, z1 + 0.07]), PAL.steel);
  }
  for (let z = -z1 + 0.4; z < z1; z += 0.7) add("metal", box(0.14, y1 - y0, 0.1, [x1 + 0.07, (y0 + y1) / 2, z]), PAL.steel);
  for (const yy of [2.5, 4.5, 6.5]) {
    add("metal", box(x1 - x0 + 0.1, 0.18, 0.12, [(x0 + x1) / 2, yy, -z1 - 0.18]), PAL.steelDark);
    add("metal", box(0.12, 0.18, 2 * z1 + 0.1, [x1 + 0.18, yy, 0]), PAL.steelDark);
  }
  // Supports to the pad.
  for (const x of [x0 + 0.3, (x0 + x1) / 2, x1 - 0.3])
    for (const z of [-z1 + 0.3, 0, z1 - 0.3]) add("metal", boxMM(x - 0.18, 0.15, z - 0.18, x + 0.18, y0, z + 0.18), PAL.steelDeep);

  // Tube banks: superheater, evaporator, economiser (rows of vertical tubes + headers).
  const banks: { xs: number[]; color: string }[] = [
    { xs: [2.0, 2.3, 2.6], color: PAL.tubeSH },
    { xs: [3.5, 3.8, 4.1, 4.4, 4.7, 5.0], color: PAL.tubeEV },
    { xs: [6.1, 6.4, 6.7, 7.0], color: PAL.tubeECO },
  ];
  for (const b of banks) {
    b.xs.forEach((x, i) => {
      for (let z = -2.2 + (i % 2) * 0.11; z <= 2.25; z += 0.22) add("metal", cylY(0.045, 0.045, 1.0, 7.9, x, z, 6, true), b.color);
      add("metal", cylZ(0.09, 0.09, -2.35, 2.3, x, 7.95, 10), PAL.steelDark);
      add("metal", cylZ(0.09, 0.09, -2.35, 2.3, x, 0.95, 10), PAL.steelDark);
    });
    // Bank label strip on the floor (subtle colour cue).
    add("paint", boxMM(b.xs[0] - 0.15, y0 + 0.08, -2.3, b.xs[b.xs.length - 1] + 0.15, y0 + 0.1, 2.3), b.color);
  }

  // Platforms, stairs and yellow handrails on the -Z side.
  const H = PAL.yellow;
  const zo = -z1 - 1.1; // outer edge of the walkway
  const plat = (yy: number, xa: number, xb: number, za: number, zb: number) =>
    add("metal", boxMM(xa, yy - 0.08, za, xb, yy, zb), PAL.steelDark);
  const rail = (a: Vec3, b: Vec3) => {
    add("paint", rod([a[0], a[1] + 0.55, a[2]], [b[0], b[1] + 0.55, b[2]], 0.025, 6), H);
    add("paint", rod([a[0], a[1] + 0.28, a[2]], [b[0], b[1] + 0.28, b[2]], 0.018, 6), H);
    const n = Math.max(1, Math.round(v3(a).distanceTo(v3(b)) / 1.0));
    for (let i = 0; i <= n; i++) {
      const k = i / n;
      const p: Vec3 = [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];
      add("paint", rod(p, [p[0], p[1] + 0.55, p[2]], 0.02, 5), H);
    }
  };
  const yL = 4.4;
  plat(yL, x0 + 0.3, x1 - 0.3, zo, -z1 - 0.25);
  rail([x0 + 1.6, yL, zo], [x1 - 0.3, yL, zo]);
  rail([x1 - 0.3, yL, zo], [x1 - 0.3, yL, -z1 - 0.25]);
  for (const x of [x0 + 0.4, (x0 + x1) / 2, x1 - 0.4]) add("metal", boxMM(x - 0.07, 0.0, zo + 0.05, x + 0.07, yL - 0.08, zo + 0.19), PAL.steelDark);
  // Two stair flights (zig-zag) outboard of the walkway.
  const sz0 = zo - 0.75;
  const sz1 = zo - 0.05;
  const flight = (xa: number, ya: number, xb: number, yb: number) => {
    for (const z of [sz0, sz1]) add("metal", beam([xa, ya, z], [xb, yb, z], 0.06, 0.22), PAL.steelDark);
    const n = Math.round((yb - ya) / 0.25);
    for (let i = 1; i < n; i++) {
      const k = i / n;
      add("metal", box(0.24, 0.04, sz1 - sz0, [xa + (xb - xa) * k, ya + (yb - ya) * k, (sz0 + sz1) / 2]), PAL.steelDark);
    }
    rail([xa, ya, sz0], [xb, yb, sz0]);
  };
  flight(x1 - 0.4, 0.15, x0 + 1.6, yL);
  plat(yL, x0 + 0.3, x0 + 1.6, sz0, zo);
  flight(x0 + 1.6, yL, x1 - 0.9, y1 + 0.06);
  plat(y1 + 0.06, x1 - 0.9, x1 + 0.05, sz0, -z1);
  rail([x1 + 0.05, y1 + 0.06, sz0], [x1 + 0.05, y1 + 0.06, -z1]);
  for (const [x, z] of [
    [x0 + 0.35, sz0 - 0.1],
    [x1 - 0.85, sz0 - 0.1],
    [x1, sz0 - 0.1],
  ] as [number, number][]) {
    const top = x < x0 + 1 ? yL - 0.08 : y1 - 0.02;
    add("metal", boxMM(x - 0.06, 0, z - 0.06, x + 0.06, top, z + 0.06), PAL.steelDark);
  }
  // Roof handrail around the perimeter.
  const ry = y1 + 0.06;
  rail([x0 + 0.05, ry, -z1 + 0.05], [x1 - 0.05, ry, -z1 + 0.05]);
  rail([x0 + 0.05, ry, z1 - 0.05], [x1 - 0.05, ry, z1 - 0.05]);
  rail([x0 + 0.05, ry, -z1 + 0.05], [x0 + 0.05, ry, z1 - 0.05]);

  // --- Steam drum on saddles atop the HRSG -------------------------------------------------
  const [dx, dy, dz] = E.steam_drum.pos;
  const dr = 0.6;
  const half = E.steam_drum.size[0] / 2 - dr; // cylinder half-length
  add("clad", cylX(dr, dr, dx - half, dx + half, dy, dz, 28), PAL.cladding);
  add("clad", domeX(dr, dr * 0.85, dx - half, dy, dz, -1, 24), PAL.cladding);
  add("clad", domeX(dr, dr * 0.85, dx + half, dy, dz, 1, 24), PAL.cladding);
  for (let x = dx - half + 0.4; x < dx + half; x += 0.8) add("metal", torusX(dr + 0.005, 0.018, x, dy, dz, 28, 4), PAL.steelDark);
  for (const x of [dx - 1.1, dx + 1.1]) {
    add("metal", boxMM(x - 0.18, y1 + 0.06, dz - 0.5, x + 0.18, dy - 0.35, dz + 0.5), PAL.steelDark);
    add("metal", box(0.42, 0.08, 1.1, [x, y1 + 0.1, dz]), PAL.steelDeep);
  }
  for (const x of [dx - 1.6, dx - 0.6, dx + 0.6, dx + 1.6])
    for (const s of [-1, 1]) add("metal", cylY(0.055, 0.055, y1, dy - 0.4, x, dz + s * 0.36, 8), PAL.steel);
  for (const x of [dx - half + 0.1, dx + half - 0.1]) add("clad", cylY(0.11, 0.11, y1, dy - 0.45, x, dz - 0.3, 10), PAL.cladding);
  add("clad", cylY(0.17, 0.17, dy + 0.3, dy + 0.75, dx, 0.4, 14), PAL.cladding);
  add("metal", torusY(0.18, 0.03, dx, dy + 0.72, 0.4, 16, 5), PAL.steelDark);
  for (const x of [dx - 1.2, dx + 1.2]) {
    add("metal", cylY(0.07, 0.07, dy + 0.5, dy + 0.85, x, dz, 10), PAL.steelDark);
    add("paint", cylY(0.09, 0.05, dy + 0.85, dy + 1.0, x, dz, 10), PAL.red);
  }
}

// =============================================================================================

function stack(add: Add) {
  const [sx, , sz] = E.stack.pos;
  const H = E.stack.size[1];
  const r = (y: number) => 1.05 - ((y - 0.15) / (H - 0.15)) * 0.1;
  add("matte", cylY(1.45, 1.45, 0, 0.32, sx, sz, 28), PAL.concreteDark);
  add("metal", cylY(1.05, r(H - 0.6), 0.15, H - 0.6, sx, sz, 28, true), PAL.steelLight);
  add("metal", cylY(r(H - 0.6), r(H), H - 0.6, H, sx, sz, 28, true), PAL.steelDeep);
  add("metal", flipped(cylY(r(H - 0.6) - 0.03, r(H) - 0.03, H - 0.6, H, sx, sz, 28, true)), "#5b6573");
  add("metal", torusY(r(H) - 0.01, 0.05, sx, H, sz, 32, 6), PAL.steelDeep);
  for (const yy of [3, 6, 9, 12]) add("metal", torusY(r(yy) + 0.01, 0.04, sx, yy, sz, 32, 5), PAL.steelDark);

  // CEMS platform with handrail at y ≈ 10.
  const py = 10;
  add("metal", cylY(1.75, 1.75, py - 0.08, py, sx, sz, 32), PAL.steelDark);
  for (let k = 0; k < 8; k++) {
    const a = (k / 8) * PI * 2;
    add("metal", beam([sx + Math.cos(a) * 1.0, py - 0.9, sz + Math.sin(a) * 1.0], [sx + Math.cos(a) * 1.6, py - 0.08, sz + Math.sin(a) * 1.6], 0.07), PAL.steelDark);
  }
  add("paint", torusY(1.7, 0.028, sx, py + 0.55, sz, 40, 5), PAL.yellow);
  add("paint", torusY(1.7, 0.02, sx, py + 0.28, sz, 40, 5), PAL.yellow);
  add("paint", cylY(1.72, 1.72, py, py + 0.1, sx, sz, 40, true), PAL.yellow);
  for (let k = 0; k < 14; k++) {
    const a = (k / 14) * PI * 2;
    const p: Vec3 = [sx + Math.cos(a) * 1.7, py, sz + Math.sin(a) * 1.7];
    add("paint", rod(p, [p[0], py + 0.55, p[2]], 0.022, 5), PAL.yellow);
  }
  // Sample probes.
  for (const a of [0.3, -0.5]) {
    const c = Math.cos(a);
    const s = Math.sin(a);
    add("metal", rod([sx + c * 0.95, py + 0.3, sz + s * 0.95], [sx + c * 1.35, py + 0.3, sz + s * 1.35], 0.045, 8), PAL.steelDark);
    add("paint", box(0.18, 0.18, 0.18, [sx + c * 1.4, py + 0.3, sz + s * 1.4]), PAL.white);
  }
  // Ladder on the +Z side.
  const lz = sz + 1.3;
  for (const dx of [-0.2, 0.2]) add("metal", boxMM(sx + dx - 0.025, 0.32, lz - 0.025, sx + dx + 0.025, py + 0.6, lz + 0.025), PAL.steelDark);
  for (let y = 0.6; y < py; y += 0.32) add("metal", box(0.4, 0.025, 0.025, [sx, y, lz]), PAL.steelDark);
  for (let y = 1.5; y < py; y += 2.2) {
    for (const dx of [-0.2, 0.2]) add("metal", boxMM(sx + dx - 0.02, y - 0.02, sz + r(y) - 0.05, sx + dx + 0.02, y + 0.02, lz), PAL.steelDark);
  }
  // Analyser shelter at the base + sample line up to the platform.
  add("paint", boxMM(10.65, 0.15, 0.25, 11.75, 1.3, 1.5), PAL.white);
  add("metal", boxMM(10.55, 1.3, 0.15, 11.85, 1.38, 1.6), PAL.steel);
  add("paint", boxMM(11.0, 0.18, 1.5, 11.45, 1.15, 1.52), PAL.blue);
  add("metal", boxMM(11.75, 0.5, 0.45, 11.95, 0.95, 0.95), PAL.steelDark);
  add("matte", polyRod([[10.7, 1.1, 0.5], [10.5, 1.1, 0.5], [10.5, py - 0.08, 0.5]], 0.035, 6), PAL.tray);

  // Outlet duct HRSG → stack.
  const hx1 = E.hrsg.pos[0] + E.hrsg.size[0] / 2;
  add("metal", boxMM(hx1, 6.6, -0.9, sx - 0.3, 8.2, 0.9), PAL.steel);
  add("metal", boxMM(hx1 + 0.12, 6.5, -1.0, hx1 + 0.22, 8.3, 1.0), PAL.steelDark);
  add("metal", boxMM(sx - 0.75, 6.5, -1.0, sx - 0.65, 8.3, 1.0), PAL.steelDark);
}

// =============================================================================================

function steamBlock(add: Add) {
  const [sx, , sz] = E.steam_turbine.pos;
  const xa = sx - E.steam_turbine.size[0] / 2 + 0.2; // 1.0
  const xb = sx + E.steam_turbine.size[0] / 2 - 0.2; // 5.0
  const rS = (x: number) => 1.0 + ((x - xa) / (xb - xa)) * 0.4;
  const C = PAL.concrete;

  // Table-top pedestal: four columns + deck beams.
  const px = [xa - 0.25, xb + 0.25];
  const pz = [sz - 1.6, sz + 1.6];
  for (const x of px) for (const z of pz) add("matte", boxMM(x - 0.3, 0.15, z - 0.3, x + 0.3, 1.75, z + 0.3), C);
  for (const x of px) add("matte", boxMM(x - 0.35, 1.75, pz[0] - 0.3, x + 0.35, 2.05, pz[1] + 0.3), C);
  for (const z of pz) add("matte", boxMM(px[0] - 0.35, 1.75, z - 0.3, px[1] + 0.35, 2.05, z + 0.3), C);

  // Casing: lagged HP section (cladding) + bare LP section, split flanges, rings.
  const xm = 2.6;
  add("clad", cylX(rS(xa), rS(xm), xa, xm, SY, sz, 28), PAL.cladding);
  add("metal", cylX(rS(xm), rS(xb), xm, xb, SY, sz, 28), PAL.steelLight);
  add("metal", domeX(rS(xa), 0.25, xa, SY, sz, -1, 24), PAL.steel);
  add("metal", domeX(rS(xb), 0.3, xb, SY, sz, 1, 24), PAL.steel);
  for (const x of [xa, xm, 3.8, xb]) add("metal", torusX(rS(x) + 0.01, 0.045, x, SY, sz, 36, 6), PAL.steelDark);
  for (const s of [-1, 1]) add("metal", beam([xa, SY, sz + s * (rS(xa) + 0.03)], [xb, SY, sz + s * (rS(xb) + 0.03)], 0.07, 0.1), PAL.steelDark);
  // Bearing housings on the deck.
  for (const x of px) {
    add("metal", boxMM(x - 0.28, 2.05, sz - 0.45, x + 0.28, 2.85, sz + 0.45), PAL.steelDark);
    add("metal", cylX(0.42, 0.42, x - 0.28, x + 0.28, 2.85, sz, 16), PAL.steelDark);
  }
  // Exhaust neck into the condenser.
  add("metal", boxMM(2.3, 1.85, sz - 1.05, 4.8, 2.6, sz + 1.05), PAL.steel);
  // Main steam valve chest at the HP inlet.
  add("clad", cylY(0.27, 0.27, SY + 0.75, SY + 1.45, 1.3, sz, 16), PAL.cladding);
  add("clad", sphere(0.27, [1.3, SY + 1.45, sz], [1, 0.5, 1], 16), PAL.cladding);
  add("paint", box(0.22, 0.3, 0.22, [1.3, SY + 1.75, sz - 0.05]), PAL.blue);
  // Coupling to the ST generator.
  add("metal", cylX(0.16, 0.16, 0.2, xa, SY, sz, 12), PAL.steel);
  add("metal", cylX(0.32, 0.32, 0.45, 0.6, SY, sz, 16), PAL.steelDark);

  // --- Condenser + water boxes ------------------------------------------------------------
  const { pos: cp, size: cs } = E.condenser;
  const cx0 = cp[0] - cs[0] / 2 + 0.2; // 1.1
  const cx1 = cp[0] + cs[0] / 2 - 0.2; // 4.9
  const cz0 = cp[2] - cs[2] / 2 + 0.2; // 8.8
  const cz1 = cp[2] + cs[2] / 2 - 0.2; // 11.2
  add("metal", boxMM(cx0, 0.15, cz0, cx1, 1.9, cz1), PAL.steel);
  for (let x = cx0 + 0.45; x < cx1; x += 0.6)
    for (const z of [cz0 - 0.04, cz1 + 0.04]) add("metal", box(0.08, 1.75, 0.08, [x, 1.02, z]), PAL.steelDark);
  add("metal", box(cx1 - cx0 + 0.1, 0.1, cz1 - cz0 + 0.1, [cp[0], 1.9, cp[2]]), PAL.steelDark);
  add("metal", boxMM(2.2, 0.15, cz0 - 0.35, 3.8, 0.75, cz0), PAL.steelDark); // hotwell
  for (const [xw, sgn] of [
    [cx0, -1],
    [cx1, 1],
  ] as [number, 1 | -1][]) {
    const xo = xw + sgn * 0.35;
    add("paint", boxMM(Math.min(xw, xo), 0.22, cp[2] - 0.9, Math.max(xw, xo), 1.7, cp[2] + 0.9), PAL.water);
    add("paint", domeX(0.72, 0.22, xo, 0.97, cp[2], sgn, 20), PAL.water);
    add("metal", torusX(0.74, 0.04, xo, 0.97, cp[2], 28, 5), PAL.steelDark);
  }
  // Cooling-water nozzles at the +X water box.
  add("metal", torusX(0.23, 0.04, cx1 + 0.38, 0.6, 10.8, 16, 5), PAL.steelDark);
  add("metal", torusX(0.23, 0.04, cx1 + 0.38, 0.35, 9.2, 16, 5), PAL.steelDark);

  // --- ST generator on its own concrete block ----------------------------------------------
  const { pos: gp } = E.st_generator;
  const g0 = -2.5;
  const g1 = -0.1;
  add("matte", boxMM(-3.4, 0.15, sz - 1.2, 0.2, 1.95, sz + 1.2), C);
  add("metal", boxMM(-2.7, 1.95, sz - 0.95, 0.1, 2.2, sz + 0.95), PAL.steelDeep);
  add("metal", cylX(1.1, 1.1, g0, g1, gp[1], gp[2], 28), PAL.steelLight);
  add("metal", domeX(1.0, 0.3, g0, gp[1], gp[2], -1, 24), PAL.steel);
  add("metal", domeX(1.0, 0.3, g1, gp[1], gp[2], 1, 24), PAL.steel);
  for (const x of [g0 + 0.15, g1 - 0.15]) add("metal", torusX(1.11, 0.04, x, gp[1], gp[2], 32, 5), PAL.steelDark);
  add("paint", cylX(1.115, 1.115, -1.45, -1.15, gp[1], gp[2], 28, true), PAL.blue);
  add("metal", cylX(0.45, 0.45, -3.15, -2.8, gp[1], gp[2], 18), PAL.steel);
  add("metal", domeX(0.45, 0.12, -3.15, gp[1], gp[2], -1, 16), PAL.steel);
  add("metal", cylX(0.12, 0.12, -2.8, -2.6, gp[1], gp[2], 10), PAL.steelDark);
  add("metal", boxMM(-3.3, 1.95, sz - 0.4, -2.65, 2.75, sz + 0.4), PAL.steelDark);
  add("metal", boxMM(-1.6, 3.6, sz + 0.3, -0.8, 4.65, sz + 1.0), PAL.steelDark); // terminal box
  add("metal", boxMM(-2.3, 4.1, sz - 0.7, -1.75, 4.5, sz + 0.3), PAL.steel); // cooler
}

// =============================================================================================

function coolingTower(add: Add) {
  const [cx, , cz] = E.cooling_tower.pos;
  const Ht = E.cooling_tower.size[1]; // 10
  const yb = 0.9; // shell starts above the leg ring
  const a = 2.2; // waist radius
  const yw = 0.7 * Ht; // waist height
  const b = 4.8;
  const r = (y: number) => a * Math.sqrt(1 + ((y - yw) / b) ** 2);
  const prof: [number, number][] = [];
  const N = 22;
  for (let i = 0; i <= N; i++) {
    const y = yb + ((Ht - yb) * i) / N;
    prof.push([r(y), y]);
  }
  add("matte", lathe(prof, cx, cz, 40), PAL.concrete);
  add("matte", flipped(lathe(prof.map(([rr, y]) => [rr - 0.1, y]), cx, cz, 40)), PAL.concreteDark);
  const rt = r(Ht);
  add("matte", twoSided(lathe([[rt - 0.12, Ht], [rt + 0.02, Ht]], cx, cz, 40)), PAL.concreteDark);
  add("matte", lathe([[r(yb) + 0.06, yb - 0.12], [r(yb) + 0.06, yb + 0.12]], cx, cz, 40), PAL.concreteDark);
  // Diagonal leg pairs.
  const NL = 20;
  for (let k = 0; k < NL; k++) {
    const ang = (k / NL) * PI * 2;
    for (const s of [-1, 1]) {
      const a0 = ang - s * 0.07;
      const a1 = ang + s * 0.07;
      add(
        "matte",
        beam([cx + Math.cos(a0) * 3.62, 0.32, cz + Math.sin(a0) * 3.62], [cx + Math.cos(a1) * r(yb), yb - 0.05, cz + Math.sin(a1) * r(yb)], 0.1),
        PAL.concrete,
      );
    }
  }
  // Basin: low ring wall, water surface and fill.
  add("matte", cylY(4.05, 4.05, 0, 0.45, cx, cz, 48, true), PAL.concreteDark);
  add("matte", flipped(cylY(3.85, 3.85, 0, 0.45, cx, cz, 48, true)), PAL.concreteDark);
  add("matte", twoSided(lathe([[3.85, 0.45], [4.05, 0.45]], cx, cz, 48)), PAL.concreteDark);
  add("paint", place(new THREE.CircleGeometry(3.86, 48), [cx, 0.3, cz], [-PI / 2, 0, 0]), PAL.basinWater);
  add("matte", cylY(3.3, 3.3, 1.25, 1.45, cx, cz, 40), PAL.fill);
}

// =============================================================================================

function generator(add: Add, glow: THREE.BufferGeometry[]) {
  const [gx, , gz] = E.generator.pos;
  const s0 = gx - 1.3; // -16.3
  const s1 = gx + 1.4; // -13.6
  const R = 1.35;
  add("metal", boxMM(s0 - 0.4, 0.15, gz - 1.2, s1 + 0.4, Y - R + 0.05, gz + 1.2), PAL.steelDeep);
  add("metal", cylX(R, R, s0, s1, Y, gz, 32), PAL.steelLight);
  add("metal", domeX(R - 0.1, 0.35, s0, Y, gz, -1, 28), PAL.steel);
  add("metal", domeX(R - 0.1, 0.35, s1, Y, gz, 1, 28), PAL.steel);
  for (const x of [s0 + 0.08, s1 - 0.08]) add("metal", torusX(R + 0.01, 0.05, x, Y, gz, 36, 6), PAL.steelDark);
  // Glow bands (dynamic).
  for (const x of [s0 + 0.45, gx, s1 - 0.45]) glow.push(cylX(R + 0.02, R + 0.02, x - 0.1, x + 0.1, Y, gz, 32, true));
  glow.push(torusX(0.55, 0.05, s1 + 0.33, Y, gz, 24, 5));
  glow.push(torusX(0.55, 0.05, s0 - 0.33, Y, gz, 24, 5));
  // Exciter.
  add("metal", cylX(0.55, 0.55, gx - 2.3, s0 - 0.35, Y, gz, 20), PAL.steel);
  add("metal", domeX(0.55, 0.14, gx - 2.3, Y, gz, -1, 18), PAL.steel);
  add("metal", boxMM(gx - 2.3, 0.15, gz - 0.5, s0 - 0.35, Y - 0.5, gz + 0.5), PAL.steelDeep);
  // Air/water cooler on top + terminal box on +Z.
  add("metal", boxMM(gx - 0.9, Y + 0.95, gz - 0.9, gx + 0.9, Y + R + 0.3, gz + 0.9), PAL.steel);
  for (const z of [-0.97, 0.97]) add("paint", cylX(0.06, 0.06, gx - 1.2, gx + 1.2, Y + 1.4, gz + z, 8), PAL.water);
  add("metal", boxMM(gx - 0.6, 0.95, gz + 1.15, gx + 0.6, 1.75, gz + 1.7), PAL.steelDark);
  add("paint", boxMM(gx - 0.45, 1.5, gz + 1.7, gx + 0.45, 1.6, gz + 1.71), PAL.yellow);
  // Bearing pedestal for the coupling shaft.
  add("metal", boxMM(-12.95, 0.15, -0.5, -12.6, Y - 0.3, 0.5), PAL.steelDeep);
  add("metal", cylX(0.33, 0.33, -12.95, -12.6, Y - 0.05, 0, 16), PAL.steelDark);
  // Coupling guard (half shell, open toward +Z for visibility).
  add("metal", place(new THREE.CylinderGeometry(0.5, 0.5, 0.6, 16, 1, true, PI, PI), [-12.25 + 0.0, Y, 0], [0, 0, -PI / 2]), PAL.yellow);
}

// =============================================================================================

function electrical(
  add: Add,
  dyn: { lamp52g: THREE.BufferGeometry[]; lampHvsg: THREE.BufferGeometry[]; gsuTank: THREE.BufferGeometry[] },
) {
  // --- Generator breaker 52G cubicle --------------------------------------------------------
  {
    const [bx, , bz] = E.breaker_52g.pos;
    const x0 = bx - 0.6;
    const x1 = bx + 0.6;
    const z0 = bz - 0.5;
    const z1 = bz + 0.5;
    add("paint", boxMM(x0, 0.12, z0, x1, 1.95, z1), PAL.steelLight);
    add("metal", boxMM(x0 - 0.08, 1.95, z0 - 0.08, x1 + 0.08, 2.03, z1 + 0.08), PAL.steelDark);
    add("metal", boxMM(x0 - 0.02, 0.12, z0 - 0.02, x1 + 0.02, 0.22, z1 + 0.02), PAL.steelDeep);
    add("paint", boxMM(bx - 0.01, 0.25, z1, bx + 0.01, 1.85, z1 + 0.01), PAL.dark); // door seam
    add("paint", boxMM(x0 + 0.15, 1.15, z1, x0 + 0.5, 1.5, z1 + 0.015), PAL.glass); // window
    add("paint", boxMM(x0 + 0.13, 1.13, z1 - 0.005, x0 + 0.52, 1.52, z1 + 0.008), PAL.steelDark);
    add("paint", boxMM(bx + 0.1, 0.85, z1, bx + 0.14, 1.15, z1 + 0.04), PAL.dark); // handle
    for (let i = 0; i < 4; i++) add("paint", boxMM(x0 + 0.15, 0.35 + i * 0.07, z1, x0 + 0.5, 0.38 + i * 0.07, z1 + 0.015), PAL.steelDark);
    add("paint", boxMM(x1 - 0.42, 1.55, z1, x1 - 0.12, 1.65, z1 + 0.012), PAL.white); // name plate
    add("paint", cylZ(0.085, 0.085, z1, z1 + 0.02, x1 - 0.27, 1.8, 16), PAL.dark);
    dyn.lamp52g.push(sphere(0.07, [x1 - 0.27, 1.8, z1 + 0.025], [1, 1, 0.6], 14));
  }

  // --- GSU transformer in its bund ----------------------------------------------------------
  {
    const [tx, , tz] = E.gsu_transformer.pos;
    add("matte", boxMM(tx - 1.9, 0, tz - 1.7, tx + 1.9, 0.1, tz + 1.7), PAL.gravel);
    for (const s of [-1, 1]) {
      add("matte", boxMM(tx - 1.9, 0, tz + s * 1.7 - 0.08, tx + 1.9, 0.42, tz + s * 1.7 + 0.08), PAL.concrete);
      add("matte", boxMM(tx + s * 1.9 - 0.08, 0, tz - 1.7, tx + s * 1.9 + 0.08, 0.42, tz + 1.7), PAL.concrete);
    }
    add("matte", boxMM(tx - 1.0, 0.1, tz - 0.8, tx + 1.0, 0.35, tz + 0.8), PAL.concreteDark);
    // Tank (dynamic tint) with stiffeners and lid.
    const T = dyn.gsuTank;
    T.push(boxMM(tx - 0.9, 0.35, tz - 0.65, tx + 0.9, 2.25, tz + 0.65));
    T.push(boxMM(tx - 0.95, 2.25, tz - 0.7, tx + 0.95, 2.33, tz + 0.7));
    T.push(boxMM(tx - 0.95, 0.35, tz - 0.7, tx + 0.95, 0.45, tz + 0.7));
    for (const x of [-0.55, 0, 0.55]) for (const s of [-1, 1]) T.push(box(0.08, 1.8, 0.06, [tx + x, 1.3, tz + s * 0.68]));
    // Radiator banks (grey-green) on both ±X sides.
    for (const s of [-1, 1]) {
      const xc = tx + s * 1.25;
      for (let i = 0; i < 9; i++) add("paint", box(0.6, 1.5, 0.035, [xc, 1.3, tz - 0.54 + i * 0.135]), PAL.radiator);
      for (const yy of [0.55, 2.05]) {
        add("paint", cylZ(0.06, 0.06, tz - 0.6, tz + 0.6, tx + s * 1.0, yy, 10), PAL.radiator);
        add("paint", cylX(0.06, 0.06, Math.min(tx + s * 0.9, tx + s * 1.0), Math.max(tx + s * 0.9, tx + s * 1.0), yy, tz, 8), PAL.radiator);
      }
    }
    // Conservator along X on stands at the -Z edge.
    const cy = 3.05;
    const cz = tz - 0.55;
    add("metal", cylX(0.24, 0.24, tx - 0.7, tx + 0.7, cy, cz, 18), "#9aa6b4");
    add("metal", domeX(0.24, 0.1, tx - 0.7, cy, cz, -1, 14), "#9aa6b4");
    add("metal", domeX(0.24, 0.1, tx + 0.7, cy, cz, 1, 14), "#9aa6b4");
    for (const x of [-0.5, 0.5]) add("metal", rod([tx + x, 2.33, cz], [tx + x, cy - 0.2, cz], 0.04, 6), PAL.steelDark);
    add("metal", polyRod([[tx - 0.2, cy - 0.22, cz], [tx - 0.2, 2.6, cz + 0.2], [tx - 0.2, 2.33, cz + 0.2]], 0.03, 6), PAL.steelDark);
    // LV bushings (-Z side) and HV bushings (+Z side).
    for (const x of [-0.4, 0, 0.4]) {
      add("paint", cylY(0.07, 0.06, 2.33, 2.62, tx + x, tz - 0.3, 10), PAL.porcelain);
      add("metal", cylY(0.03, 0.03, 2.62, 2.72, tx + x, tz - 0.3, 6), PAL.steelDark);
    }
    for (const x of [-0.5, 0, 0.5]) {
      const bz = tz + 0.38;
      add("metal", cylY(0.14, 0.14, 2.33, 2.5, tx + x, bz, 12), PAL.steelDark);
      add("paint", cylY(0.075, 0.065, 2.5, 3.6, tx + x, bz, 10), PAL.porcelain);
      for (let y = 2.58; y < 3.55; y += 0.12) add("paint", cylY(0.15, 0.13, y, y + 0.04, tx + x, bz, 12), PAL.porcelain);
      add("metal", cylY(0.05, 0.05, 3.6, 3.78, tx + x, bz, 8), PAL.steel);
    }
    // Marshalling box.
    add("paint", boxMM(tx + 0.3, 0.6, tz + 0.65, tx + 0.8, 1.4, tz + 0.85), PAL.steelLight);
  }

  // --- HV GIS bay with breaker 52H ---------------------------------------------------------
  {
    const [hx, , hz] = E.hv_switchgear.pos;
    const G = PAL.steelLight;
    add("metal", boxMM(hx - 1.1, 0.06, hz - 0.65, hx + 1.1, 0.3, hz + 0.65), PAL.steelDeep);
    for (const z of [hz - 0.45, hz + 0.45]) {
      add("paint", cylX(0.18, 0.18, hx - 1.1, hx + 1.1, 0.62, z, 18), G);
      for (const x of [hx - 1.1, hx - 0.5, hx + 0.5, hx + 1.1]) add("metal", torusX(0.19, 0.03, x, 0.62, z, 18, 5), PAL.steelDark);
    }
    // Breaker 52H tank.
    add("paint", cylY(0.34, 0.34, 0.3, 2.1, hx, hz, 22), G);
    add("paint", sphere(0.34, [hx, 2.1, hz], [1, 0.45, 1], 20), G);
    for (const y of [0.9, 1.5]) add("metal", torusY(0.35, 0.03, hx, y, hz, 24, 5), PAL.steelDark);
    add("paint", boxMM(hx - 0.25, 0.9, hz + 0.34, hx + 0.25, 1.5, hz + 0.55), PAL.blue);
    // Disconnector housings + cross tube.
    for (const x of [hx - 0.7, hx + 0.7]) {
      add("paint", cylY(0.2, 0.2, 0.8, 1.65, x, hz, 16), G);
      add("paint", sphere(0.25, [x, 1.75, hz], [1, 1, 1], 16), G);
      add("metal", torusY(0.21, 0.03, x, 1.3, hz, 18, 5), PAL.steelDark);
    }
    add("paint", cylX(0.13, 0.13, hx - 0.7, hx + 0.7, 1.75, hz, 14), G);
    // Outgoing riser + composite bushing up to the busbar.
    const bx = hx + 0.7;
    add("paint", cylY(0.15, 0.15, 1.75, 2.6, bx, hz, 14), G);
    add("paint", cylY(0.1, 0.07, 2.6, 4.5, bx, hz, 10), PAL.porcelainGrey);
    for (let y = 2.7; y < 4.45; y += 0.13) add("paint", cylY(0.17, 0.15, y, y + 0.04, bx, hz, 12), PAL.porcelainGrey);
    add("metal", rod([bx, 4.5, hz], [hx + 0.9, 4.95, hz + 0.1], 0.04, 6), PAL.steel);
    // Local control cabinet with status lamp (dynamic) on top.
    add("paint", boxMM(hx - 1.45, 0.06, hz - 0.4, hx - 1.15, 1.45, hz + 0.4), G);
    add("paint", boxMM(hx - 1.46, 0.95, hz - 0.25, hx - 1.45, 1.3, hz + 0.25), PAL.glass);
    add("metal", cylY(0.07, 0.07, 1.45, 1.52, hx - 1.3, hz, 12), PAL.dark);
    dyn.lampHvsg.push(sphere(0.075, [hx - 1.3, 1.58, hz], [1, 0.9, 1], 14));
  }

  // --- Overhead cable supports along the generator → busbar power route --------------------
  for (const p of [
    [-15, 4.4, 8.6],
    [-12.5, 4.4, 11.8],
    [-1.2, 5, 12.4],
  ] as Vec3[]) {
    add("metal", boxMM(p[0] - 0.08, 0.0, p[2] + 0.25, p[0] + 0.08, p[1] - 0.25, p[2] + 0.41), PAL.steelDark);
    add("metal", boxMM(p[0] - 0.25, p[1] - 0.3, p[2] - 0.1, p[0] + 0.25, p[1] - 0.24, p[2] + 0.45), PAL.steelDark);
    add("paint", cylY(0.06, 0.05, p[1] - 0.24, p[1] - 0.06, p[0], p[2], 8), PAL.porcelain);
  }
}

// =============================================================================================

function latticeColumn(add: Add, x: number, z: number, y0: number, y1: number, hw: number, color: string) {
  const cs: [number, number][] = [
    [-hw, -hw],
    [hw, -hw],
    [hw, hw],
    [-hw, hw],
  ];
  for (const [dx, dz] of cs) add("metal", beam([x + dx, y0, z + dz], [x + dx, y1, z + dz], 0.05), color);
  const n = Math.max(2, Math.round((y1 - y0) / 0.6));
  for (let i = 0; i < n; i++) {
    const ya = y0 + ((y1 - y0) * i) / n;
    const yb = y0 + ((y1 - y0) * (i + 1)) / n;
    for (let f = 0; f < 4; f++) {
      const [ax, az] = cs[f];
      const [bx, bz] = cs[(f + 1) % 4];
      const flip = (i + f) % 2 === 0;
      add("metal", beam([x + (flip ? ax : bx), ya, z + (flip ? az : bz)], [x + (flip ? bx : ax), yb, z + (flip ? bz : az)], 0.025), color);
    }
  }
}

function tower(add: Add, cx: number, cz: number) {
  const C = PAL.steelDark;
  const lv = [0.1, 1.6, 3.0, 4.3, 5.5, 6.6, 7.6, 8.4, 9.6];
  const hwAt = (y: number) => (y <= 8.4 ? 1.0 + ((0.35 - 1.0) * (y - 0.1)) / 8.3 : 0.35 + ((0.3 - 0.35) * (y - 8.4)) / 1.2);
  const corners: [number, number][] = [
    [-1, -1],
    [1, -1],
    [1, 1],
    [-1, 1],
  ];
  const P = (sx: number, sz: number, y: number): Vec3 => [cx + sx * hwAt(y), y, cz + sz * hwAt(y)];
  for (const [sx, sz] of corners) {
    add("matte", boxMM(cx + sx * 1.0 - 0.25, 0, cz + sz * 1.0 - 0.25, cx + sx * 1.0 + 0.25, 0.2, cz + sz * 1.0 + 0.25), PAL.concreteDark);
    for (let i = 0; i < lv.length - 1; i++) add("metal", beam(P(sx, sz, lv[i]), P(sx, sz, lv[i + 1]), 0.09), C);
  }
  for (let i = 0; i < lv.length - 1; i++) {
    for (let f = 0; f < 4; f++) {
      const [ax, az] = corners[f];
      const [bx, bz] = corners[(f + 1) % 4];
      add("metal", beam(P(ax, az, lv[i + 1]), P(bx, bz, lv[i + 1]), 0.045), C);
      add("metal", beam(P(ax, az, lv[i]), P(bx, bz, lv[i + 1]), 0.035), C);
      add("metal", beam(P(bx, bz, lv[i]), P(ax, az, lv[i + 1]), 0.035), C);
    }
  }
  // Crossarm along Z at y ≈ 9.2, peak for the earth wire.
  const ya = 9.0;
  const span = 2.2;
  for (const sx of [-1, 1]) {
    add("metal", beam([cx + sx * 0.3, ya, cz - span], [cx + sx * 0.3, ya, cz + span], 0.07), C);
    for (const sz of [-1, 1]) add("metal", beam([cx + sx * 0.3, 9.6, cz + sz * 0.3], [cx + sx * 0.05, ya, cz + sz * span], 0.05), C);
    add("metal", beam(P(sx, -1, 9.6), [cx, 10.6, cz], 0.06), C);
    add("metal", beam(P(sx, 1, 9.6), [cx, 10.6, cz], 0.06), C);
  }
  for (let z = -span; z <= span + 0.01; z += 0.55) add("metal", beam([cx - 0.3, ya, cz + z], [cx + 0.3, ya, cz + z], 0.035), C);
  // Insulator strings at the arm tips.
  for (const sz of [-1, 1]) {
    const zt = cz + sz * 2.0;
    add("paint", cylY(0.025, 0.025, 8.3, ya, cx, zt, 6), PAL.porcelainGrey);
    for (let y = 8.4; y < ya - 0.05; y += 0.1) add("paint", cylY(0.09, 0.07, y, y + 0.03, cx, zt, 10), PAL.porcelainGrey);
  }
}

function busbarAndLine(add: Add) {
  const by = E.busbar.pos[1];
  const bz = E.busbar.pos[2];
  const bx0 = E.busbar.pos[0] - E.busbar.size[0] / 2; // -10
  const bx1 = E.busbar.pos[0] + E.busbar.size[0] / 2; // 4
  const phases = [bz - 0.5, bz, bz + 0.5];
  for (const z of phases) {
    add("clad", cylX(0.075, 0.075, bx0, bx1, by, z, 12), "#d5dbe2");
    add("clad", sphere(0.09, [bx0, by, z], [1, 1, 1], 10), "#d5dbe2");
  }
  for (const x of [-8.8, -5.6, -2.2, 1.2, 3.9]) {
    for (const z of [bz - 0.95, bz + 0.95]) {
      add("matte", boxMM(x - 0.3, 0, z - 0.3, x + 0.3, 0.25, z + 0.3), PAL.concreteDark);
      latticeColumn(add, x, z, 0.25, 5.7, 0.15, PAL.steelDark);
    }
    add("metal", boxMM(x - 0.12, 4.1, bz - 1.15, x + 0.12, 4.32, bz + 1.15), PAL.steelDark);
    add("metal", boxMM(x - 0.08, 5.62, bz - 1.15, x + 0.08, 5.74, bz + 1.15), PAL.steelDark);
    for (const z of phases) {
      add("paint", cylY(0.05, 0.05, 4.32, by - 0.06, x, z, 8), PAL.porcelain);
      for (let y = 4.4; y < by - 0.12; y += 0.1) add("paint", cylY(0.1, 0.09, y, y + 0.035, x, z, 10), PAL.porcelain);
      add("metal", box(0.14, 0.06, 0.18, [x, by - 0.07, z]), PAL.steel);
    }
  }

  // Transmission towers + conductors.
  const T1: Vec3 = [10, 0, 16];
  const T2: Vec3 = [21, 0, 16];
  tower(add, T1[0], T1[2]);
  tower(add, T2[0], T2[2]);
  const ca = "#7d8896";
  const att = (t: Vec3, s: number): Vec3 => [t[0], 8.3, t[2] + s * 2.0];
  for (const s of [-1, 1]) {
    add("metal", sagLine(att(T1, s), att(T2, s), 0.9, 0.035), ca);
    add("metal", sagLine(att(T2, s), [27, 7.4, T2[2] + s * 2.0], 0.3, 0.035), ca);
  }
  add("metal", sagLine([T1[0], 10.6, T1[2]], [T2[0], 10.6, T2[2]], 0.5, 0.02), ca);
  add("metal", sagLine([T2[0], 10.6, T2[2]], [27, 10.3, T2[2]], 0.15, 0.02), ca);
  add("metal", sagLine([bx1, by, phases[0]], att(T1, -1), 0.35, 0.035), ca);
  add("metal", sagLine([bx1, by, phases[2]], att(T1, 1), 0.35, 0.035), ca);
}

// =============================================================================================

function pipes(add: Add) {
  for (const fp of FLOW_PATHS) {
    if (!fp.pipe) continue;
    const st = PIPE_STYLE[fp.pipe.material];
    add(st.finish, tubeAlong(fp.points, fp.pipe.radius, 64, 8), st.color);
  }
  // Pipe supports: concrete sleepers under low runs, steel post under the steam line.
  for (const p of [
    [8, 0.6, 10.8],
    [11.5, 0.6, 8.6],
  ] as Vec3[])
    add("matte", boxMM(p[0] - 0.2, 0, p[2] - 0.35, p[0] + 0.2, p[1] - 0.2, p[2] + 0.35), PAL.concreteDark);
  add("matte", boxMM(1.2, 0, 4.65, 1.6, 0.38, 5.35), PAL.concreteDark);
  const sp: Vec3 = [3.2, 8.6, 6.8];
  add("metal", boxMM(sp[0] - 0.12, 0, sp[2] - 0.12, sp[0] + 0.12, sp[1] - 0.2, sp[2] + 0.12), PAL.steelDark);
  add("metal", boxMM(sp[0] - 0.3, sp[1] - 0.26, sp[2] - 0.2, sp[0] + 0.3, sp[1] - 0.16, sp[2] + 0.2), PAL.steelDark);
  add("matte", boxMM(sp[0] - 0.35, 0, sp[2] - 0.35, sp[0] + 0.35, 0.2, sp[2] + 0.35), PAL.concreteDark);
}
