/**
 * Nice tick generation.
 *
 * Produces a small set of human-readable tick values within a domain.
 * Same algorithm used everywhere → consistent label density across charts.
 */

/**
 * Generate ~`targetCount` "nice" ticks between `min` and `max`.
 *
 * Step is rounded to 1, 2, 5 × 10ⁿ so labels stay readable
 * (e.g. 0, 50, 100, 150 instead of 0, 33.33, 66.67, 100).
 */
export function niceTicks(
  min: number,
  max: number,
  targetCount: number = 6,
): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [min];
  if (min > max) [min, max] = [max, min];

  const range = max - min;
  const roughStep = range / Math.max(1, targetCount);
  const magnitude = Math.pow(10, Math.floor(Math.log10(roughStep)));
  const residual = roughStep / magnitude;

  let niceStep: number;
  if (residual <= 1.5) niceStep = 1;
  else if (residual <= 3) niceStep = 2;
  else if (residual <= 7) niceStep = 5;
  else niceStep = 10;
  niceStep *= magnitude;

  const ticks: number[] = [];
  const start = Math.ceil(min / niceStep) * niceStep;
  for (let v = start; v <= max + niceStep * 1e-9; v += niceStep) {
    // Snap to avoid floating-point drift like 0.30000000000000004
    ticks.push(Math.round(v / niceStep) * niceStep);
  }
  return ticks;
}

/**
 * Generate symmetric ticks around zero spanning [-halfExtent, +halfExtent].
 * Used by delta charts where zero must be a visual center.
 */
export function niceSymmetricTicks(halfExtent: number, targetCount: number = 4): number[] {
  const ticks = niceTicks(0, halfExtent, targetCount);
  return [...ticks.slice(1).map((t) => -t).reverse(), ...ticks];
}

/**
 * How many decimal places this step size needs to render cleanly.
 * Used to format tick labels consistently within a single axis.
 */
export function decimalsForStep(step: number): number {
  if (step >= 1) return 0;
  if (step >= 0.1) return 1;
  if (step >= 0.01) return 2;
  if (step >= 0.001) return 3;
  return 4;
}
