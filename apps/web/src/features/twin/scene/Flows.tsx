/**
 * Animated flows as instanced particles along Catmull-Rom curves (one InstancedMesh per flow kind).
 * Speed / brightness are scaled by the current sample in `live` (TEY, TIT, AFDP, GTEP, CO, NOx).
 */
import { useMemo, useRef, type MutableRefObject } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { FLOW_PATHS, type FlowPath } from "../layout";
import type { FlowKind, LiveState } from "../types";

const LUT = 200;

interface Track {
  lut: Float32Array; // LUT * 3 positions (arc-length spaced)
  tan: Float32Array; // LUT * 3 tangents
}

function buildTrack(p: FlowPath): Track {
  const curve = new THREE.CatmullRomCurve3(
    p.points.map((v) => new THREE.Vector3(v[0], v[1], v[2])),
    false,
    "centripetal",
  );
  const lut = new Float32Array(LUT * 3);
  const tan = new Float32Array(LUT * 3);
  for (let i = 0; i < LUT; i += 1) {
    const u = i / (LUT - 1);
    const pt = curve.getPointAt(u);
    const t = curve.getTangentAt(u);
    lut.set([pt.x, pt.y, pt.z], i * 3);
    tan.set([t.x, t.y, t.z], i * 3);
  }
  return { lut, tan };
}

function sample(track: Track, u: number, out: THREE.Vector3, outTan?: THREE.Vector3) {
  const f = Math.min(0.99999, Math.max(0, u)) * (LUT - 1);
  const i = Math.floor(f);
  const a = f - i;
  const j = Math.min(LUT - 1, i + 1);
  const L = track.lut;
  out.set(
    L[i * 3] + (L[j * 3] - L[i * 3]) * a,
    L[i * 3 + 1] + (L[j * 3 + 1] - L[i * 3 + 1]) * a,
    L[i * 3 + 2] + (L[j * 3 + 2] - L[i * 3 + 2]) * a,
  );
  if (outTan) {
    const T = track.tan;
    outTan.set(T[i * 3], T[i * 3 + 1], T[i * 3 + 2]);
  }
}

/** Deterministic PRNG so particle layouts are stable between renders. */
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

interface Particle {
  track: number;
  phase: number;
  off: THREE.Vector3;
  size: number;
  speed: number;
}

const COLORS: Record<FlowKind, string> = {
  air: "#7cc4f5",
  fuel: "#f97316",
  gas: "#ef4444",
  steam: "#ffffff",
  water: "#06b6d4",
  power: "#facc15",
  dust: "#a16207",
  plume: "#9ca3af",
  vapor: "#ffffff",
};

/** Speed driver per kind from live state. */
function driver(kind: FlowKind, live: LiveState): number {
  const tey = live.n.tey;
  switch (kind) {
    case "air":
    case "fuel":
    case "gas":
      return 0.45 + 0.9 * tey;
    case "steam":
    case "water":
      return 0.4 + 0.7 * tey;
    case "power":
      return 0.25 + 1.6 * tey;
    default:
      return 1;
  }
}

const UP = new THREE.Vector3(0, 1, 0);

function FlowKindMesh({ kind, paths, live }: { kind: FlowKind; paths: FlowPath[]; live: MutableRefObject<LiveState> }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const tracks = useMemo(() => paths.map(buildTrack), [paths]);
  const particles = useMemo(() => {
    const r = rng(kind.length * 977 + paths.length * 31);
    const out: Particle[] = [];
    paths.forEach((p, ti) => {
      for (let k = 0; k < p.count; k += 1) {
        const ang = r() * Math.PI * 2;
        const rad = p.spread * Math.sqrt(r());
        out.push({
          track: ti,
          phase: (k + r() * 0.6) / p.count,
          off: new THREE.Vector3(Math.cos(ang) * rad, (r() - 0.5) * 2 * rad, Math.sin(ang) * rad),
          size: p.size * (0.75 + r() * 0.5),
          speed: p.speed * (0.9 + r() * 0.2),
        });
      }
    });
    return out;
  }, [paths, kind]);

  const arrow = kind === "water" || kind === "steam" || kind === "fuel";
  const geometry = useMemo(() => {
    if (arrow) {
      const g = new THREE.ConeGeometry(1, 2.6, 8);
      return g;
    }
    return new THREE.IcosahedronGeometry(1, kind === "power" ? 1 : 0);
  }, [arrow, kind]);
  const material = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: "#ffffff",
        transparent: kind === "air" || kind === "gas",
        opacity: kind === "air" ? 0.8 : 0.92,
        toneMapped: false,
        depthWrite: !(kind === "air" || kind === "gas"),
      }),
    [kind],
  );

  const tmp = useMemo(
    () => ({
      m: new THREE.Matrix4(),
      p: new THREE.Vector3(),
      t: new THREE.Vector3(),
      q: new THREE.Quaternion(),
      s: new THREE.Vector3(),
      c: new THREE.Color(),
      base: new THREE.Color(COLORS[kind]),
      hot: new THREE.Color(),
      grey: new THREE.Color("#9aa3ad"),
      clock: 0,
      progress: new Float32Array(particles.length).map((_, i) => particles[i].phase),
    }),
    [kind, particles],
  );

  useFrame((_, dtRaw) => {
    const mesh = ref.current;
    if (!mesh) return;
    const L = live.current;
    const dt = Math.min(dtRaw, 0.05) * L.speed;
    tmp.clock += dt;
    const drv = driver(kind, L);
    const hasData = L.row !== null;
    const powerOn = kind !== "power" || !hasData || (L.v.TEY ?? 0) > 0;
    // Gas starts at a TIT-dependent hot colour and cools towards grey along the path.
    if (kind === "gas") tmp.hot.setHSL(0.02 + 0.08 * L.n.tit, 1, 0.5 + 0.08 * L.n.tit);
    for (let i = 0; i < particles.length; i += 1) {
      const pt = particles[i];
      tmp.progress[i] = (tmp.progress[i] + dt * pt.speed * drv) % 1;
      const u = tmp.progress[i];
      sample(tracks[pt.track], u, tmp.p, arrow ? tmp.t : undefined);
      tmp.p.add(pt.off);
      let s = pt.size;
      if (kind === "power") {
        // Pulses: brightness and size breathe with TEY.
        const pulse = 0.65 + 0.35 * Math.sin(tmp.clock * (4 + 8 * L.n.tey) + i * 1.7);
        s *= powerOn ? 0.7 + 0.6 * L.n.tey * pulse : 0;
        tmp.c.copy(tmp.base).multiplyScalar(0.6 + 0.6 * pulse * (0.4 + L.n.tey));
      } else if (kind === "gas") {
        tmp.c.copy(tmp.hot).lerp(tmp.grey, Math.min(1, u * 1.25));
        s *= 1 + u * 0.6;
      } else if (kind === "air") {
        tmp.c.copy(tmp.base);
      } else {
        tmp.c.copy(tmp.base);
      }
      // fade in/out at the ends
      const edge = Math.min(1, u * 12, (1 - u) * 12);
      s *= 0.35 + 0.65 * edge;
      if (arrow) {
        tmp.q.setFromUnitVectors(UP, tmp.t);
        tmp.s.set(s, s, s);
      } else {
        tmp.q.identity();
        tmp.s.set(s, s, s);
      }
      tmp.m.compose(tmp.p, tmp.q, tmp.s);
      mesh.setMatrixAt(i, tmp.m);
      mesh.setColorAt(i, tmp.c);
    }
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  });

  return <instancedMesh ref={ref} args={[geometry, material, particles.length]} frustumCulled={false} />;
}

/** Dust drifting into the intake: count ∝ AFDP (filter loading). */
function Dust({ live }: { live: MutableRefObject<LiveState> }) {
  const N = 70;
  const ref = useRef<THREE.InstancedMesh>(null);
  const seeds = useMemo(() => {
    const r = rng(4242);
    return Array.from({ length: N }, () => ({ y: 6.2 + r() * 2.8, z: -2.4 + r() * 4.8, x0: -18 + r() * 3, sp: 0.6 + r() * 0.8, ph: r(), s: 0.04 + r() * 0.05 }));
  }, []);
  const geometry = useMemo(() => new THREE.IcosahedronGeometry(1, 0), []);
  const material = useMemo(() => new THREE.MeshBasicMaterial({ color: COLORS.dust, transparent: true, opacity: 0.75, depthWrite: false }), []);
  const tmp = useMemo(() => ({ m: new THREE.Matrix4(), clock: 0 }), []);
  useFrame((_, dtRaw) => {
    const mesh = ref.current;
    if (!mesh) return;
    const L = live.current;
    tmp.clock += Math.min(dtRaw, 0.05) * L.speed;
    const visible = Math.round(N * Math.min(1, Math.max(0, (L.n.afdp - 0.15) / 0.85)));
    for (let i = 0; i < N; i += 1) {
      const d = seeds[i];
      const u = (d.ph + tmp.clock * 0.12 * d.sp) % 1;
      const x = d.x0 + u * (-12.3 - d.x0);
      const y = d.y + Math.sin(tmp.clock * 1.3 + i) * 0.15;
      const s = i < visible ? d.s : 0;
      tmp.m.makeScale(s, s, s).setPosition(x, y, d.z);
      mesh.setMatrixAt(i, tmp.m);
    }
    mesh.instanceMatrix.needsUpdate = true;
  });
  return <instancedMesh ref={ref} args={[geometry, material, N]} frustumCulled={false} />;
}

/** Rising puffs: stack plume (size ∝ GTEP, tint by CO/NOx) or cooling-tower vapour. */
function Puffs({ live, kind }: { live: MutableRefObject<LiveState>; kind: "plume" | "vapor" }) {
  const N = kind === "plume" ? 34 : 30;
  const origin = kind === "plume" ? new THREE.Vector3(9.4, 15.2, 0) : new THREE.Vector3(16, 10.2, 5);
  const ref = useRef<THREE.InstancedMesh>(null);
  const seeds = useMemo(() => {
    const r = rng(kind === "plume" ? 77 : 99);
    return Array.from({ length: N }, (_, i) => ({ ph: i / N + r() * 0.02, a: r() * Math.PI * 2, rr: r() }));
  }, [N, kind]);
  const geometry = useMemo(() => new THREE.IcosahedronGeometry(1, 1), []);
  const material = useMemo(
    () => new THREE.MeshLambertMaterial({ color: "#ffffff", transparent: true, opacity: kind === "plume" ? 0.32 : 0.42, depthWrite: false }),
    [kind],
  );
  const tmp = useMemo(
    () => ({ m: new THREE.Matrix4(), c: new THREE.Color(), clean: new THREE.Color("#d7dbe0"), co: new THREE.Color("#5b5b5b"), nox: new THREE.Color("#b45309"), clock: 0 }),
    [],
  );
  useFrame((_, dtRaw) => {
    const mesh = ref.current;
    if (!mesh) return;
    const L = live.current;
    tmp.clock += Math.min(dtRaw, 0.05) * L.speed;
    const scale = kind === "plume" ? 0.7 + 1.2 * L.n.gtep : 1.2;
    const rise = kind === "plume" ? 5 + 4 * L.n.tey : 4;
    if (kind === "plume") {
      tmp.c.copy(tmp.clean).lerp(tmp.nox, Math.min(0.7, Math.max(0, L.n.nox - 0.55) * 1.6)).lerp(tmp.co, Math.min(0.6, Math.max(0, L.n.co - 0.55) * 1.4));
      material.color.copy(tmp.c);
    }
    for (let i = 0; i < N; i += 1) {
      const d = seeds[i];
      const u = (d.ph + tmp.clock * (kind === "plume" ? 0.11 : 0.06)) % 1;
      const drift = u * u * (kind === "plume" ? 3.2 : 2);
      const x = origin.x + Math.cos(d.a) * d.rr * 0.5 * (1 + u * 2) + drift;
      const z = origin.z + Math.sin(d.a) * d.rr * 0.5 * (1 + u * 2) + drift * 0.3;
      const y = origin.y + u * rise;
      const s = scale * (0.35 + u * 1.3) * Math.min(1, u * 6) * (1 - u * 0.4);
      tmp.m.makeScale(s, s, s).setPosition(x, y, z);
      mesh.setMatrixAt(i, tmp.m);
    }
    mesh.instanceMatrix.needsUpdate = true;
  });
  return <instancedMesh ref={ref} args={[geometry, material, N]} frustumCulled={false} />;
}

export function Flows({ live }: { live: MutableRefObject<LiveState> }) {
  const groups = useMemo(() => {
    const m = new Map<FlowKind, FlowPath[]>();
    for (const p of FLOW_PATHS) m.set(p.kind, [...(m.get(p.kind) ?? []), p]);
    return [...m.entries()];
  }, []);
  return (
    <group>
      {groups.map(([kind, paths]) => (
        <FlowKindMesh key={kind} kind={kind} paths={paths} live={live} />
      ))}
      <Dust live={live} />
      <Puffs live={live} kind="plume" />
      <Puffs live={live} kind="vapor" />
    </group>
  );
}
