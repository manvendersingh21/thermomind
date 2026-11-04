/** Pulsing "LOOK HERE" hot-spot markers and yellow SYNTHETIC rings around affected equipment. */
import { useMemo, useRef, type MutableRefObject } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import * as THREE from "three";
import { EQUIPMENT_BY_ID } from "../layout";
import type { EquipmentId, Hotspot, LiveState } from "../types";

const PRIMARY = "#dc2626";
const SECONDARY = "#f59e0b";
const SYNTH = "#eab308";

function HotspotMarker({ h, index }: { h: Hotspot; index: number; live: MutableRefObject<LiveState> }) {
  const e = EQUIPMENT_BY_ID[h.equipment];
  const color = h.kind === "primary" ? PRIMARY : SECONDARY;
  const top = e.pos[1] + e.size[1] / 2;
  const radius = Math.max(0.9, Math.max(e.size[0], e.size[2]) * 0.62);
  const ring = useRef<THREE.Mesh>(null);
  const cone = useRef<THREE.Mesh>(null);
  const beam = useRef<THREE.Mesh>(null);
  const ringMat = useMemo(() => new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.8, depthWrite: false, toneMapped: false }), [color]);
  const beamMat = useMemo(() => new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.18, depthWrite: false, toneMapped: false }), [color]);
  const coneMat = useMemo(() => new THREE.MeshBasicMaterial({ color, toneMapped: false }), [color]);
  const beamH = h.kind === "primary" ? 3.2 : 1.2;
  useFrame(({ clock }) => {
    const t = clock.elapsedTime * 2.2 + index;
    const k = (Math.sin(t) + 1) / 2;
    if (ring.current) {
      const s = 1 + 0.18 * k;
      ring.current.scale.set(s, s, s);
      ringMat.opacity = 0.45 + 0.5 * k;
    }
    if (cone.current) cone.current.position.y = top + beamH + 0.6 + 0.35 * Math.sin(t * 0.8);
    if (beam.current) beamMat.opacity = 0.1 + 0.16 * k;
  });
  return (
    <group>
      <mesh ref={ring} position={[e.pos[0], e.pos[1], e.pos[2]]} rotation-x={-Math.PI / 2} material={ringMat}>
        <torusGeometry args={[radius, h.kind === "primary" ? 0.09 : 0.07, 8, 48]} />
      </mesh>
      <mesh ref={beam} position={[e.pos[0], top + beamH / 2, e.pos[2]]} material={beamMat}>
        <cylinderGeometry args={[0.12, 0.12, beamH, 10, 1, true]} />
      </mesh>
      <mesh ref={cone} position={[e.pos[0], top + beamH + 0.6, e.pos[2]]} rotation-x={Math.PI} material={coneMat}>
        <coneGeometry args={[0.45, 0.9, 16]} />
      </mesh>
      <Html position={[e.pos[0], Math.min(top + beamH + 1.4, 13), e.pos[2] + (top + beamH + 1.4 > 13 ? 1.4 : 0)]} center zIndexRange={[30, 10]} style={{ pointerEvents: "none" }}>
        <div
          className={`w-max max-w-[200px] whitespace-normal rounded-md border-2 px-2.5 py-1 text-xs font-bold shadow-lg sm:max-w-none sm:whitespace-nowrap ${
            h.kind === "primary" ? "border-red-700 bg-red-600 text-white" : "border-amber-600 bg-amber-100 text-amber-900"
          }`}
          data-testid={`hotspot-${h.equipment}`}
        >
          {h.label}
          {h.synthetic ? (
            <span className="ml-1.5 rounded bg-yellow-300 px-1 py-px text-[10px] font-bold text-yellow-950">SYNTHETIC</span>
          ) : null}
        </div>
      </Html>
    </group>
  );
}

export function Hotspots({ hotspots, live }: { hotspots: Hotspot[]; live: MutableRefObject<LiveState> }) {
  return (
    <group>
      {hotspots.map((h, i) => (
        <HotspotMarker key={h.id} h={h} index={i} live={live} />
      ))}
    </group>
  );
}

function Ring({ id, index }: { id: EquipmentId; index: number }) {
  const e = EQUIPMENT_BY_ID[id];
  const radius = Math.max(0.8, Math.max(e.size[0], e.size[2]) * 0.72 + 0.35);
  const ref = useRef<THREE.Mesh>(null);
  const mat = useMemo(() => new THREE.MeshBasicMaterial({ color: SYNTH, transparent: true, opacity: 0.85, toneMapped: false, depthWrite: false }), []);
  useFrame(({ clock }) => {
    if (ref.current) ref.current.rotation.z = clock.elapsedTime * 0.6 + index;
    mat.opacity = 0.55 + 0.3 * Math.sin(clock.elapsedTime * 1.6 + index);
  });
  // Dashed look: a torus with gaps via a partial arc, rotated.
  return (
    <mesh ref={ref} position={[e.pos[0], e.pos[1] - e.size[1] * 0.25, e.pos[2]]} rotation-x={-Math.PI / 2} material={mat}>
      <torusGeometry args={[radius, 0.07, 6, 64, Math.PI * 1.7]} />
    </mesh>
  );
}

export function SyntheticRings({ ids }: { ids: EquipmentId[] }) {
  return (
    <group>
      {ids.map((id, i) => (
        <Ring key={id} id={id} index={i} />
      ))}
    </group>
  );
}
