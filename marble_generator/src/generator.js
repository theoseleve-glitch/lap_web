import sharp from 'sharp';
import { createNoise, fbm, domainWarp } from './noise.js';
import { mapDyeToColor, metallicGold } from './palette.js';
import { computeCoverage, withinTolerance } from './coverage.js';
import { createPalette } from './color/palette.js';
import { MODES } from './color/distribution.js';
import { generateVelocityField, PRESET_NAMES } from './engine/velocity-presets.js';

const TARGETS = { black: 60, white: 35, gold: 5 };
const TOLERANCE = 7; // percentage points
const MAX_TUNE_ITERATIONS = 8;

/** Default generation parameters. */
export const DEFAULTS = {
  warpStrength: 0.4,
  warpScale: 2.0,
  dyeOctaves: 5,
  dyeFrequency: 1.5,
  dyePersistence: 0.5,
  blackThreshold: 0.42,
  whiteThreshold: 0.58,
  goldThreshold: 0.65,
  goldWidth: 0.06,
  contrast: 1.2,
};

/**
 * Build noise functions from a seed.
 * Uses offsets of the base seed to create decorrelated noise layers.
 */
function buildNoises(seed) {
  return {
    warp1: createNoise(seed),
    warp2: createNoise(seed + 1000),
    warp3: createNoise(seed + 2000),
    warp4: createNoise(seed + 3000),
    dye: createNoise(seed + 4000),
    vein: createNoise(seed + 5000),
  };
}

/**
 * Render the marble dye field and gradient into a raw RGBA buffer.
 *
 * @param {number} width
 * @param {number} height
 * @param {Object} noises - noise functions from buildNoises()
 * @param {Object} params - generation parameters
 * @returns {{ buffer: Buffer, dyeField: Float32Array, gradientField: Float32Array }}
 */
function renderField(width, height, noises, params) {
  const { warpStrength, warpScale, dyeOctaves, dyeFrequency, dyePersistence,
          blackThreshold, whiteThreshold, goldThreshold, goldWidth, contrast } = params;

  const buffer = Buffer.alloc(width * height * 4);
  const dyeField = new Float32Array(width * height);
  const gradientField = new Float32Array(width * height);

  // Step 1: compute dye field values
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const nx = x / width;
      const ny = y / height;

      // Domain warp
      const { wx, wy } = domainWarp(noises, nx, ny, params);

      // Dye field: FBM at warped coords, map from [-1,1] to [0,1]
      const raw = fbm(noises.dye, wx, wy, dyeOctaves, dyeFrequency, dyePersistence);
      dyeField[y * width + x] = (raw + 1) * 0.5;
    }
  }

  // Step 2: compute gradient magnitude via finite differences
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = y * width + x;
      const left = x > 0 ? dyeField[idx - 1] : dyeField[idx];
      const right = x < width - 1 ? dyeField[idx + 1] : dyeField[idx];
      const up = y > 0 ? dyeField[idx - width] : dyeField[idx];
      const down = y < height - 1 ? dyeField[idx + width] : dyeField[idx];

      const gx = (right - left) * 0.5 * width;
      const gy = (down - up) * 0.5 * height;
      gradientField[idx] = Math.sqrt(gx * gx + gy * gy);
    }
  }

  // Normalize gradient using 95th percentile (not max) to avoid
  // outlier spikes squashing the distribution near 0
  const sorted = Float32Array.from(gradientField).sort();
  const p95 = sorted[Math.floor(sorted.length * 0.95)] || 1;
  if (p95 > 0) {
    for (let i = 0; i < gradientField.length; i++) {
      gradientField[i] = Math.min(1, gradientField[i] / p95);
    }
  }

  // Step 3: color mapping + gold veins + dither
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = y * width + x;
      const off = idx * 4;
      const dye = dyeField[idx];
      const grad = gradientField[idx];

      let color;

      // Gold vein: high gradient in the transition zone
      const inVeinRange = dye > (blackThreshold - goldWidth) && dye < (whiteThreshold + goldWidth);
      if (grad > goldThreshold && inVeinRange) {
        color = metallicGold(grad, goldThreshold);
      } else {
        color = mapDyeToColor(dye, blackThreshold, whiteThreshold, contrast);
      }

      // Anti-banding: triangular dither ±1 LSB
      const dither = (Math.random() + Math.random() - 1) * 1.5;
      buffer[off] = clamp(color.r + dither, 0, 255);
      buffer[off + 1] = clamp(color.g + dither, 0, 255);
      buffer[off + 2] = clamp(color.b + dither, 0, 255);
      buffer[off + 3] = 255; // fully opaque
    }
  }

  return { buffer, dyeField, gradientField };
}

function clamp(v, min, max) {
  return v < min ? min : v > max ? max : Math.round(v);
}

/**
 * Auto-tune thresholds to hit target coverage ratios.
 * Renders at 1/4 resolution for speed, iteratively adjusts thresholds.
 *
 * @param {number} width - full resolution width
 * @param {number} height - full resolution height
 * @param {Object} noises
 * @param {Object} params - mutable, will be adjusted in place
 * @returns {{ coverage: Object, iterations: number }}
 */
function autoTune(width, height, noises, params) {
  const tuneW = Math.round(width / 4);
  const tuneH = Math.round(height / 4);
  let coverage;
  let iterations = 0;

  for (let i = 0; i < MAX_TUNE_ITERATIONS; i++) {
    iterations = i + 1;
    const { buffer } = renderField(tuneW, tuneH, noises, params);
    coverage = computeCoverage(buffer, tuneW, tuneH);

    if (withinTolerance(coverage, TARGETS, TOLERANCE)) break;

    // Adjust thresholds based on coverage errors
    const blackErr = coverage.black - TARGETS.black;
    const goldErr = coverage.gold - TARGETS.gold;

    // If too much black → lower blackThreshold (lets more pixels become white)
    // If too little black → raise blackThreshold
    // Proportional step: larger errors → larger corrections
    const blackStep = Math.min(0.04, Math.abs(blackErr) * 0.008);
    params.blackThreshold -= Math.sign(blackErr) * blackStep;
    params.blackThreshold = Math.max(0.2, Math.min(0.65, params.blackThreshold));

    // WhiteThreshold tracks blackThreshold with a gap
    params.whiteThreshold = params.blackThreshold + 0.14;
    params.whiteThreshold = Math.max(params.blackThreshold + 0.05, Math.min(0.8, params.whiteThreshold));

    // If too much gold → raise goldThreshold (fewer pixels qualify)
    // If too little gold → lower goldThreshold
    params.goldThreshold += goldErr * 0.02;
    params.goldThreshold = Math.max(0.3, Math.min(0.95, params.goldThreshold));
  }

  return { coverage, iterations };
}

/**
 * Generate a single marble image.
 *
 * @param {Object} options
 * @param {number} options.width - output width in pixels
 * @param {number} options.height - output height in pixels
 * @param {number} options.seed - random seed
 * @param {Object} [options.params] - override default parameters
 * @returns {Promise<{ png: Buffer, coverage: Object, params: Object, seed: number, tuneIterations: number }>}
 */
export async function generateMarble({ width, height, seed, params: overrides = {} }) {
  const params = { ...DEFAULTS, ...overrides };
  const noises = buildNoises(seed);

  // Auto-tune thresholds
  const { coverage: tuneCoverage, iterations: tuneIterations } = autoTune(width, height, noises, params);

  // Render at full resolution with tuned params
  const { buffer } = renderField(width, height, noises, params);

  // Final coverage at full res
  const coverage = computeCoverage(buffer, width, height);

  // Encode to PNG
  const png = await sharp(buffer, { raw: { width, height, channels: 4 } })
    .png({ compressionLevel: 6 })
    .toBuffer();

  return { png, coverage, params: { ...params }, seed, tuneIterations };
}

// ---------------------------------------------------------------------------
// V2: N-color palette rendering
// ---------------------------------------------------------------------------

/**
 * Default parameters for V2 generation.
 * Shares warp/noise params with DEFAULTS but adds distribution-specific ones.
 */
export const DEFAULTS_V2 = {
  warpStrength: 0.4,
  warpScale: 2.0,
  dyeOctaves: 5,
  dyeFrequency: 1.5,
  dyePersistence: 0.5,
  contrast: 1.2,
  accentGradientThreshold: 0.65,
  blendWidth: 0.04,
};

/**
 * Smoothstep interpolation (cubic Hermite).
 *
 * @param {number} edge0
 * @param {number} edge1
 * @param {number} x
 * @returns {number} value in [0, 1]
 */
function smoothstep(edge0, edge1, x) {
  const t = Math.max(0, Math.min(1, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

/**
 * Lerp between two normalized-float RGB colors.
 *
 * @param {{ r: number, g: number, b: number }} a - RGB with values in [0, 1]
 * @param {{ r: number, g: number, b: number }} b - RGB with values in [0, 1]
 * @param {number} t - interpolation factor [0, 1]
 * @returns {{ r: number, g: number, b: number }}
 */
function lerpColorNorm(a, b, t) {
  const tc = Math.max(0, Math.min(1, t));
  return {
    r: a.r + (b.r - a.r) * tc,
    g: a.g + (b.g - a.g) * tc,
    b: a.b + (b.b - a.b) * tc,
  };
}

/**
 * Map a distribution value in [0, 1] to an N-color palette color.
 * Uses smoothstep blending at threshold transitions.
 *
 * @param {number} value - distribution value in [0, 1]
 * @param {Object} palette - from createPalette()
 * @param {number} blendWidth - half-width of the transition blend zone
 * @returns {{ r: number, g: number, b: number }} RGB in [0, 255]
 */
function mapValueToNColor(value, palette, blendWidth) {
  const { colors, thresholds, count } = palette;

  // Find which band the value falls into
  let bandIdx = 0;
  for (let i = 0; i < count; i++) {
    if (value <= thresholds[i]) {
      bandIdx = i;
      break;
    }
  }

  // Get base color for this band (normalized floats)
  const baseColor = colors[bandIdx];

  // Check for blend zone at the upper edge of this band
  if (bandIdx < count - 1) {
    const boundary = thresholds[bandIdx];
    const lowerEdge = boundary - blendWidth;
    const upperEdge = boundary + blendWidth;

    if (value > lowerEdge && value < upperEdge) {
      const nextColor = colors[bandIdx + 1];
      const t = smoothstep(lowerEdge, upperEdge, value);
      const blended = lerpColorNorm(baseColor, nextColor, t);
      return {
        r: Math.round(blended.r * 255),
        g: Math.round(blended.g * 255),
        b: Math.round(blended.b * 255),
      };
    }
  }

  // Check for blend zone at the lower edge of this band
  if (bandIdx > 0) {
    const boundary = thresholds[bandIdx - 1];
    const lowerEdge = boundary - blendWidth;
    const upperEdge = boundary + blendWidth;

    if (value > lowerEdge && value < upperEdge) {
      const prevColor = colors[bandIdx - 1];
      const t = smoothstep(lowerEdge, upperEdge, value);
      const blended = lerpColorNorm(prevColor, baseColor, t);
      return {
        r: Math.round(blended.r * 255),
        g: Math.round(blended.g * 255),
        b: Math.round(blended.b * 255),
      };
    }
  }

  return {
    r: Math.round(baseColor.r * 255),
    g: Math.round(baseColor.g * 255),
    b: Math.round(baseColor.b * 255),
  };
}

/**
 * Compute N-color coverage from a raw RGBA buffer.
 * Classifies each pixel to its nearest palette color by RGB distance.
 *
 * @param {Buffer} buffer - RGBA pixel data
 * @param {number} width
 * @param {number} height
 * @param {Object} palette - from createPalette()
 * @returns {Object} per-color coverage with hex keys and percentage values
 */
function computeCoverageV2(buffer, width, height, palette) {
  const { colors, count } = palette;
  const total = width * height;
  const counts = new Uint32Array(count);

  // Pre-compute palette colors in 0-255 space
  const palColors255 = colors.map((c) => ({
    r: Math.round(c.r * 255),
    g: Math.round(c.g * 255),
    b: Math.round(c.b * 255),
  }));

  for (let i = 0; i < total; i++) {
    const off = i * 4;
    const pr = buffer[off];
    const pg = buffer[off + 1];
    const pb = buffer[off + 2];

    let minDist = Infinity;
    let closest = 0;

    for (let c = 0; c < count; c++) {
      const dr = pr - palColors255[c].r;
      const dg = pg - palColors255[c].g;
      const db = pb - palColors255[c].b;
      const dist = dr * dr + dg * dg + db * db;
      if (dist < minDist) {
        minDist = dist;
        closest = c;
      }
    }

    counts[closest]++;
  }

  const coverage = { total };
  const colorDetails = [];
  for (let c = 0; c < count; c++) {
    const pct = (counts[c] / total) * 100;
    const hex = `#${palColors255[c].r.toString(16).padStart(2, '0')}${palColors255[c].g.toString(16).padStart(2, '0')}${palColors255[c].b.toString(16).padStart(2, '0')}`;
    colorDetails.push({ hex, percentage: pct, index: c });
    coverage[hex] = pct;
  }
  coverage.colorDetails = colorDetails;

  return coverage;
}

/**
 * Render N-color marble field using palette thresholds and distribution mode.
 *
 * @param {number} width
 * @param {number} height
 * @param {Object} noises - noise functions from buildNoises()
 * @param {Object} params - generation parameters (V2)
 * @param {Object} palette - from createPalette()
 * @param {Function} distributionFn - from MODES, maps (x, y, noiseFn, params) => [0, 1]
 * @param {Object} [distParams] - distribution-specific parameters
 * @param {Float32Array} [velocityField] - optional velocity field for advection
 * @returns {{ buffer: Buffer, dyeField: Float32Array }}
 */
function renderFieldV2(width, height, noises, params, palette, distributionFn, distParams, velocityField) {
  const { warpStrength, warpScale, dyeOctaves, dyeFrequency, dyePersistence,
          contrast, accentGradientThreshold, blendWidth } = params;

  const buffer = Buffer.alloc(width * height * 4);
  const dyeField = new Float32Array(width * height);
  const gradientField = new Float32Array(width * height);

  // Step 1: compute distribution values using the mode function
  // The distribution function operates on warped coordinates for organic feel
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const nx = x / width;
      const ny = y / height;

      // Domain warp for organic distortion
      const { wx, wy } = domainWarp(noises, nx, ny, params);

      // Apply velocity-based advection offset if velocity field provided
      let fx = wx;
      let fy = wy;
      if (velocityField) {
        // Sample velocity at the grid position (velocity field is at image resolution)
        const vIdx = (y * width + x) * 4;
        const vx = velocityField[vIdx] || 0;
        const vy = velocityField[vIdx + 1] || 0;
        // Advect: shift the sampling point by the velocity
        fx += vx * 0.01;
        fy += vy * 0.01;
      }

      // Use distribution mode to map warped coords to [0, 1]
      const distValue = distributionFn(fx, fy, noises.dye, distParams);

      // Apply contrast around 0.5 midpoint
      const adjusted = 0.5 + (distValue - 0.5) * contrast;
      dyeField[y * width + x] = Math.max(0, Math.min(1, adjusted));
    }
  }

  // Step 2: compute gradient magnitude for accent/vein detection
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = y * width + x;
      const left = x > 0 ? dyeField[idx - 1] : dyeField[idx];
      const right = x < width - 1 ? dyeField[idx + 1] : dyeField[idx];
      const up = y > 0 ? dyeField[idx - width] : dyeField[idx];
      const down = y < height - 1 ? dyeField[idx + width] : dyeField[idx];

      const gx = (right - left) * 0.5 * width;
      const gy = (down - up) * 0.5 * height;
      gradientField[idx] = Math.sqrt(gx * gx + gy * gy);
    }
  }

  // Normalize gradient using 95th percentile
  const sorted = Float32Array.from(gradientField).sort();
  const p95 = sorted[Math.floor(sorted.length * 0.95)] || 1;
  if (p95 > 0) {
    for (let i = 0; i < gradientField.length; i++) {
      gradientField[i] = Math.min(1, gradientField[i] / p95);
    }
  }

  // Step 3: color mapping via N-color palette with accent veins
  const accentColor = palette.colors[palette.count - 1]; // last color is accent
  const hasAccent = palette.count >= 3;

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = y * width + x;
      const off = idx * 4;
      const dye = dyeField[idx];
      const grad = gradientField[idx];

      let color;

      // Accent vein: high gradient at transitions between color bands
      if (hasAccent && grad > accentGradientThreshold) {
        // Blend accent color intensity based on gradient strength
        const intensity = Math.min(1, (grad - accentGradientThreshold) / (1 - accentGradientThreshold));
        const baseColor = mapValueToNColor(dye, palette, blendWidth);

        // Metallic-style accent modulation
        const accentR = Math.round(accentColor.r * 255);
        const accentG = Math.round(accentColor.g * 255);
        const accentB = Math.round(accentColor.b * 255);

        const t = intensity * 0.7; // max 70% accent blend
        color = {
          r: Math.round(baseColor.r + (accentR - baseColor.r) * t),
          g: Math.round(baseColor.g + (accentG - baseColor.g) * t),
          b: Math.round(baseColor.b + (accentB - baseColor.b) * t),
        };
      } else {
        color = mapValueToNColor(dye, palette, blendWidth);
      }

      // Anti-banding: triangular dither
      const dither = (Math.random() + Math.random() - 1) * 1.5;
      buffer[off] = clamp(color.r + dither, 0, 255);
      buffer[off + 1] = clamp(color.g + dither, 0, 255);
      buffer[off + 2] = clamp(color.b + dither, 0, 255);
      buffer[off + 3] = 255;
    }
  }

  return { buffer, dyeField };
}

/**
 * Generate an N-color marble image using palette and distribution modes.
 *
 * @param {Object} options
 * @param {number} options.width - output width in pixels
 * @param {number} options.height - output height in pixels
 * @param {number} options.seed - random seed
 * @param {Object} options.palette - from createPalette() (colors, thresholds, count)
 * @param {string} [options.distribution='veined'] - distribution mode name
 * @param {Object} [options.velocity] - velocity preset config
 * @param {string} [options.velocity.preset] - velocity preset name
 * @param {number} [options.velocity.magnitude=80] - velocity magnitude 0-200
 * @param {number} [options.velocity.angle=0] - velocity angle in degrees
 * @param {number} [options.velocity.turbulence=0] - turbulence overlay 0-50
 * @param {Object} [options.params] - override default V2 parameters
 * @returns {Promise<{ png: Buffer, coverage: Object, params: Object, seed: number, tuneIterations: number }>}
 */
export async function generateMarbleV2({ width, height, seed, palette, distribution = 'veined', velocity, params: overrides = {} }) {
  const params = { ...DEFAULTS_V2, ...overrides };
  const noises = buildNoises(seed);

  // Resolve distribution function
  const distributionFn = MODES[distribution];
  if (!distributionFn) {
    throw new Error(
      `Unknown distribution mode "${distribution}". ` +
      `Valid modes: ${Object.keys(MODES).join(', ')}`
    );
  }

  // Distribution-specific parameters: pass seed for deterministic modes
  const distParams = { seed };

  // Generate velocity field if requested
  let velocityField = null;
  if (velocity && velocity.preset) {
    const velParams = {
      magnitude: velocity.magnitude != null ? velocity.magnitude : 80,
      angle: velocity.angle != null ? velocity.angle : 0,
      turbulence: velocity.turbulence != null ? velocity.turbulence : 0,
      seed,
    };
    velocityField = generateVelocityField(velocity.preset, width, height, velParams, noises.dye);
  }

  // No auto-tune for V2 -- the palette thresholds define the color distribution
  // directly. The distribution mode + palette ratios control the visual balance.
  const { buffer } = renderFieldV2(width, height, noises, params, palette, distributionFn, distParams, velocityField);

  // Compute per-color coverage
  const coverage = computeCoverageV2(buffer, width, height, palette);

  // Encode to PNG
  const png = await sharp(buffer, { raw: { width, height, channels: 4 } })
    .png({ compressionLevel: 6 })
    .toBuffer();

  return { png, coverage, params: { ...params }, seed, tuneIterations: 0 };
}
