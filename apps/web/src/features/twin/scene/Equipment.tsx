/**
 * Procedural equipment geometry for the 3D twin: static plant merged into a few finish buckets
 * (one draw call each) plus a handful of dynamic meshes driven from `live` inside useFrame.
 * Picking, labels, hot-spots, flow particles, ground and lights live elsewhere.
 */
import { useEffect, useMemo, useRef, type MutableRefObject } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { GT_AXIS_Y } from "../layout";
import type { LiveState } from "../types";
import { buildPlant, GAUGE } from "./geometry/plant";
import { createDynamicMaterials, createStaticMaterials, DYN, FINISHES } from "./materials";

const DEG = Math.PI / 180;
/** Stylised shaft speed (rad/s at live.speed = 1). */
const SHAFT_RAD_S = 7;

const clamp01 = (v: number) => (Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0);

/** Status lamp: 0 → green, 0.5 → amber, ≥ 1 → red. */
function lampColor(heat: number, out: THREE.Color): THREE.Color {
  const h = clamp01(heat);
  return h < 0.5 ? out.lerpColors(DYN.lampOk, DYN.lampWarn, h / 0.5) : out.lerpColors(DYN.lampWarn, DYN.lampAlarm, (h - 0.5) / 0.5);
}

export function Equipment({ live }: { live: MutableRefObject<LiveState> }) {
  const plant = useMemo(() => buildPlant(), []);
  const smat = useMemo(() => createStaticMaterials(), []);
  const dmat = useMemo(() => createDynamicMaterials(), []);

  useEffect(
    () => () => {
      for (const g of Object.values(plant.statics)) g.dispose();
      for (const [k, g] of Object.entries(plant)) if (k !== "statics") (g as THREE.BufferGeometry).dispose();
      for (const m of Object.values(smat)) m.dispose();
      for (const m of Object.values(dmat)) m.dispose();
    },
    [plant, smat, dmat],
  );

  const rotorRef = useRef<THREE.Mesh>(null);
  const needleRef = useRef<THREE.Mesh>(null);
  const anim = useRef({ phase: 0, needle: 0 });

  useFrame((_, rawDt) => {
    const L = live.current;
    const dt = Math.min(rawDt, 0.1);
    const speed = Number.isFinite(L.speed) ? Math.max(0, L.speed) : 1;
    const a = anim.current;
    a.phase += dt * speed;
    const t = a.phase;

    if (rotorRef.current) rotorRef.current.rotation.x = (rotorRef.current.rotation.x + dt * SHAFT_RAD_S * speed) % (Math.PI * 2);

    // Filter face: clean → dirty with AFDP.
    dmat.filterFace.color.lerpColors(DYN.filterClean, DYN.filterDirty, clamp01(L.n.afdp));

    // Combustor cans: colour + emissive intensity by TIT, with a small flicker.
    const tit = clamp01(L.n.tit);
    if (tit < 0.5) dmat.cans.emissive.lerpColors(DYN.canLow, DYN.canMid, tit / 0.5);
    else dmat.cans.emissive.lerpColors(DYN.canMid, DYN.canHigh, (tit - 0.5) / 0.5);
    dmat.cans.color.lerpColors(DYN.canBodyLow, DYN.canBodyHigh, tit);
    const flicker = speed > 0 ? 0.07 * Math.sin(t * 23.0) + 0.05 * Math.sin(t * 37.3 + 1.3) : 0;
    dmat.cans.emissiveIntensity = Math.max(0.2, 0.4 + 1.2 * tit + flicker * (0.5 + tit));

    // Generator glow ∝ TEY with a gentle pulse.
    const tey = clamp01(L.n.tey);
    dmat.genGlow.emissiveIntensity = 0.05 + tey * 1.5 * (0.85 + 0.15 * Math.sin(t * 2.6));

    // CDP gauge: 0..1 → -120°..+120° (clockwise), smoothed.
    const target = (clamp01(L.n.cdp) * 240 - 120) * DEG;
    a.needle += (target - a.needle) * Math.min(1, dt * 6);
    if (needleRef.current) needleRef.current.rotation.z = -a.needle;

    // Breaker / switchgear status lamps (simulated heat), blinking when ≥ 1.
    const h52 = L.heat.GCB ?? 0;
    lampColor(h52, dmat.lamp52g.color);
    dmat.lamp52g.emissive.copy(dmat.lamp52g.color);
    dmat.lamp52g.emissiveIntensity = h52 >= 1 ? 0.8 + 0.8 * (Math.sin(t * 8) > 0 ? 1 : 0) : 1.1;
    const hHv = L.heat.HVSG ?? 0;
    lampColor(hHv, dmat.lampHvsg.color);
    dmat.lampHvsg.emissive.copy(dmat.lampHvsg.color);
    dmat.lampHvsg.emissiveIntensity = hHv >= 1 ? 0.8 + 0.8 * (Math.sin(t * 8) > 0 ? 1 : 0) : 1.1;

    // GSU tank warms toward orange only above 0.8 heat.
    const hG = L.heat.GSU ?? 0;
    const k = Number.isFinite(hG) ? Math.min(1, Math.max(0, (hG - 0.8) / 0.4)) * 0.6 : 0;
    dmat.gsuTank.color.lerpColors(DYN.tankBase, DYN.tankHot, k);
  });

  return (
    <group name="equipment">
      {FINISHES.map((f) => (
        <mesh key={f} geometry={plant.statics[f]} material={smat[f]} castShadow receiveShadow />
      ))}
      <mesh geometry={plant.filterFace} material={dmat.filterFace} receiveShadow />
      <mesh geometry={plant.cans} material={dmat.cans} castShadow />
      <mesh geometry={plant.genGlow} material={dmat.genGlow} />
      <mesh geometry={plant.gsuTank} material={dmat.gsuTank} castShadow receiveShadow />
      <mesh geometry={plant.lamp52g} material={dmat.lamp52g} />
      <mesh geometry={plant.lampHvsg} material={dmat.lampHvsg} />
      <mesh ref={rotorRef} geometry={plant.rotor} material={dmat.rotor} position={[0, GT_AXIS_Y, 0]} castShadow />
      <group position={GAUGE.pos} rotation={[GAUGE.tilt, 0, 0]}>
        <mesh ref={needleRef} geometry={plant.needle} material={dmat.needle} position={[0, 0, GAUGE.needleZ]} />
      </group>
      <mesh geometry={plant.casing} material={dmat.casing} renderOrder={2} />
    </group>
  );
}
