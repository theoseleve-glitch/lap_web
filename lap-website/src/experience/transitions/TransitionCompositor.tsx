'use client';

import { useRef, useEffect, useState, useCallback } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { useFBO } from '@react-three/drei';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { getTransitionType } from './TransitionLibrary';
import { crossfadeBlurFragment, crossfadeBlurVertex } from './shaders/crossfade-blur';
import { maskWipeFragment, maskWipeVertex } from './shaders/mask-wipe';
import { velocityWarpFragment, velocityWarpVertex } from './shaders/velocity-warp';
import { refractionFragment, refractionVertex } from './shaders/refraction';
import { rooms, timing } from '@/lib/tokens';

const SHADERS: Record<string, { vertex: string; fragment: string }> = {
  'crossfade-blur': { vertex: crossfadeBlurVertex, fragment: crossfadeBlurFragment },
  'mask-wipe': { vertex: maskWipeVertex, fragment: maskWipeFragment },
  'velocity-warp': { vertex: velocityWarpVertex, fragment: velocityWarpFragment },
  'refraction': { vertex: refractionVertex, fragment: refractionFragment },
};

export function TransitionCompositor() {
  const { gl, scene, camera } = useThree();
  const fboFrom = useFBO();
  const [transitioning, setTransitioning] = useState(false);
  const progressRef = useRef(0);
  const prevChapterRef = useRef(0);
  const materialRef = useRef<THREE.ShaderMaterial | null>(null);

  const currentChapter = useKernelStore((s) => s.currentChapter);
  const scrollVelocity = useKernelStore((s) => s.scrollVelocity);
  const setMode = useKernelStore((s) => s.setMode);

  const startTransition = useCallback(() => {
    // Capture current scene to FBO
    gl.setRenderTarget(fboFrom);
    gl.render(scene, camera);
    gl.setRenderTarget(null);

    progressRef.current = 0;
    setTransitioning(true);
    setMode('transitioning');
  }, [gl, scene, camera, fboFrom, setMode]);

  // Detect chapter changes
  useEffect(() => {
    if (currentChapter !== prevChapterRef.current) {
      startTransition();
      prevChapterRef.current = currentChapter;
    }
  }, [currentChapter, startTransition]);

  useFrame((_, delta) => {
    if (!transitioning || !materialRef.current) return;

    progressRef.current += delta / timing.room;

    if (progressRef.current >= 1) {
      progressRef.current = 1;
      setTransitioning(false);
      setMode('idle');
    }

    materialRef.current.uniforms.uProgress.value = progressRef.current;
    materialRef.current.uniforms.uTime.value += delta;
    if (materialRef.current.uniforms.uVelocity) {
      materialRef.current.uniforms.uVelocity.value = scrollVelocity;
    }
  });

  if (!transitioning) return null;

  const fromId = rooms[prevChapterRef.current]?.id ?? 'start-grid';
  const toId = rooms[currentChapter]?.id ?? 'start-grid';
  const type = getTransitionType(fromId, toId);
  const shader = SHADERS[type] ?? SHADERS['crossfade-blur'];

  return (
    <mesh renderOrder={999}>
      <planeGeometry args={[2, 2]} />
      <shaderMaterial
        ref={materialRef}
        vertexShader={shader.vertex}
        fragmentShader={shader.fragment}
        uniforms={{
          tFrom: { value: fboFrom.texture },
          tTo: { value: null },
          uProgress: { value: 0 },
          uVelocity: { value: 0 },
          uTime: { value: 0 },
          uAccentColor: { value: new THREE.Color('#F3F0E8') },
        }}
        transparent
        depthTest={false}
        depthWrite={false}
      />
    </mesh>
  );
}
