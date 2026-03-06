/**
 * Color distribution modes for marble generation.
 *
 * Each mode maps a 2D coordinate to a scalar value in [0, 1]
 * which is then used against palette thresholds to select a color.
 *
 * All functions share the signature:
 *   (x, y, noiseFn, params) => number in [0, 1]
 *
 * where noiseFn is a 2D noise function (x, y) => [-1, 1]
 * and params is an optional object with mode-specific settings.
 */

/**
 * Fractional Brownian Motion helper.
 * Accumulates multiple octaves of noise with increasing frequency
 * and decreasing amplitude. Uses lacunarity 2.1379 to match
 * the project's noise.js convention and avoid tiling artifacts.
 *
 * @param {Function} noiseFn - 2D noise function returning [-1, 1]
 * @param {number} x
 * @param {number} y
 * @param {number} octaves
 * @param {number} freq - base frequency
 * @param {number} persistence - amplitude decay per octave
 * @returns {number} value in [-1, 1]
 */
function fbmSample(noiseFn, x, y, octaves, freq, persistence) {
  const lacunarity = 2.1379;
  let value = 0;
  let amplitude = 1;
  let maxAmplitude = 0;
  let f = freq;

  for (let i = 0; i < octaves; i++) {
    value += amplitude * noiseFn(x * f, y * f);
    maxAmplitude += amplitude;
    amplitude *= persistence;
    f *= lacunarity;
  }

  return value / maxAmplitude;
}

/**
 * Veined distribution -- FBM noise field producing organic vein patterns.
 * The noise output is mapped from [-1, 1] to [0, 1].
 *
 * @param {number} x - normalized x coordinate [0, 1]
 * @param {number} y - normalized y coordinate [0, 1]
 * @param {Function} noiseFn - 2D noise (x, y) => [-1, 1]
 * @param {object} [params]
 * @param {number} [params.frequency=1.5] - base noise frequency
 * @param {number} [params.octaves=5] - FBM octave count
 * @param {number} [params.persistence=0.5] - amplitude decay per octave
 * @returns {number} value in [0, 1]
 */
function veined(x, y, noiseFn, params = {}) {
  const frequency = params.frequency != null ? params.frequency : 1.5;
  const octaves = params.octaves != null ? params.octaves : 5;
  const persistence = params.persistence != null ? params.persistence : 0.5;

  const n = fbmSample(noiseFn, x, y, octaves, frequency, persistence);
  // Map from [-1, 1] to [0, 1]
  return n * 0.5 + 0.5;
}

/**
 * Radial distribution -- distance from a center point,
 * perturbed by noise for an organic feel.
 *
 * @param {number} x
 * @param {number} y
 * @param {Function} noiseFn
 * @param {object} [params]
 * @param {number} [params.centerX=0.5] - center x in [0, 1]
 * @param {number} [params.centerY=0.5] - center y in [0, 1]
 * @param {number} [params.noiseStrength=0.15] - how much noise perturbs the radius
 * @param {number} [params.frequency=2.0] - noise frequency
 * @returns {number} value in [0, 1]
 */
function radial(x, y, noiseFn, params = {}) {
  const cx = params.centerX != null ? params.centerX : 0.5;
  const cy = params.centerY != null ? params.centerY : 0.5;
  const noiseStrength = params.noiseStrength != null ? params.noiseStrength : 0.15;
  const frequency = params.frequency != null ? params.frequency : 2.0;

  const dx = x - cx;
  const dy = y - cy;
  // Maximum distance from center in a unit square is sqrt(0.5) ~ 0.707
  const dist = Math.sqrt(dx * dx + dy * dy) / 0.7071;

  const noise = noiseFn(x * frequency, y * frequency);
  const perturbed = dist + noise * noiseStrength;

  return Math.max(0, Math.min(1, perturbed));
}

/**
 * Linear distribution -- directional gradient at a given angle,
 * perturbed by noise for an organic feel.
 *
 * @param {number} x
 * @param {number} y
 * @param {Function} noiseFn
 * @param {object} [params]
 * @param {number} [params.angle=0] - gradient direction in degrees
 * @param {number} [params.noiseStrength=0.1] - noise perturbation amount
 * @param {number} [params.frequency=2.0] - noise frequency
 * @returns {number} value in [0, 1]
 */
function linear(x, y, noiseFn, params = {}) {
  const angleDeg = params.angle != null ? params.angle : 0;
  const noiseStrength = params.noiseStrength != null ? params.noiseStrength : 0.1;
  const frequency = params.frequency != null ? params.frequency : 2.0;

  const angleRad = (angleDeg * Math.PI) / 180;
  const dirX = Math.cos(angleRad);
  const dirY = Math.sin(angleRad);

  // Project position onto direction vector, centered at 0.5
  const projection = (x - 0.5) * dirX + (y - 0.5) * dirY;
  // Shift from [-0.5, 0.5] to [0, 1]
  const base = projection + 0.5;

  const noise = noiseFn(x * frequency, y * frequency);
  const perturbed = base + noise * noiseStrength;

  return Math.max(0, Math.min(1, perturbed));
}

/**
 * Simple deterministic pseudo-random number generator.
 * Returns values in [0, 1). Used for Voronoi point placement.
 *
 * @param {number} n - seed integer
 * @returns {number} pseudo-random value in [0, 1)
 */
function seededRandom(n) {
  // Mulberry32 variant
  let t = (n + 0x6D2B79F5) | 0;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}

/**
 * Clustered distribution -- Voronoi cells from deterministic
 * pseudo-random seed points. Returns the index of the closest
 * Voronoi cell normalized to [0, 1].
 *
 * @param {number} x
 * @param {number} y
 * @param {Function} noiseFn - unused but kept for uniform signature
 * @param {object} [params]
 * @param {number} [params.numPoints=20] - number of Voronoi sites
 * @param {number} [params.seed=42] - deterministic seed
 * @returns {number} value in [0, 1]
 */
function clustered(x, y, noiseFn, params = {}) {
  const numPoints = params.numPoints != null ? params.numPoints : 20;
  const seed = params.seed != null ? params.seed : 42;

  let minDist = Infinity;
  let closestIdx = 0;

  for (let i = 0; i < numPoints; i++) {
    const px = seededRandom(seed * 1000 + i * 2);
    const py = seededRandom(seed * 1000 + i * 2 + 1);
    const dx = x - px;
    const dy = y - py;
    const dist = dx * dx + dy * dy;
    if (dist < minDist) {
      minDist = dist;
      closestIdx = i;
    }
  }

  return closestIdx / numPoints;
}

/**
 * Swirl distribution -- spiral pattern using atan2 + distance,
 * with multiple arms and noise perturbation.
 *
 * @param {number} x
 * @param {number} y
 * @param {Function} noiseFn
 * @param {object} [params]
 * @param {number} [params.arms=3] - number of spiral arms
 * @param {number} [params.tightness=4.0] - how tightly the spiral winds
 * @param {number} [params.noiseStrength=0.2] - noise perturbation
 * @param {number} [params.frequency=2.0] - noise frequency
 * @returns {number} value in [0, 1]
 */
function swirl(x, y, noiseFn, params = {}) {
  const arms = params.arms != null ? params.arms : 3;
  const tightness = params.tightness != null ? params.tightness : 4.0;
  const noiseStrength = params.noiseStrength != null ? params.noiseStrength : 0.2;
  const frequency = params.frequency != null ? params.frequency : 2.0;

  const cx = x - 0.5;
  const cy = y - 0.5;
  const dist = Math.sqrt(cx * cx + cy * cy);
  const angle = Math.atan2(cy, cx);

  // Spiral phase: angle + distance * tightness, modulated by arm count
  const phase = angle * arms + dist * tightness * Math.PI * 2;

  // Map spiral to [0, 1] using sine
  const spiral = Math.sin(phase) * 0.5 + 0.5;

  const noise = noiseFn(x * frequency, y * frequency);
  const perturbed = spiral + noise * noiseStrength;

  return Math.max(0, Math.min(1, perturbed));
}

/**
 * Distribution mode registry.
 * Maps mode name strings to their distribution functions.
 */
export const MODES = {
  veined,
  radial,
  linear,
  clustered,
  swirl,
};
