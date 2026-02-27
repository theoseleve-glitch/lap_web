'use client';

import { useRef, useMemo, useEffect } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import type { ChapterSceneProps } from '@/experience/state/types';
import { background } from '@/experience/motion/springs';
import { useKernelStore } from '@/experience/state/store';
import { grainVertex, grainFragment } from './shaders/grain';
import { vignetteVertex, vignetteFragment } from './shaders/vignette';

// ── Types ──────────────────────────────────────────────

interface LivingSurfaceProps extends ChapterSceneProps {
  color?: string;
  fogDensity?: number;
}

interface Streak {
  alive: boolean;
  age: number;
  x: number;
  y: number;
  heading: number;
}

// ── Constants ──────────────────────────────────────────

const PARTICLE_COUNT = 200;
const CONTOUR_SEGMENTS = 64;
const STREAK_POOL_SIZE = background.streakCount;

// ── Helpers ────────────────────────────────────────────

/** Build a single organic contour ring as a set of points */
function buildContourPoints(index: number, total: number): Float32Array {
  const points = new Float32Array(CONTOUR_SEGMENTS * 3);
  const baseRadius = 1.5 + (index / total) * 6.0;
  const phaseOffset = index * 1.23;
  for (let i = 0; i < CONTOUR_SEGMENTS; i++) {
    const t = (i / CONTOUR_SEGMENTS) * Math.PI * 2;
    const wobble = 0.3 * Math.sin(t * 3 + phaseOffset) + 0.15 * Math.cos(t * 5 + phaseOffset * 2);
    const r = baseRadius + wobble;
    points[i * 3] = Math.cos(t) * r;
    points[i * 3 + 1] = Math.sin(t) * r;
    points[i * 3 + 2] = 0;
  }
  return points;
}

// ── Component ──────────────────────────────────────────

export function LivingSurface({
  color = '#0B0C0F',
  fogDensity = 0.03,
  progress,
  scrollVelocity: _scrollVelocityProp,
  pointerX: _pointerXProp,
  pointerY: _pointerYProp,
  qualityTier,
  active,
}: LivingSurfaceProps) {
  const groupRef = useRef<THREE.Group>(null);
  const { size } = useThree();

  const isHigh = qualityTier === 'high';
  const isBalanced = qualityTier === 'balanced';
  const isLow = qualityTier === 'low';

  // ── Layer 1: Grain shader material ─────────────────

  const grainUniforms = useMemo(() => ({
    uTime: { value: 0 },
    uIntensity: { value: background.grainIntensity },
  }), []);

  const grainMaterial = useMemo(() => {
    return new THREE.ShaderMaterial({
      vertexShader: grainVertex,
      fragmentShader: grainFragment,
      uniforms: grainUniforms,
      transparent: true,
      depthWrite: false,
      depthTest: false,
    });
  }, [grainUniforms]);

  // ── Layer 2: Contour lines (high + balanced only) ──

  const contourCount = isHigh ? background.contourCount : isBalanced ? 0 : 0;

  const contourData = useMemo(() => {
    if (contourCount === 0) return null;
    const geometries: THREE.BufferGeometry[] = [];
    const materials: THREE.LineBasicMaterial[] = [];
    for (let i = 0; i < contourCount; i++) {
      const pts = buildContourPoints(i, contourCount);
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(pts, 3));
      geometries.push(geo);

      const mat = new THREE.LineBasicMaterial({
        color: '#F3F0E8',
        transparent: true,
        opacity: 0.04 + (i / contourCount) * 0.03,
        depthWrite: false,
      });
      materials.push(mat);
    }
    return { geometries, materials };
  }, [contourCount]);

  const contourRefs = useRef<(THREE.LineLoop | null)[]>([]);

  // ── Layer 3: Particle drift ────────────────────────

  const particleCount = isLow ? 0 : isBalanced ? Math.floor(PARTICLE_COUNT / 2) : PARTICLE_COUNT;

  const particlePositions = useMemo(() => {
    const arr = new Float32Array(particleCount * 3);
    for (let i = 0; i < particleCount; i++) {
      arr[i * 3] = (Math.random() - 0.5) * 20;
      arr[i * 3 + 1] = (Math.random() - 0.5) * 20;
      arr[i * 3 + 2] = (Math.random() - 0.5) * 5;
    }
    return arr;
  }, [particleCount]);

  const particlesRef = useRef<THREE.Points>(null);

  // ── Layer 4: Speed streaks (high only) ─────────────

  const streakPool = useRef<Streak[]>(
    Array.from({ length: STREAK_POOL_SIZE }, () => ({
      alive: false,
      age: 0,
      x: 0,
      y: 0,
      heading: 0,
    })),
  );

  const streakPositions = useMemo(() => {
    // Each streak = 2 vertices (start, end) = 6 floats
    return new Float32Array(STREAK_POOL_SIZE * 6);
  }, []);

  const streakOpacities = useMemo(() => {
    return new Float32Array(STREAK_POOL_SIZE * 2);
  }, []);

  const streakGeo = useMemo(() => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(streakPositions, 3));
    geo.setAttribute('opacity', new THREE.BufferAttribute(streakOpacities, 1));
    return geo;
  }, [streakPositions, streakOpacities]);

  const streakMat = useMemo(() => {
    return new THREE.LineBasicMaterial({
      color: '#F3F0E8',
      transparent: true,
      opacity: 0.3,
      depthWrite: false,
    });
  }, []);

  const streakLinesRef = useRef<THREE.LineSegments>(null);

  // ── Layer 5: Vignette shader ───────────────────────

  const vignetteUniforms = useMemo(() => ({
    uRadius: { value: background.vignetteRadius },
    uShift: { value: new THREE.Vector2(0, 0) },
  }), []);

  const vignetteMaterial = useMemo(() => {
    return new THREE.ShaderMaterial({
      vertexShader: vignetteVertex,
      fragmentShader: vignetteFragment,
      uniforms: vignetteUniforms,
      transparent: true,
      depthWrite: false,
      depthTest: false,
    });
  }, [vignetteUniforms]);

  // ── Animation loop ─────────────────────────────────

  useFrame((_, delta) => {
    if (!active) return;

    // Read high-frequency state via getState() to avoid re-renders
    const state = useKernelStore.getState();
    const { trackPath, scrollVelocity, pointerX, pointerY } = state;

    // -- Grain: animate time
    grainUniforms.uTime.value += delta;

    // -- Contours: slow drift + pointer/heading influence
    if (contourData && contourRefs.current.length > 0) {
      const driftAngle = grainUniforms.uTime.value * background.contourDriftSpeed;
      const pxInfluence = (pointerX - 0.5) * background.contourPointerInfluence;
      const pyInfluence = (pointerY - 0.5) * background.contourPointerInfluence;
      const headingInfluence = trackPath.heading * 0.01;

      for (let i = 0; i < contourRefs.current.length; i++) {
        const line = contourRefs.current[i];
        if (!line) continue;
        const layerSpeed = 1 + (i / contourCount) * 0.5;
        line.rotation.z = driftAngle * layerSpeed + headingInfluence;
        line.position.x = pxInfluence * (i + 1);
        line.position.y = pyInfluence * (i + 1);
      }
    }

    // -- Particles: drift with heading, pointer attraction
    if (particlesRef.current && particleCount > 0) {
      const posArray = particlesRef.current.geometry.attributes.position.array as Float32Array;
      const lateralDrift = trackPath.headingDelta * background.particleDriftX * delta;
      const verticalDrift = scrollVelocity * background.particleDriftY * delta;
      const cornerBoost = trackPath.isCorner ? 2.0 : 1.0;

      // Pointer in NDC-like coords (-10..10 for our world space)
      const pWorldX = (pointerX - 0.5) * 20;
      const pWorldY = (pointerY - 0.5) * 20;
      const attractRadius = background.particlePointerRadius / (size.width || 1) * 20;

      for (let i = 0; i < particleCount; i++) {
        const ix = i * 3;
        const iy = ix + 1;

        // Lateral drift from heading delta (turn-feel)
        posArray[ix] += lateralDrift * cornerBoost;
        // Vertical drift from scroll velocity
        posArray[iy] += verticalDrift;

        // Pointer attraction/repulsion
        const dx = pWorldX - posArray[ix];
        const dy = pWorldY - posArray[iy];
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < attractRadius && dist > 0.01) {
          const force = (1 - dist / attractRadius) * 0.02;
          posArray[ix] += dx * force;
          posArray[iy] += dy * force;
        }

        // Wrap around boundaries
        if (posArray[ix] > 10) posArray[ix] = -10;
        if (posArray[ix] < -10) posArray[ix] = 10;
        if (posArray[iy] > 10) posArray[iy] = -10;
        if (posArray[iy] < -10) posArray[iy] = 10;
      }
      particlesRef.current.geometry.attributes.position.needsUpdate = true;
    }

    // -- Streaks: spawn on high scroll velocity, age out
    if (isHigh && streakLinesRef.current) {
      const pool = streakPool.current;
      const lifetime = background.streakLifetime;
      const halfLen = background.streakLength / (size.width || 1) * 10; // world units
      const heading = trackPath.heading;

      // Spawn new streaks when velocity exceeds threshold
      if (Math.abs(scrollVelocity) > background.streakSpawnThreshold) {
        for (let i = 0; i < pool.length; i++) {
          if (!pool[i].alive) {
            pool[i].alive = true;
            pool[i].age = 0;
            pool[i].x = (Math.random() - 0.5) * 16;
            pool[i].y = (Math.random() - 0.5) * 16;
            pool[i].heading = heading;
            break; // spawn one per frame
          }
        }
      }

      // Update streak positions and ages
      for (let i = 0; i < pool.length; i++) {
        const s = pool[i];
        const base = i * 6;
        const opBase = i * 2;

        if (s.alive) {
          s.age += delta * 1000; // convert to ms
          if (s.age > lifetime) {
            s.alive = false;
          }
        }

        if (s.alive) {
          const lifeFrac = s.age / lifetime;
          // Fade in quickly, fade out
          const alpha = lifeFrac < 0.15 ? lifeFrac / 0.15 : 1 - (lifeFrac - 0.15) / 0.85;
          const cosH = Math.cos(s.heading);
          const sinH = Math.sin(s.heading);
          // Start point
          streakPositions[base] = s.x - cosH * halfLen;
          streakPositions[base + 1] = s.y - sinH * halfLen;
          streakPositions[base + 2] = 0;
          // End point
          streakPositions[base + 3] = s.x + cosH * halfLen;
          streakPositions[base + 4] = s.y + sinH * halfLen;
          streakPositions[base + 5] = 0;

          streakOpacities[opBase] = alpha;
          streakOpacities[opBase + 1] = alpha;
        } else {
          // Hide dead streaks by collapsing vertices
          streakPositions[base] = 0;
          streakPositions[base + 1] = 0;
          streakPositions[base + 2] = 0;
          streakPositions[base + 3] = 0;
          streakPositions[base + 4] = 0;
          streakPositions[base + 5] = 0;
          streakOpacities[opBase] = 0;
          streakOpacities[opBase + 1] = 0;
        }
      }
      streakGeo.attributes.position.needsUpdate = true;
      streakGeo.attributes.opacity.needsUpdate = true;

      // Modulate global streak material opacity based on velocity
      const vel = Math.abs(scrollVelocity);
      streakMat.opacity = Math.min(0.5, (vel - background.streakSpawnThreshold) * 0.8);
    }

    // -- Vignette: shift toward corner apex
    if (trackPath.isCorner) {
      const shiftX = Math.sin(trackPath.heading) * background.vignetteShift;
      const shiftY = -Math.cos(trackPath.heading) * background.vignetteShift;
      vignetteUniforms.uShift.value.lerp(new THREE.Vector2(shiftX, shiftY), 0.05);
    } else {
      vignetteUniforms.uShift.value.lerp(new THREE.Vector2(0, 0), 0.03);
    }
  });

  // ── Cleanup GPU resources on unmount ───────────────

  useEffect(() => {
    return () => {
      grainMaterial.dispose();
      vignetteMaterial.dispose();
      streakGeo.dispose();
      streakMat.dispose();
      if (contourData) {
        contourData.geometries.forEach((g) => g.dispose());
        contourData.materials.forEach((m) => m.dispose());
      }
    };
  }, [grainMaterial, vignetteMaterial, streakGeo, streakMat, contourData]);

  // ── Render ─────────────────────────────────────────

  return (
    <group ref={groupRef} visible={active} renderOrder={-100}>
      <fogExp2 attach="fog" args={[color, fogDensity]} />
      <ambientLight intensity={0.1} />

      {/* Layer 1: Grain — always renders */}
      <mesh renderOrder={-99}>
        <planeGeometry args={[50, 50]} />
        <primitive object={grainMaterial} attach="material" />
      </mesh>

      {/* Layer 2: Contour field — high quality only */}
      {contourData && contourData.geometries.map((geo, i) => (
        <lineLoop
          key={i}
          ref={(el: THREE.LineLoop | null) => { contourRefs.current[i] = el; }}
          geometry={geo}
          material={contourData.materials[i]}
          renderOrder={-98}
        />
      ))}

      {/* Layer 3: Particle drift */}
      {particleCount > 0 && (
        <points ref={particlesRef} renderOrder={-97}>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              args={[particlePositions, 3]}
            />
          </bufferGeometry>
          <pointsMaterial
            size={0.03}
            color="#F3F0E8"
            transparent
            opacity={0.2 + progress * 0.1}
            sizeAttenuation
            depthWrite={false}
          />
        </points>
      )}

      {/* Layer 4: Speed streaks — high quality only */}
      {isHigh && (
        <lineSegments
          ref={streakLinesRef}
          geometry={streakGeo}
          material={streakMat}
          renderOrder={-96}
        />
      )}

      {/* Layer 5: Vignette overlay */}
      <mesh renderOrder={-95}>
        <planeGeometry args={[50, 50]} />
        <primitive object={vignetteMaterial} attach="material" />
      </mesh>
    </group>
  );
}
