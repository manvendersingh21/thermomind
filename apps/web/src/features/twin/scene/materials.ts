/**
 * Materials and palette for the procedural plant equipment.
 *
 * Static geometry is merged into a handful of "finish" buckets that carry per-vertex colours, so a
 * whole finish (all painted steel, all concrete, ...) costs one draw call. Dynamic parts get their
 * own materials whose colour / emissive is mutated in useFrame.
 *
 * There is no environment map in the scene, so metalness stays low (≤ 0.45) — high metalness
 * renders almost black without reflections.
 */
import * as THREE from "three";

/** Named colours (sRGB hex). */
export const PAL = {
  steelLight: "#c7ced8",
  steel: "#aab4c1",
  steelDark: "#8d99a8",
  steelDeep: "#6b7685",
  warmSteel: "#b9a58e",
  concrete: "#dde2e8",
  concreteDark: "#cbd2da",
  gravel: "#d3d0c8",
  road: "#cdd3da",
  roadLine: "#f8fafc",
  white: "#f4f6f8",
  cladding: "#dfe4ea",
  fuel: "#f59e0b",
  water: "#0e7490",
  basinWater: "#8db4bf",
  cable: "#3f4652",
  tray: "#4b5563",
  yellow: "#eab308",
  blue: "#2563eb",
  green: "#16a34a",
  radiator: "#8fa39a",
  porcelain: "#8a5a3c",
  porcelainGrey: "#9aa3ad",
  glass: "#475569",
  dark: "#334155",
  red: "#dc2626",
  tubeSH: "#a87d5f",
  tubeEV: "#8d99a8",
  tubeECO: "#7f9ca6",
  fill: "#5b6573",
} as const;

export type PaletteKey = keyof typeof PAL;

/** Static finish buckets (one merged mesh each). */
export type Finish = "metal" | "matte" | "paint" | "clad";

export const FINISHES: Finish[] = ["metal", "matte", "paint", "clad"];

export interface StaticMaterials {
  metal: THREE.MeshStandardMaterial;
  matte: THREE.MeshStandardMaterial;
  paint: THREE.MeshStandardMaterial;
  clad: THREE.MeshStandardMaterial;
}

export interface DynamicMaterials {
  filterFace: THREE.MeshStandardMaterial;
  cans: THREE.MeshStandardMaterial;
  genGlow: THREE.MeshStandardMaterial;
  needle: THREE.MeshStandardMaterial;
  rotor: THREE.MeshStandardMaterial;
  casing: THREE.MeshStandardMaterial;
  lamp52g: THREE.MeshStandardMaterial;
  lampHvsg: THREE.MeshStandardMaterial;
  gsuTank: THREE.MeshStandardMaterial;
}

/** Colours used by the dynamic parts (linear THREE.Color, created once). */
export const DYN = {
  filterClean: new THREE.Color("#e8edf3"),
  filterDirty: new THREE.Color("#8a6d46"),
  canLow: new THREE.Color("#c2410c"),
  canMid: new THREE.Color("#f59e0b"),
  canHigh: new THREE.Color("#fde68a"),
  canBodyLow: new THREE.Color("#5c3b2a"),
  canBodyHigh: new THREE.Color("#a08463"),
  genGlow: new THREE.Color("#facc15"),
  lampOk: new THREE.Color("#22c55e"),
  lampWarn: new THREE.Color("#f59e0b"),
  lampAlarm: new THREE.Color("#ef4444"),
  tankBase: new THREE.Color("#9aa6b4"),
  tankHot: new THREE.Color("#f97316"),
};

function std(params: THREE.MeshStandardMaterialParameters): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial(params);
}

export function createStaticMaterials(): StaticMaterials {
  return {
    metal: std({ color: "#ffffff", vertexColors: true, metalness: 0.35, roughness: 0.55 }),
    matte: std({ color: "#ffffff", vertexColors: true, metalness: 0.0, roughness: 0.9 }),
    paint: std({ color: "#ffffff", vertexColors: true, metalness: 0.15, roughness: 0.5 }),
    clad: std({ color: "#ffffff", vertexColors: true, metalness: 0.45, roughness: 0.38 }),
  };
}

export function createDynamicMaterials(): DynamicMaterials {
  return {
    filterFace: std({ color: DYN.filterClean.clone(), metalness: 0.05, roughness: 0.85 }),
    cans: std({
      color: DYN.canBodyLow.clone(),
      emissive: DYN.canLow.clone(),
      emissiveIntensity: 0.6,
      metalness: 0.3,
      roughness: 0.5,
    }),
    genGlow: std({
      color: "#e9d98a",
      emissive: DYN.genGlow.clone(),
      emissiveIntensity: 0.6,
      metalness: 0.2,
      roughness: 0.45,
    }),
    needle: std({ color: PAL.red, emissive: PAL.red, emissiveIntensity: 0.25, metalness: 0.1, roughness: 0.5 }),
    rotor: std({ color: "#ffffff", vertexColors: true, metalness: 0.4, roughness: 0.42 }),
    casing: std({
      color: "#ffffff",
      vertexColors: true,
      metalness: 0.2,
      roughness: 0.35,
      transparent: true,
      opacity: 0.28,
      depthWrite: false,
      side: THREE.DoubleSide,
    }),
    lamp52g: std({ color: DYN.lampOk.clone(), emissive: DYN.lampOk.clone(), emissiveIntensity: 1.2, roughness: 0.3 }),
    lampHvsg: std({ color: DYN.lampOk.clone(), emissive: DYN.lampOk.clone(), emissiveIntensity: 1.2, roughness: 0.3 }),
    gsuTank: std({ color: DYN.tankBase.clone(), metalness: 0.3, roughness: 0.6 }),
  };
}

/** Pipe material key (layout.ts FlowPath.pipe.material) → finish + colour. */
export const PIPE_STYLE: Record<
  "steel" | "insulated" | "fuel" | "water" | "cable",
  { finish: Finish; color: string }
> = {
  steel: { finish: "metal", color: PAL.steel },
  insulated: { finish: "clad", color: PAL.cladding },
  fuel: { finish: "paint", color: PAL.fuel },
  water: { finish: "paint", color: PAL.water },
  cable: { finish: "matte", color: PAL.cable },
};
