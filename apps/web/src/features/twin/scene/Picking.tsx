/**
 * Invisible hit-boxes (material.visible = false → raycast but no draw call) for hover/click,
 * plus a single outline box for the hovered / selected equipment.
 */
import { useMemo } from "react";
import type { ThreeEvent } from "@react-three/fiber";
import * as THREE from "three";
import { EQUIPMENT, EQUIPMENT_BY_ID } from "../layout";
import type { EquipmentId } from "../types";

interface Props {
  hovered: EquipmentId | null;
  selected: EquipmentId | null;
  onHover: (id: EquipmentId | null, clientX: number, clientY: number) => void;
  onSelect: (id: EquipmentId | null) => void;
}

const volume = (id: EquipmentId) => {
  const s = EQUIPMENT_BY_ID[id].size;
  return s[0] * s[1] * s[2];
};

/** Prefer small items (transmitters) when they are hit within ~2 units of the nearest hit. */
function pick(e: ThreeEvent<PointerEvent | MouseEvent>): EquipmentId | null {
  const hits = e.intersections.filter((i) => typeof i.object.userData.equipment === "string");
  if (hits.length === 0) return null;
  const nearest = hits[0].distance;
  const near = hits.filter((h) => h.distance <= nearest + 2.5).map((h) => h.object.userData.equipment as EquipmentId);
  near.sort((a, b) => volume(a) - volume(b));
  return near[0] ?? null;
}

function Outline({ id, color }: { id: EquipmentId; color: string }) {
  const e = EQUIPMENT_BY_ID[id];
  const geo = useMemo(() => new THREE.EdgesGeometry(new THREE.BoxGeometry(e.size[0] + 0.2, e.size[1] + 0.2, e.size[2] + 0.2)), [e]);
  return (
    <lineSegments position={e.pos} geometry={geo}>
      <lineBasicMaterial color={color} transparent opacity={0.9} depthTest={false} toneMapped={false} />
    </lineSegments>
  );
}

export function Picking({ hovered, selected, onHover, onSelect }: Props) {
  const hitMat = useMemo(() => new THREE.MeshBasicMaterial({ visible: false }), []);
  const box = useMemo(() => new THREE.BoxGeometry(1, 1, 1), []);
  return (
    <group>
      <group
        onPointerMove={(e) => {
          e.stopPropagation();
          onHover(pick(e), e.nativeEvent.clientX, e.nativeEvent.clientY);
        }}
        onPointerOut={(e) => {
          if (e.intersections.length === 0) onHover(null, 0, 0);
        }}
        onPointerLeave={() => onHover(null, 0, 0)}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(pick(e));
        }}
      >
        {EQUIPMENT.map((eq) => (
          <mesh
            key={eq.id}
            position={eq.pos}
            scale={eq.size}
            geometry={box}
            material={hitMat}
            userData={{ equipment: eq.id }}
          />
        ))}
      </group>
      {hovered && hovered !== selected ? <Outline id={hovered} color="#2563eb" /> : null}
      {selected ? <Outline id={selected} color="#16a34a" /> : null}
    </group>
  );
}
