import { makeNoise2D } from 'open-simplex-noise';

/**
 * Create a seeded 2D simplex noise function.
 * open-simplex-noise uses a numeric seed internally.
 */
export function createNoise(seed) {
  return makeNoise2D(seed);
}

/**
 * Fractional Brownian Motion — layers multiple octaves of noise.
 * Each octave doubles frequency and halves amplitude (controlled by persistence).
 *
 * @param {Function} noiseFn - 2D noise function (x, y) => [-1, 1]
 * @param {number} x
 * @param {number} y
 * @param {number} octaves - number of layers (3-8)
 * @param {number} frequency - base frequency
 * @param {number} persistence - amplitude decay per octave (0.3-0.7)
 * @returns {number} value roughly in [-1, 1]
 */
export function fbm(noiseFn, x, y, octaves, frequency, persistence) {
  let value = 0;
  let amplitude = 1;
  let maxAmplitude = 0;
  // Use prime-ratio multipliers to avoid tiling artifacts
  const lacunarity = 2.1379;

  for (let i = 0; i < octaves; i++) {
    value += amplitude * noiseFn(x * frequency, y * frequency);
    maxAmplitude += amplitude;
    amplitude *= persistence;
    frequency *= lacunarity;
  }

  return value / maxAmplitude; // normalize to [-1, 1]
}

/**
 * Domain warping — use noise to distort input coordinates, creating organic swirls.
 * Two layers of warping for richer distortion:
 *   p' = p + warpStrength * fbm(p)
 *   p'' = p' + warpStrength * fbm(p' + offset)
 *
 * @param {Object} noises - { warp1, warp2, warp3, warp4 } noise functions
 * @param {number} x - normalized x [0, 1]
 * @param {number} y - normalized y [0, 1]
 * @param {Object} params - { warpStrength, warpScale, dyeOctaves, dyeFrequency, dyePersistence }
 * @returns {{ wx: number, wy: number }} warped coordinates
 */
export function domainWarp(noises, x, y, params) {
  const { warpStrength, warpScale, dyeOctaves, dyeFrequency, dyePersistence } = params;

  // First warp layer
  const dx1 = fbm(noises.warp1, x * warpScale, y * warpScale, dyeOctaves, dyeFrequency, dyePersistence);
  const dy1 = fbm(noises.warp2, x * warpScale, y * warpScale, dyeOctaves, dyeFrequency, dyePersistence);

  const x1 = x + warpStrength * dx1;
  const y1 = y + warpStrength * dy1;

  // Second warp layer (offset by 5.2 and 1.3 to decorrelate)
  const dx2 = fbm(noises.warp3, (x1 + 5.2) * warpScale, (y1 + 1.3) * warpScale, dyeOctaves, dyeFrequency, dyePersistence);
  const dy2 = fbm(noises.warp4, (x1 + 1.7) * warpScale, (y1 + 9.2) * warpScale, dyeOctaves, dyeFrequency, dyePersistence);

  return {
    wx: x1 + warpStrength * 0.6 * dx2,
    wy: y1 + warpStrength * 0.6 * dy2,
  };
}
