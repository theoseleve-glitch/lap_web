/**
 * Linear scale utilities.
 *
 * A scale maps a domain value (e.g. distance in meters) to a pixel position
 * inside the plot area, and back. Every chart that maps continuous values
 * to canvas coordinates uses these — no chart should compute its own
 * `(v - min) / (max - min) * width` math.
 */

export interface LinearScale {
  /** Domain extent the scale was built from. */
  readonly domain: readonly [number, number];
  /** Pixel range the scale was built from. */
  readonly range: readonly [number, number];
  /** Map a domain value → pixel position. */
  toPixel(v: number): number;
  /** Map a pixel position → domain value. */
  fromPixel(px: number): number;
}

/**
 * Create a linear scale from a domain to a pixel range.
 *
 * Range is given as `[start, end]` — for a Y-axis where 0 is at the bottom
 * of the plot and max is at the top, pass `[plotBottom, plotTop]` so the
 * inversion is built in.
 *
 * Degenerate domains (min === max) collapse to the midpoint of the range.
 */
export function createLinearScale(
  domain: readonly [number, number],
  range: readonly [number, number],
): LinearScale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const dSpan = d1 - d0;
  const rSpan = r1 - r0;

  if (dSpan === 0) {
    const mid = (r0 + r1) / 2;
    return {
      domain,
      range,
      toPixel: () => mid,
      fromPixel: () => d0,
    };
  }

  return {
    domain,
    range,
    toPixel: (v: number) => r0 + ((v - d0) / dSpan) * rSpan,
    fromPixel: (px: number) => d0 + ((px - r0) / rSpan) * dSpan,
  };
}

/**
 * Symmetric scale around zero — useful for delta/error charts where the
 * Y-axis must be balanced visually around zero. The provided value defines
 * the half-extent.
 */
export function createSymmetricScale(
  halfExtent: number,
  range: readonly [number, number],
): LinearScale {
  const abs = Math.max(Math.abs(halfExtent), 1e-9);
  return createLinearScale([-abs, abs], range);
}

/**
 * Find the closest index in a sorted array — binary search.
 * Used by every hover handler to map pointer x → data index.
 */
export function closestIndex(sortedValues: readonly number[], target: number): number {
  if (sortedValues.length === 0) return -1;
  let lo = 0;
  let hi = sortedValues.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (sortedValues[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs(sortedValues[lo - 1] - target) < Math.abs(sortedValues[lo] - target)) {
    return lo - 1;
  }
  return lo;
}
