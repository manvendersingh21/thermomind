/**
 * The three.js / react-three-fiber scene. Loaded lazily (React.lazy) so three.js stays out of the
 * core bundle. Read-only visualisation: nothing here can write to any plant system.
 */
import { Suspense, memo, useEffect, useMemo, useRef, type MutableRefObject } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Grid, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { CAMERA_POSITION, CAMERA_TARGET, EQUIPMENT_BY_ID } from "../layout";
import type { EquipmentId, Hotspot, LiveState } from "../types";
import { Equipment } from "./Equipment";
import { Flows } from "./Flows";
import { Hotspots, SyntheticRings } from "./Hotspots";
import { Picking } from "./Picking";
import { EquipmentLabels } from "./Labels";

export interface TwinSceneProps {
  live: MutableRefObject<LiveState>;
  hotspots: Hotspot[];
  syntheticRings: EquipmentId[];
  hovered: EquipmentId | null;
  selected: EquipmentId | null;
  onHover: (id: EquipmentId | null, clientX: number, clientY: number) => void;
  onSelect: (id: EquipmentId | null) => void;
  showLabels: boolean;
  /** Changing this value flies the camera to the equipment (null = overview). */
  focus: EquipmentId | null;
  focusNonce: number;
  /** Reports draw calls once a second (dev/perf readout). */
  onStats?: (s: { calls: number; triangles: number; fps: number }) => void;
}

const BG = "#f3f5f8";

function CameraRig({ focus, nonce }: { focus: EquipmentId | null; nonce: number }) {
  const controls = useThree((s) => s.controls) as unknown as OrbitControlsImpl | null;
  const camera = useThree((s) => s.camera);
  const anim = useRef<{ fromP: THREE.Vector3; toP: THREE.Vector3; fromT: THREE.Vector3; toT: THREE.Vector3; t: number } | null>(null);

  useEffect(() => {
    if (!controls) return;
    const toT = new THREE.Vector3(...CAMERA_TARGET);
    const toP = new THREE.Vector3(...CAMERA_POSITION);
    // Portrait / narrow canvases need a longer overview distance to fit the plant.
    const aspect = (camera as THREE.PerspectiveCamera).aspect || 1.4;
    if (aspect < 1.25) toP.sub(toT).multiplyScalar(Math.min(2.2, 1.3 / aspect)).add(toT);
    if (focus) {
      const e = EQUIPMENT_BY_ID[focus];
      toT.set(e.pos[0], e.pos[1], e.pos[2]);
      const r = Math.max(6, Math.max(...e.size) * 1.9);
      toP.set(e.pos[0] - r * 0.95, e.pos[1] + r * 0.7, e.pos[2] + r * 1.1);
    }
    anim.current = { fromP: camera.position.clone(), toP, fromT: controls.target.clone(), toT, t: 0 };
  }, [focus, nonce, controls, camera]);

  useFrame((_, dt) => {
    const a = anim.current;
    if (!a || !controls) return;
    a.t = Math.min(1, a.t + dt / 1.1);
    const k = a.t < 0.5 ? 2 * a.t * a.t : 1 - Math.pow(-2 * a.t + 2, 2) / 2;
    camera.position.lerpVectors(a.fromP, a.toP, k);
    controls.target.lerpVectors(a.fromT, a.toT, k);
    controls.update();
    if (a.t >= 1) anim.current = null;
  });
  return null;
}

function Stats({ onStats }: { onStats?: TwinSceneProps["onStats"] }) {
  const gl = useThree((s) => s.gl);
  const acc = useRef({ frames: 0, t: 0 });
  useFrame((_, dt) => {
    if (!onStats) return;
    acc.current.frames += 1;
    acc.current.t += dt;
    if (acc.current.t >= 1) {
      onStats({ calls: gl.info.render.calls, triangles: gl.info.render.triangles, fps: acc.current.frames / acc.current.t });
      acc.current = { frames: 0, t: 0 };
    }
  });
  return null;
}

function Lights() {
  const shadowCam = useMemo(() => ({ left: -30, right: 30, top: 26, bottom: -26, near: 1, far: 110 }), []);
  return (
    <>
      <hemisphereLight args={["#ffffff", "#c9d2dc", 1.15]} />
      <ambientLight intensity={0.25} />
      <directionalLight
        position={[18, 34, 22]}
        intensity={2.1}
        castShadow
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-left={shadowCam.left}
        shadow-camera-right={shadowCam.right}
        shadow-camera-top={shadowCam.top}
        shadow-camera-bottom={shadowCam.bottom}
        shadow-camera-near={shadowCam.near}
        shadow-camera-far={shadowCam.far}
        shadow-bias={-0.0004}
        shadow-normalBias={0.03}
        shadow-radius={4}
      />
      <directionalLight position={[-20, 12, -14]} intensity={0.45} color="#dbeafe" />
    </>
  );
}

function TwinScene(props: TwinSceneProps) {
  const { live, hotspots, syntheticRings, hovered, selected, onHover, onSelect, showLabels, focus, focusNonce, onStats } = props;
  return (
    <Canvas
      shadows
      dpr={[1, 1.75]}
      gl={{ antialias: true, powerPreference: "high-performance" }}
      camera={{ position: CAMERA_POSITION, fov: 38, near: 0.5, far: 400 }}
      onPointerMissed={() => onSelect(null)}
      style={{ background: BG }}
    >
      <color attach="background" args={[BG]} />
      <fog attach="fog" args={[BG, 70, 150]} />
      <Lights />
      <Suspense fallback={null}>
        <Equipment live={live} />
        <Flows live={live} />
        <SyntheticRings ids={syntheticRings} />
        <Hotspots hotspots={hotspots} live={live} />
        <Picking hovered={hovered} selected={selected} onHover={onHover} onSelect={onSelect} />
        {showLabels ? <EquipmentLabels hovered={hovered} /> : null}
      </Suspense>
      <Grid
        position={[0, 0.002, 4]}
        args={[90, 70]}
        cellSize={1}
        cellThickness={0.6}
        cellColor="#e3e8ee"
        sectionSize={5}
        sectionThickness={1}
        sectionColor="#cdd5df"
        fadeDistance={95}
        fadeStrength={1.4}
        infiniteGrid={false}
      />
      <mesh rotation-x={-Math.PI / 2} position={[0, -0.01, 4]} receiveShadow>
        <planeGeometry args={[140, 110]} />
        <meshStandardMaterial color="#eef1f5" roughness={1} metalness={0} />
      </mesh>
      <OrbitControls
        makeDefault
        target={CAMERA_TARGET}
        enableDamping
        dampingFactor={0.08}
        autoRotate={false}
        minDistance={6}
        maxDistance={90}
        maxPolarAngle={Math.PI * 0.48}
      />
      <CameraRig focus={focus} nonce={focusNonce} />
      <Stats onStats={onStats} />
    </Canvas>
  );
}

export default memo(TwinScene);
