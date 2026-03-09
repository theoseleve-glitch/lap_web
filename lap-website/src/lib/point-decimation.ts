/**
 * Point decimation utilities for rendering large GPS traces.
 *
 * Ramer-Douglas-Peucker (RDP) algorithm: reduces point count while
 * preserving the shape within a given tolerance (epsilon).
 */

/** Simple 2D point with optional index for back-referencing original data. */
interface Point {
  x: number;
  y: number;
  idx: number;
}

/**
 * Perpendicular distance from point P to line segment AB.
 */
function perpendicularDistance(p: Point, a: Point, b: Point): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) {
    // A and B are the same point
    return Math.sqrt((p.x - a.x) ** 2 + (p.y - a.y) ** 2);
  }
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq));
  const projX = a.x + t * dx;
  const projY = a.y + t * dy;
  return Math.sqrt((p.x - projX) ** 2 + (p.y - projY) ** 2);
}

/**
 * Ramer-Douglas-Peucker line simplification.
 *
 * Returns indices into the original array that should be kept.
 * Epsilon is in the same units as the coordinates (pixels or degrees).
 */
function rdpIndices(points: Point[], epsilon: number): number[] {
  if (points.length <= 2) {
    return points.map((p) => p.idx);
  }

  const first = points[0]!;
  const last = points[points.length - 1]!;

  let maxDist = 0;
  let maxIdx = 0;

  for (let i = 1; i < points.length - 1; i++) {
    const dist = perpendicularDistance(points[i]!, first, last);
    if (dist > maxDist) {
      maxDist = dist;
      maxIdx = i;
    }
  }

  if (maxDist > epsilon) {
    const left = rdpIndices(points.slice(0, maxIdx + 1), epsilon);
    const right = rdpIndices(points.slice(maxIdx), epsilon);
    // Merge, avoiding duplicate at split point
    return [...left, ...right.slice(1)];
  }

  return [first.idx, last.idx];
}

/**
 * Decimate parallel arrays of lat/lon (or x/y) using RDP.
 *
 * @param xs - X coordinates (latitudes or pixel x)
 * @param ys - Y coordinates (longitudes or pixel y)
 * @param epsilon - Tolerance (smaller = more points kept). Try 0.5-2 for pixels.
 * @returns Sorted array of indices to keep from the original arrays.
 */
export function decimatePoints(xs: number[], ys: number[], epsilon: number): number[] {
  const n = Math.min(xs.length, ys.length);
  if (n <= 2) return Array.from({ length: n }, (_, i) => i);

  const points: Point[] = [];
  for (let i = 0; i < n; i++) {
    points.push({ x: xs[i]!, y: ys[i]!, idx: i });
  }

  return rdpIndices(points, epsilon).sort((a, b) => a - b);
}

/**
 * Quick uniform sampling — keeps every Nth point.
 * Much faster than RDP but doesn't preserve shape as well.
 */
export function uniformSample(length: number, maxPoints: number): number[] {
  if (length <= maxPoints) return Array.from({ length }, (_, i) => i);
  const step = length / maxPoints;
  const indices: number[] = [];
  for (let i = 0; i < maxPoints; i++) {
    indices.push(Math.round(i * step));
  }
  // Always include last point
  if (indices[indices.length - 1] !== length - 1) {
    indices.push(length - 1);
  }
  return indices;
}
