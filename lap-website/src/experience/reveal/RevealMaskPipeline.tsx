'use client';

import { useRef, useMemo, useEffect } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { useFBO } from '@react-three/drei';
import * as THREE from 'three';
import { useKernelStore } from '@/experience/state/store';
import { useRevealState, computeMaskResolution } from './useRevealState';
import { reveal as revealPhysics } from '@/experience/motion/springs';
import { maskStampVertex, maskStampFragment } from './shaders/mask-stamp';
import { maskDecayVertex, maskDecayFragment } from './shaders/mask-decay';
import { maskBlurVertex, maskBlurFragment } from './shaders/mask-blur';

/**
 * RevealMaskPipeline — FBO ping-pong system for persistent cursor reveal.
 *
 * Per-frame pipeline:
 * 1. STAMP: Soft brush at smoothed pointer -> maskFBO_A
 * 2. DECAY: maskFBO_A * decayFactor -> maskFBO_B
 * 3. BLUR:  separable Gaussian on maskFBO_B -> maskFBO_A (high tier only)
 * 4. Result stays in maskFBO_B (or maskFBO_A after blur)
 */
export function RevealMaskPipeline() {
  const { gl, size } = useThree();
  const qualityTier = useKernelStore((s) => s.qualityTier);
  const pointerX = useKernelStore((s) => s.pointerX);
  const pointerY = useKernelStore((s) => s.pointerY);
  const revealActive = useKernelStore((s) => s.reveal.active);
  const reducedMotion = useKernelStore((s) => s.reducedMotion);
  const setMaskCoverage = useKernelStore((s) => s.setMaskCoverage);
  const { getSmoothedPointer, getDecayFactor, getBrushRadius } = useRevealState();

  // Mobile touch burst refs
  const isTouchRef = useRef(false);
  const burstRef = useRef(false);

  // Detect touch device on first touchstart
  useEffect(() => {
    const onTouchStart = () => {
      isTouchRef.current = true;
    };
    window.addEventListener('touchstart', onTouchStart, { once: true, passive: true });
    return () => {
      window.removeEventListener('touchstart', onTouchStart);
    };
  }, []);

  // Trigger burst mode on touch pointer down/up
  useEffect(() => {
    let burstTimeout: ReturnType<typeof setTimeout>;

    const onPointerDown = () => {
      if (!isTouchRef.current) return;
      burstRef.current = true;
    };
    const onPointerUp = () => {
      if (!isTouchRef.current) return;
      burstTimeout = setTimeout(() => {
        burstRef.current = false;
      }, 100);
    };

    window.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointerup', onPointerUp);
    return () => {
      window.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointerup', onPointerUp);
      clearTimeout(burstTimeout);
    };
  }, []);

  const resolution = computeMaskResolution(qualityTier);

  // FBO ping-pong buffers for mask persistence
  const maskFboA = useFBO(resolution || 64, resolution || 64, {
    minFilter: THREE.LinearFilter,
    magFilter: THREE.LinearFilter,
    type: THREE.HalfFloatType,
  });
  const maskFboB = useFBO(resolution || 64, resolution || 64, {
    minFilter: THREE.LinearFilter,
    magFilter: THREE.LinearFilter,
    type: THREE.HalfFloatType,
  });

  // Full-screen quad scene for shader passes
  const quadScene = useMemo(() => new THREE.Scene(), []);
  const quadCamera = useMemo(
    () => new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1),
    [],
  );
  const quadGeo = useMemo(() => new THREE.PlaneGeometry(2, 2), []);

  // Shader materials
  const stampMat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: maskStampVertex,
        fragmentShader: maskStampFragment,
        uniforms: {
          tPrevMask: { value: null },
          uPointer: { value: new THREE.Vector2(0.5, 0.5) },
          uRadius: { value: 0.1 },
          uSoftness: { value: revealPhysics.brushSoftness },
          uStrength: { value: 1.0 },
        },
      }),
    [],
  );

  const decayMat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: maskDecayVertex,
        fragmentShader: maskDecayFragment,
        uniforms: {
          tMask: { value: null },
          uDecay: { value: revealPhysics.decayFactor },
        },
      }),
    [],
  );

  const blurMatH = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: maskBlurVertex,
        fragmentShader: maskBlurFragment,
        uniforms: {
          tMask: { value: null },
          uDirection: { value: new THREE.Vector2(1.0 / (resolution || 512), 0) },
          uSigma: { value: revealPhysics.blurSigma },
        },
      }),
    [resolution],
  );

  const blurMatV = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: maskBlurVertex,
        fragmentShader: maskBlurFragment,
        uniforms: {
          tMask: { value: null },
          uDirection: { value: new THREE.Vector2(0, 1.0 / (resolution || 512)) },
          uSigma: { value: revealPhysics.blurSigma },
        },
      }),
    [resolution],
  );

  // Reusable quad mesh for rendering passes
  const quadMesh = useMemo(() => {
    const mesh = new THREE.Mesh(quadGeo, stampMat);
    quadScene.add(mesh);
    return mesh;
  }, [quadGeo, stampMat, quadScene]);

  // Coverage sampling pixel buffer
  const coveragePixels = useMemo(
    () => new Float32Array(4),
    [],
  );

  useFrame(() => {
    if (!revealActive || resolution === 0) return;

    // 1. STAMP PASS: stamp brush at smoothed pointer
    const smoothed = getSmoothedPointer(pointerX, pointerY);
    const brushRadiusPx = getBrushRadius();
    const radiusPx = burstRef.current
      ? revealPhysics.mobileBurstRadius
      : brushRadiusPx;
    const brushRadiusUV = radiusPx / Math.max(size.width, size.height);

    stampMat.uniforms.tPrevMask.value = maskFboB.texture;
    stampMat.uniforms.uPointer.value.set(smoothed.x, 1.0 - smoothed.y); // flip Y for UV
    stampMat.uniforms.uRadius.value = brushRadiusUV;
    stampMat.uniforms.uStrength.value = reducedMotion ? 0.8 : 1.0;

    quadMesh.material = stampMat;
    gl.setRenderTarget(maskFboA);
    gl.render(quadScene, quadCamera);

    // 2. DECAY PASS: decay persistence (or instant clear for reduced motion)
    decayMat.uniforms.tMask.value = maskFboA.texture;
    decayMat.uniforms.uDecay.value = reducedMotion ? 0.0 : getDecayFactor();

    quadMesh.material = decayMat;
    gl.setRenderTarget(maskFboB);
    gl.render(quadScene, quadCamera);

    // 3. BLUR PASS (high tier only, skip for reduced motion): separable Gaussian
    if (qualityTier === 'high' && !reducedMotion) {
      // Horizontal
      blurMatH.uniforms.tMask.value = maskFboB.texture;
      quadMesh.material = blurMatH;
      gl.setRenderTarget(maskFboA);
      gl.render(quadScene, quadCamera);

      // Vertical
      blurMatV.uniforms.tMask.value = maskFboA.texture;
      quadMesh.material = blurMatV;
      gl.setRenderTarget(maskFboB);
      gl.render(quadScene, quadCamera);
    }

    gl.setRenderTarget(null);

    // Sample coverage (read single pixel from center for approximation)
    gl.setRenderTarget(maskFboB);
    gl.readRenderTargetPixels(maskFboB, resolution / 2, resolution / 2, 1, 1, coveragePixels);
    gl.setRenderTarget(null);
    setMaskCoverage(Math.min(1, coveragePixels[0] * 2)); // scale up center sample
  });

  return null;
}
