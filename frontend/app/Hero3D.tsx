"use client";

import { useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Line, Points, PointMaterial } from "@react-three/drei";
import * as THREE from "three";

// Interactive 3D backdrop for the hero -- an abstract constellation of nodes
// standing in for the seven pipeline stages (Event/Predict/Retrieve/Decide/
// Act/Measure/Learn), never labeled in 3D text (illegible at this scale),
// just the *shape* of a live decision graph: nodes, edges, gentle drift,
// parallax toward the cursor. Confined to the hero -- not a sitewide layer --
// so the rest of the (data-dense) console never competes with a GPU-driven
// background. Respects prefers-reduced-motion by freezing all motion.

const NODE_COUNT = 46;
const CONNECT_DISTANCE = 2.6;
const SEED = 1337;

function seededRandom(seed: number) {
  let s = seed;
  return () => {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

function useGraph() {
  return useMemo(() => {
    const rand = seededRandom(SEED);
    const positions: [number, number, number][] = [];
    for (let i = 0; i < NODE_COUNT; i++) {
      const r = 3.4 + rand() * 1.4;
      const theta = rand() * Math.PI * 2;
      const phi = Math.acos(2 * rand() - 1);
      positions.push([
        r * Math.sin(phi) * Math.cos(theta) * 0.9,
        r * Math.sin(phi) * Math.sin(theta) * 0.6,
        r * Math.cos(phi) * 0.9 - 1,
      ]);
    }
    const flat = new Float32Array(positions.length * 3);
    positions.forEach(([x, y, z], i) => {
      flat[i * 3] = x;
      flat[i * 3 + 1] = y;
      flat[i * 3 + 2] = z;
    });

    const edges: [[number, number, number], [number, number, number]][] = [];
    for (let i = 0; i < positions.length; i++) {
      for (let j = i + 1; j < positions.length; j++) {
        const a = positions[i];
        const b = positions[j];
        const d = Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
        if (d < CONNECT_DISTANCE) edges.push([a, b]);
      }
    }
    return { positions: flat, edges };
  }, []);
}

function ConstellationGroup({ reducedMotion }: { reducedMotion: boolean }) {
  const group = useRef<THREE.Group>(null);
  const pointer = useRef({ x: 0, y: 0 });
  const { positions, edges } = useGraph();

  useFrame((state, delta) => {
    if (!group.current) return;
    if (!reducedMotion) {
      group.current.rotation.y += delta * 0.045;
      pointer.current.x = state.pointer.x;
      pointer.current.y = state.pointer.y;
      group.current.rotation.x = THREE.MathUtils.lerp(group.current.rotation.x, pointer.current.y * 0.18, 0.04);
      group.current.rotation.y = THREE.MathUtils.lerp(group.current.rotation.y, group.current.rotation.y + pointer.current.x * 0.06, 0.04);
    }
  });

  return (
    <group ref={group}>
      <Points positions={positions} stride={3}>
        <PointMaterial
          transparent
          color="#5c8bff"
          size={0.05}
          sizeAttenuation
          depthWrite={false}
          opacity={0.85}
        />
      </Points>
      {edges.map((edge, i) => (
        <Line key={i} points={edge} color="#3d74f0" lineWidth={0.5} transparent opacity={0.14} />
      ))}
    </group>
  );
}

export default function Hero3D({ reducedMotion = false }: { reducedMotion?: boolean }) {
  return (
    <Canvas
      dpr={[1, 1.5]}
      gl={{ antialias: true, alpha: true }}
      camera={{ position: [0, 0, 7.5], fov: 45 }}
      className="!absolute inset-0"
    >
      <ConstellationGroup reducedMotion={reducedMotion} />
    </Canvas>
  );
}
