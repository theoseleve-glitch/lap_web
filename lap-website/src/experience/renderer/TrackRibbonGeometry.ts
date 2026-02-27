import * as THREE from 'three';
import type { ChapterPathConfig } from '@/experience/narrative/TrackPath';
import { background } from '@/experience/motion/springs';

const DEG2RAD = Math.PI / 180;
const STEP_SIZE = background.ribbonStepSize;

/** Total ribbon length in world units */
export const TOTAL_LENGTH = 100;

export interface RibbonPoint {
  x: number;
  y: number;
  z: number;
}

/**
 * Build an array of 3D points tracing the track ribbon from chapter headings.
 * Each chapter's heading defines the direction of travel in the XZ plane.
 * The ribbon is flat (Y=0).
 */
export function buildRibbonPoints(chapters: readonly ChapterPathConfig[]): RibbonPoint[] {
  const points: RibbonPoint[] = [];
  let x = 0;
  let z = 0;
  let currentHeading = 0;

  const chapterWeight = TOTAL_LENGTH / chapters.length;

  for (const chapter of chapters) {
    const segmentLength = chapterWeight;
    currentHeading += chapter.heading;
    const headingRad = currentHeading * DEG2RAD;
    const steps = Math.max(1, Math.ceil(segmentLength / STEP_SIZE));

    for (let i = 0; i < steps; i++) {
      x += Math.sin(headingRad) * STEP_SIZE;
      z += Math.cos(headingRad) * STEP_SIZE;
      points.push({ x, y: 0, z });
    }
  }

  return points;
}

/**
 * Build a Three.js CatmullRomCurve3 from the ribbon points.
 */
export function buildRibbonCurve(chapters: readonly ChapterPathConfig[]): THREE.CatmullRomCurve3 {
  const points = buildRibbonPoints(chapters);
  const vectors = points.map((p) => new THREE.Vector3(p.x, p.y, p.z));
  return new THREE.CatmullRomCurve3(vectors, false, 'catmullrom', 0.5);
}

/**
 * Extrude the ribbon curve into a flat mesh with given width.
 */
export function extrudeRibbonGeometry(
  curve: THREE.CatmullRomCurve3,
  width: number,
  segments: number = 200,
): THREE.BufferGeometry {
  const positions: number[] = [];
  const uvs: number[] = [];
  const indices: number[] = [];

  for (let i = 0; i <= segments; i++) {
    const t = i / segments;
    const point = curve.getPointAt(t);
    const tangent = curve.getTangentAt(t).normalize();

    const normal = new THREE.Vector3(-tangent.z, 0, tangent.x);
    const halfWidth = width / 2;

    positions.push(
      point.x - normal.x * halfWidth, point.y, point.z - normal.z * halfWidth,
    );
    positions.push(
      point.x + normal.x * halfWidth, point.y, point.z + normal.z * halfWidth,
    );

    uvs.push(0, t);
    uvs.push(1, t);

    if (i < segments) {
      const base = i * 2;
      indices.push(base, base + 1, base + 2);
      indices.push(base + 1, base + 3, base + 2);
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}
