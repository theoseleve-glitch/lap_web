'use client';

import { Canvas, useFrame } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import * as THREE from 'three';
import {
  buildRibbonGeometry,
  buildTrackCurve,
  sampleTrack,
  type TrackSample,
} from '@/experience/background/trackGeometry';
import styles from './Lap3DConceptV2.module.css';

interface Lap3DWorldProps {
  progress: number;
  activeIndex: number;
  reducedMotion: boolean;
}

const BEAT_TRACK_T = [0.02, 0.18, 0.36, 0.56, 0.78, 0.96] as const;

function clamp01(value: number) {
  return Math.max(0, Math.min(1, value));
}

function getSampleAtT(samples: TrackSample[], trackT: number) {
  const safeT = clamp01(trackT);
  const index = Math.round(safeT * (samples.length - 1));
  return samples[index] ?? samples[0];
}

function WorldScene({ progress, activeIndex, reducedMotion }: Lap3DWorldProps) {
  const rigRef = useRef(new THREE.Object3D());
  const lookRef = useRef(new THREE.Vector3(0, 0, 0));
  const pulseRef = useRef<THREE.Mesh>(null);
  const accentLightRef = useRef<THREE.PointLight>(null);

  const { curve, samples, trackGeometry, edgeGeometry, lineGeometry, telemetryGeometry } =
    useMemo(() => {
      const nextCurve = buildTrackCurve();
      const nextSamples = sampleTrack(nextCurve, 360);

      const telemetry = new Float32Array(96 * 3);
      for (let i = 0; i < 96; i += 1) {
        const sample = nextSamples[(i * 3) % nextSamples.length] ?? nextSamples[0];
        const lateral = ((i % 6) - 2.5) * 0.18;
        const lift = 0.08 + (i % 4) * 0.11;
        const drift = Math.sin(i * 0.58) * 0.12;
        const point = sample.position
          .clone()
          .add(sample.normal.clone().multiplyScalar(lateral))
          .add(sample.binormal.clone().multiplyScalar(lift))
          .add(sample.tangent.clone().multiplyScalar(drift));

        telemetry[i * 3] = point.x;
        telemetry[i * 3 + 1] = point.y;
        telemetry[i * 3 + 2] = point.z;
      }

      const telemetryGeometry = new THREE.BufferGeometry();
      telemetryGeometry.setAttribute('position', new THREE.BufferAttribute(telemetry, 3));

      return {
        curve: nextCurve,
        samples: nextSamples,
        trackGeometry: buildRibbonGeometry(nextSamples, 1.18),
        edgeGeometry: buildRibbonGeometry(nextSamples, 1.5),
        lineGeometry: buildRibbonGeometry(nextSamples, 0.12),
        telemetryGeometry,
      };
    }, []);

  useFrame((state, delta) => {
    const smoothedProgress = reducedMotion
      ? 0.12 + clamp01(progress) * 0.16
      : THREE.MathUtils.smootherstep(clamp01(progress), 0, 1);
    const trackT = THREE.MathUtils.lerp(0.025, 0.985, smoothedProgress);

    const current = getSampleAtT(samples, trackT);
    const ahead = getSampleAtT(samples, Math.min(trackT + 0.035, 0.999));
    const cameraPos = current.position
      .clone()
      .add(current.tangent.clone().multiplyScalar(-1.7))
      .add(current.normal.clone().multiplyScalar(0.56 + activeIndex * 0.04))
      .add(current.binormal.clone().multiplyScalar(1.16));
    const lookAt = ahead.position
      .clone()
      .add(ahead.normal.clone().multiplyScalar(0.05))
      .add(ahead.binormal.clone().multiplyScalar(0.08));
    const damping = 1 - Math.exp(-delta * (reducedMotion ? 6.5 : 3.8));

    state.camera.position.lerp(cameraPos, damping);
    lookRef.current.lerp(lookAt, damping);

    rigRef.current.position.copy(state.camera.position);
    rigRef.current.up.copy(current.binormal);
    rigRef.current.lookAt(lookRef.current);
    rigRef.current.rotateZ(THREE.MathUtils.clamp(current.curvature * 0.018, -0.09, 0.09));
    state.camera.quaternion.slerp(rigRef.current.quaternion, damping);

    if (pulseRef.current) {
      pulseRef.current.position.copy(current.position).add(current.binormal.clone().multiplyScalar(0.09));
      const pulseScale = 0.1 + Math.sin(state.clock.elapsedTime * 3.4) * 0.02;
      pulseRef.current.scale.setScalar(pulseScale + activeIndex * 0.006);
    }

    if (accentLightRef.current) {
      accentLightRef.current.position.copy(current.position).add(current.binormal.clone().multiplyScalar(1.3));
      accentLightRef.current.intensity = 0.85 + activeIndex * 0.14;
    }
  });

  return (
    <>
      <color attach="background" args={['#040404']} />
      <fog attach="fog" args={['#040404', 5.2, 18]} />
      <ambientLight color="#d8d2cb" intensity={0.24} />
      <directionalLight position={[4, 5, 6]} color="#f6f1ea" intensity={1.18} />
      <pointLight
        ref={accentLightRef}
        color="#b9362d"
        intensity={0.9}
        distance={5.5}
        decay={2}
      />

      <group scale={1.32} position={[0, 0, -0.2]}>
        <mesh geometry={edgeGeometry} frustumCulled={false}>
          <meshBasicMaterial
            color="#82261f"
            transparent
            opacity={0.18}
            blending={THREE.AdditiveBlending}
            depthWrite={false}
            side={THREE.DoubleSide}
          />
        </mesh>

        <mesh geometry={trackGeometry} frustumCulled={false}>
          <meshStandardMaterial
            color="#08090a"
            emissive="#070707"
            emissiveIntensity={0.32}
            roughness={0.88}
            metalness={0.28}
            side={THREE.DoubleSide}
          />
        </mesh>

        <mesh geometry={lineGeometry} position={[0, 0, 0.02]} frustumCulled={false}>
          <meshBasicMaterial
            color="#eae2d8"
            transparent
            opacity={0.84}
            depthWrite={false}
            side={THREE.DoubleSide}
          />
        </mesh>

        <mesh geometry={lineGeometry} position={[0, 0, 0.04]} frustumCulled={false}>
          <meshBasicMaterial
            color="#b9362d"
            transparent
            opacity={0.32}
            blending={THREE.AdditiveBlending}
            depthWrite={false}
            side={THREE.DoubleSide}
          />
        </mesh>

        <points geometry={telemetryGeometry}>
          <pointsMaterial
            color="#f0ede5"
            size={0.04}
            transparent
            opacity={0.46}
            depthWrite={false}
            sizeAttenuation
          />
        </points>

        {BEAT_TRACK_T.map((trackT, index) => {
          const sample = getSampleAtT(samples, trackT);
          const isActive = index === activeIndex;
          const beaconScale = isActive ? 0.12 : 0.08;

          return (
            <group
              key={trackT}
              position={[
                sample.position.x,
                sample.position.y,
                sample.position.z + 0.1,
              ]}
            >
              <mesh scale={beaconScale}>
                <sphereGeometry args={[1, 18, 18]} />
                <meshBasicMaterial
                  color={isActive ? '#f4ede4' : '#a39089'}
                  transparent
                  opacity={isActive ? 0.95 : 0.38}
                />
              </mesh>
              <mesh position={[0, 0, -0.03]} scale={isActive ? 0.34 : 0.24}>
                <sphereGeometry args={[1, 18, 18]} />
                <meshBasicMaterial
                  color="#b9362d"
                  transparent
                  opacity={isActive ? 0.22 : 0.1}
                  blending={THREE.AdditiveBlending}
                />
              </mesh>
            </group>
          );
        })}

        <mesh ref={pulseRef}>
          <sphereGeometry args={[1, 20, 20]} />
          <meshBasicMaterial
            color="#f7f1e8"
            transparent
            opacity={0.9}
            blending={THREE.AdditiveBlending}
          />
        </mesh>
      </group>
    </>
  );
}

export function Lap3DWorld(props: Lap3DWorldProps) {
  return (
    <div className={styles.worldShell} aria-hidden="true">
      <Canvas
        className={styles.worldCanvas}
        dpr={props.reducedMotion ? [1, 1] : [1, 1.6]}
        camera={{ position: [0, 0, 6], fov: 42, near: 0.1, far: 100 }}
        gl={{
          alpha: true,
          antialias: !props.reducedMotion,
          stencil: false,
          powerPreference: 'high-performance',
        }}
      >
        <WorldScene {...props} />
      </Canvas>
    </div>
  );
}
