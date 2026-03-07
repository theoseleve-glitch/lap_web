// Pure math module: builds the track bezier curve, samples it, and generates ribbon geometry.
// No React — consumed by TrackRibbon (R3F) and BackgroundController (DOM).

import * as THREE from 'three';

// ── Types ──────────────────────────────────────

export interface TrackSample {
  position: THREE.Vector3;
  tangent: THREE.Vector3;
  normal: THREE.Vector3;
  binormal: THREE.Vector3;
  curvature: number;
  t: number; // 0→1 along the track
}

// ── Track curve ────────────────────────────────

// 18 control points forming the narrative track layout.
// Coordinate space: XY plane ≈ [-6,6]×[-4,4], Z = subtle depth ±0.3
// Corners at chapters 1,3,5,7 (high curvature), straights at 0,2,4,6,9,10, pit at 8.
const CONTROL_POINTS: [number, number, number][] = [
  // Start/finish straight (chapter 0)
  [-5.5,  3.2,  0.0],
  [-3.0,  3.5,  0.1],
  // Turn 1 — chapter 1 (pain point)
  [-0.5,  3.8,  0.2],
  [ 1.8,  3.0,  0.3],
  // Back straight — chapter 2
  [ 3.5,  1.8,  0.2],
  [ 4.8,  0.2,  0.1],
  // Turn 2 — chapter 3 (pipeline)
  [ 5.2, -1.5,  0.0],
  [ 4.0, -2.8, -0.1],
  // Mid straight — chapter 4
  [ 2.0, -3.2, -0.2],
  [ 0.0, -3.5, -0.3],
  // Turn 3 — chapter 5 (product)
  [-2.0, -3.0, -0.2],
  [-3.8, -2.0, -0.1],
  // Return straight — chapter 6
  [-4.8, -0.5,  0.0],
  [-5.2,  0.8,  0.1],
  // Turn 4 — chapter 7 (personas)
  [-5.5,  2.0,  0.2],
  [-5.8,  1.0,  0.1],
  // Pit lane — chapter 8
  [-5.0,  1.8,  0.0],
  // Final approach — chapters 9,10 (garage, podium)
  [-5.8,  2.8,  0.1],
];

export function buildTrackCurve(): THREE.CatmullRomCurve3 {
  const points = CONTROL_POINTS.map(([x, y, z]) => new THREE.Vector3(x, y, z));
  return new THREE.CatmullRomCurve3(points, true, 'centripetal', 0.5);
}

// ── Sampling ───────────────────────────────────

export function sampleTrack(curve: THREE.CatmullRomCurve3, segments: number): TrackSample[] {
  const samples: TrackSample[] = [];
  const up = new THREE.Vector3(0, 0, 1);
  const epsilon = 0.001;

  for (let i = 0; i <= segments; i++) {
    const t = i / segments;
    const position = curve.getPointAt(t);
    const tangent = curve.getTangentAt(t).normalize();

    // Normal: perpendicular to tangent in the XY plane (cross with Z-up)
    const normal = new THREE.Vector3().crossVectors(tangent, up).normalize();
    const binormal = new THREE.Vector3().crossVectors(normal, tangent).normalize();

    // Curvature via finite differences on tangent vectors
    const tPrev = Math.max(0, t - epsilon);
    const tNext = Math.min(1, t + epsilon);
    const tanPrev = curve.getTangentAt(tPrev).normalize();
    const tanNext = curve.getTangentAt(tNext).normalize();
    const dTangent = new THREE.Vector3().subVectors(tanNext, tanPrev);
    const curvature = dTangent.length() / (2 * epsilon);

    // Sign: positive = turning left (cross product Z component)
    const cross = new THREE.Vector3().crossVectors(tanPrev, tanNext);
    const signedCurvature = Math.sign(cross.z) * curvature;

    samples.push({ position, tangent, normal, binormal, curvature: signedCurvature, t });
  }

  return samples;
}

// ── Ribbon geometry ────────────────────────────

export function buildRibbonGeometry(
  samples: TrackSample[],
  width: number
): THREE.BufferGeometry {
  const count = samples.length;
  const vertCount = count * 2;
  const triCount = (count - 1) * 2;
  const halfW = width / 2;

  const positions = new Float32Array(vertCount * 3);
  const normals = new Float32Array(vertCount * 3);
  const uvs = new Float32Array(vertCount * 2);
  const tangents = new Float32Array(vertCount * 4);
  const curvatures = new Float32Array(vertCount);
  const trackTs = new Float32Array(vertCount);
  const indices = new Uint32Array(triCount * 3);

  for (let i = 0; i < count; i++) {
    const s = samples[i]!;
    const offset = new THREE.Vector3().copy(s.normal).multiplyScalar(halfW);
    const leftPos = new THREE.Vector3().copy(s.position).sub(offset);
    const rightPos = new THREE.Vector3().copy(s.position).add(offset);

    const li = i * 2;
    const ri = i * 2 + 1;

    // Positions
    positions[li * 3]     = leftPos.x;
    positions[li * 3 + 1] = leftPos.y;
    positions[li * 3 + 2] = leftPos.z;
    positions[ri * 3]     = rightPos.x;
    positions[ri * 3 + 1] = rightPos.y;
    positions[ri * 3 + 2] = rightPos.z;

    // Normals (face up / toward camera)
    normals[li * 3]     = s.binormal.x;
    normals[li * 3 + 1] = s.binormal.y;
    normals[li * 3 + 2] = s.binormal.z;
    normals[ri * 3]     = s.binormal.x;
    normals[ri * 3 + 1] = s.binormal.y;
    normals[ri * 3 + 2] = s.binormal.z;

    // UVs: x = across (0=left, 1=right), y = along track (t)
    uvs[li * 2]     = 0.0;
    uvs[li * 2 + 1] = s.t;
    uvs[ri * 2]     = 1.0;
    uvs[ri * 2 + 1] = s.t;

    // Tangent as vec4 (w = handedness, always 1.0 here)
    tangents[li * 4]     = s.tangent.x;
    tangents[li * 4 + 1] = s.tangent.y;
    tangents[li * 4 + 2] = s.tangent.z;
    tangents[li * 4 + 3] = 1.0;
    tangents[ri * 4]     = s.tangent.x;
    tangents[ri * 4 + 1] = s.tangent.y;
    tangents[ri * 4 + 2] = s.tangent.z;
    tangents[ri * 4 + 3] = 1.0;

    // Custom attributes
    curvatures[li] = s.curvature;
    curvatures[ri] = s.curvature;
    trackTs[li] = s.t;
    trackTs[ri] = s.t;
  }

  // Indices: quad strip → two triangles per quad
  for (let i = 0; i < count - 1; i++) {
    const bl = i * 2;       // bottom-left
    const br = i * 2 + 1;   // bottom-right
    const tl = (i + 1) * 2;     // top-left
    const tr = (i + 1) * 2 + 1; // top-right

    const ti = i * 6;
    indices[ti]     = bl;
    indices[ti + 1] = br;
    indices[ti + 2] = tl;
    indices[ti + 3] = br;
    indices[ti + 4] = tr;
    indices[ti + 5] = tl;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setIndex(new THREE.BufferAttribute(indices, 1));
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('normal', new THREE.BufferAttribute(normals, 3));
  geometry.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
  geometry.setAttribute('tangent', new THREE.BufferAttribute(tangents, 4));
  geometry.setAttribute('aCurvature', new THREE.BufferAttribute(curvatures, 1));
  geometry.setAttribute('aTrackT', new THREE.BufferAttribute(trackTs, 1));

  return geometry;
}

// ── Corner values from curvature ───────────────

const CURVATURE_DEAD_ZONE = 0.03;
const YAW_SCALE = 3.0;   // matches springs.cornerYawRange
const BANK_SCALE = 1.5;  // matches springs.cornerBankRange

export function computeCornerValues(curvature: number): { yaw: number; bank: number } {
  const absCurv = Math.abs(curvature);
  if (absCurv < CURVATURE_DEAD_ZONE) {
    return { yaw: 0, bank: 0 };
  }
  const sign = Math.sign(curvature);
  const magnitude = Math.min((absCurv - CURVATURE_DEAD_ZONE) * 10, 1);
  return {
    yaw: sign * magnitude * YAW_SCALE,
    bank: sign * magnitude * BANK_SCALE,
  };
}

// ── Scroll-to-track mapping ────────────────────

// Non-linear mapping: corners get more track length (more scroll time at interesting parts).
// 11 chapters → 18 control points → track t ∈ [0,1]
const CHAPTER_TRACK_T: number[] = [
  0.00,  // ch0: start grid
  0.08,  // ch1: turn 1 (wider range)
  0.18,  // ch2: back straight
  0.30,  // ch3: turn 2 (wider range)
  0.42,  // ch4: mid straight
  0.52,  // ch5: turn 3 (wider range)
  0.64,  // ch6: return straight
  0.74,  // ch7: turn 4 (wider range)
  0.82,  // ch8: pit lane
  0.90,  // ch9: garage
  0.98,  // ch10: podium
];

export function scrollToTrackT(globalProgress: number, currentChapter: number): number {
  const chapterCount = CHAPTER_TRACK_T.length;
  const clampedChapter = Math.max(0, Math.min(chapterCount - 1, currentChapter));
  const nextChapter = Math.min(clampedChapter + 1, chapterCount - 1);

  const chapterStart = CHAPTER_TRACK_T[clampedChapter] ?? 0;
  const chapterEnd = CHAPTER_TRACK_T[nextChapter] ?? 1;

  // Fractional progress within the current chapter
  const chapterWidth = 1 / (chapterCount - 1);
  const chapterLocalProgress = clampedChapter < chapterCount - 1
    ? (globalProgress - clampedChapter * chapterWidth) / chapterWidth
    : 1;

  const localClamped = Math.max(0, Math.min(1, chapterLocalProgress));
  return chapterStart + (chapterEnd - chapterStart) * localClamped;
}

// ── Utility: find curvature at a given trackT from pre-computed samples ──

export function curvatureAtT(samples: TrackSample[], trackT: number): number {
  if (samples.length === 0) return 0;
  const t = Math.max(0, Math.min(1, trackT));
  const idx = t * (samples.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.min(lo + 1, samples.length - 1);
  const frac = idx - lo;
  const loSample = samples[lo];
  const hiSample = samples[hi];
  if (!loSample || !hiSample) return 0;
  return loSample.curvature * (1 - frac) + hiSample.curvature * frac;
}
