'use client';

import { useRef, useMemo, useEffect } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { background } from '@/experience/motion/springs';
import { grainVertex, grainFragment } from './scenes/shaders/grain';
import { vignetteVertex, vignetteFragment } from './scenes/shaders/vignette';

const PARTICLE_COUNT_HIGH = 200;
const PARTICLE_COUNT_BALANCED = 100;

const _vignetteTarget = new THREE.Vector2();
const _vignetteCenter = new THREE.Vector2(0, 0);

interface Streak {
  alive: boolean;
  age: number;
  x: number;
  y: number;
  heading: number;
}

/**
 * Atmosphere — persistent 4-layer background (+ TrackRibbon as separate sibling).
 * L1: Grain (always)
 * L3: ParticleField (velocity-reactive drift)
 * L4: SpeedStreaks (scroll-velocity accents, high tier only)
 * L5: Vignette (readability shield)
 */
export function Atmosphere() {
  const { size } = useThree();
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);

  const isHigh = qualityTier === 'high';
  const isLow = qualityTier === 'low';
  const particleCount = isLow ? 0 : isHigh ? PARTICLE_COUNT_HIGH : PARTICLE_COUNT_BALANCED;

  // -- L1: Grain ------------------------------------------------
  const grainUniforms = useMemo(() => ({
    uTime: { value: 0 },
    uIntensity: { value: background.grainIntensity },
  }), []);

  const grainMaterial = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: grainVertex,
    fragmentShader: grainFragment,
    uniforms: grainUniforms,
    transparent: true,
    depthWrite: false,
    depthTest: false,
  }), [grainUniforms]);

  // -- L3: Particles ---------------------------------------------
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

  // -- L4: Speed Streaks -----------------------------------------
  const streakPoolSize = background.streakCount;
  const streakPool = useRef<Streak[]>(
    Array.from({ length: streakPoolSize }, () => ({
      alive: false, age: 0, x: 0, y: 0, heading: 0,
    })),
  );

  const streakPositions = useMemo(() => new Float32Array(streakPoolSize * 6), [streakPoolSize]);

  const streakGeo = useMemo(() => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(streakPositions, 3));
    return geo;
  }, [streakPositions]);

  const streakMat = useMemo(() => new THREE.LineBasicMaterial({
    color: '#F3F0E8',
    transparent: true,
    opacity: 0.3,
    depthWrite: false,
  }), []);

  const streakLinesRef = useRef<THREE.LineSegments>(null);

  // -- L5: Vignette ----------------------------------------------
  const vignetteUniforms = useMemo(() => ({
    uRadius: { value: background.vignetteRadius },
    uShift: { value: new THREE.Vector2(0, 0) },
  }), []);

  const vignetteMaterial = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: vignetteVertex,
    fragmentShader: vignetteFragment,
    uniforms: vignetteUniforms,
    transparent: true,
    depthWrite: false,
    depthTest: false,
  }), [vignetteUniforms]);

  // -- Animation -------------------------------------------------
  useFrame((_, delta) => {
    const state = useKernelStore.getState();
    const { trackPath, scrollVelocity, pointerX, pointerY, drs } = state;

    if (reducedMotion) return;

    // Grain time
    grainUniforms.uTime.value += delta;

    // Particles: drift + pointer attraction
    if (particlesRef.current && particleCount > 0) {
      const posArray = particlesRef.current.geometry.attributes.position.array as Float32Array;
      const cornerBoost = trackPath.isCorner ? background.cornerParticleDriftMultiplier : 1.0;
      const lateralDrift = trackPath.headingDelta * background.particleDriftX * delta * cornerBoost;
      const verticalDrift = scrollVelocity * background.particleDriftY * delta;

      const pWorldX = (pointerX - 0.5) * 20;
      const pWorldY = (pointerY - 0.5) * 20;
      const attractRadius = background.particlePointerRadius / (size.width || 1) * 20;

      for (let i = 0; i < particleCount; i++) {
        const ix = i * 3;
        const iy = ix + 1;
        posArray[ix] += lateralDrift;
        posArray[iy] += verticalDrift;

        const dx = pWorldX - posArray[ix];
        const dy = pWorldY - posArray[iy];
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < attractRadius && dist > 0.01) {
          const force = (1 - dist / attractRadius) * 0.02;
          posArray[ix] += dx * force;
          posArray[iy] += dy * force;
        }

        if (posArray[ix] > 10) posArray[ix] = -10;
        if (posArray[ix] < -10) posArray[ix] = 10;
        if (posArray[iy] > 10) posArray[iy] = -10;
        if (posArray[iy] < -10) posArray[iy] = 10;
      }
      particlesRef.current.geometry.attributes.position.needsUpdate = true;
    }

    // Streaks: spawn + age (DRS modulates threshold)
    if (isHigh && streakLinesRef.current) {
      const pool = streakPool.current;
      const lifetime = background.streakLifetime;
      const halfLen = background.streakLength / (size.width || 1) * 10;
      const heading = trackPath.heading;

      const threshold = drs.active
        ? background.streakSpawnThreshold * (1 - background.streakDrsThresholdReduction)
        : background.streakSpawnThreshold;

      if (Math.abs(scrollVelocity) > threshold) {
        for (let i = 0; i < pool.length; i++) {
          if (!pool[i].alive) {
            pool[i].alive = true;
            pool[i].age = 0;
            pool[i].x = (Math.random() - 0.5) * 16;
            pool[i].y = (Math.random() - 0.5) * 16;
            pool[i].heading = heading;
            break;
          }
        }
      }

      for (let i = 0; i < pool.length; i++) {
        const s = pool[i];
        const base = i * 6;
        if (s.alive) {
          s.age += delta * 1000;
          if (s.age > lifetime) s.alive = false;
        }
        if (s.alive) {
          const cosH = Math.cos(s.heading);
          const sinH = Math.sin(s.heading);
          streakPositions[base] = s.x - cosH * halfLen;
          streakPositions[base + 1] = s.y - sinH * halfLen;
          streakPositions[base + 2] = 0;
          streakPositions[base + 3] = s.x + cosH * halfLen;
          streakPositions[base + 4] = s.y + sinH * halfLen;
          streakPositions[base + 5] = 0;
        } else {
          for (let j = 0; j < 6; j++) streakPositions[base + j] = 0;
        }
      }
      streakGeo.attributes.position.needsUpdate = true;
      const vel = Math.abs(scrollVelocity);
      streakMat.opacity = Math.min(0.5, (vel - threshold) * 0.8);
    }

    // Vignette shift toward corner apex
    if (trackPath.isCorner) {
      _vignetteTarget.set(
        Math.sin(trackPath.heading) * background.vignetteShift,
        -Math.cos(trackPath.heading) * background.vignetteShift,
      );
      vignetteUniforms.uShift.value.lerp(_vignetteTarget, 0.05);
    } else {
      vignetteUniforms.uShift.value.lerp(_vignetteCenter, 0.03);
    }
  });

  // -- Cleanup ---------------------------------------------------
  useEffect(() => {
    return () => {
      grainMaterial.dispose();
      vignetteMaterial.dispose();
      streakGeo.dispose();
      streakMat.dispose();
    };
  }, [grainMaterial, vignetteMaterial, streakGeo, streakMat]);

  return (
    <group renderOrder={-100}>
      {/* L1: Grain */}
      <mesh renderOrder={-99}>
        <planeGeometry args={[50, 50]} />
        <primitive object={grainMaterial} attach="material" />
      </mesh>

      {/* L3: Particles */}
      {particleCount > 0 && (
        <points ref={particlesRef} renderOrder={-97}>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[particlePositions, 3]} />
          </bufferGeometry>
          <pointsMaterial
            size={0.03}
            color="#F3F0E8"
            transparent
            opacity={0.25}
            sizeAttenuation
            depthWrite={false}
          />
        </points>
      )}

      {/* L4: Speed streaks */}
      {isHigh && (
        <lineSegments
          ref={streakLinesRef}
          geometry={streakGeo}
          material={streakMat}
          renderOrder={-96}
        />
      )}

      {/* L5: Vignette */}
      <mesh renderOrder={-95}>
        <planeGeometry args={[50, 50]} />
        <primitive object={vignetteMaterial} attach="material" />
      </mesh>
    </group>
  );
}
