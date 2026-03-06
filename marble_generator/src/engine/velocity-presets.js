/**
 * CPU-side velocity field generator for initial velocity presets.
 *
 * Generates Float32Array in RGBA format [u0,v0,0,0, u1,v1,0,0, ...]
 * suitable for direct upload to a WebGL2 RGBA32F texture.
 *
 * 8 presets: curl-noise, laminar-h, laminar-v, radial-out, radial-in,
 * vortex, double-vortex, turbulent.
 */

// ---------------------------------------------------------------------------
// Internal noise utilities
// ---------------------------------------------------------------------------

/**
 * Simple hash-based pseudo-noise fallback.
 * Deterministic given (x, y, seed). Returns value in [-1, 1].
 */
function makeSimpleNoise(seed) {
  return function noise2D(x, y) {
    const raw = Math.sin(x * 127.1 + y * 311.7 + seed) * 43758.5453;
    const frac = raw - Math.floor(raw); // [0, 1)
    return frac * 2.0 - 1.0;            // [-1, 1]
  };
}

/**
 * Fractional Brownian Motion.
 * Layers multiple octaves of noise with prime-ratio lacunarity
 * to avoid tiling artifacts.
 *
 * @param {Function} fn      - 2D noise (x, y) => [-1, 1]
 * @param {number}   x
 * @param {number}   y
 * @param {number}   octaves
 * @param {number}   freq    - base frequency
 * @param {number}   persistence - amplitude decay per octave
 * @returns {number} value roughly in [-1, 1]
 */
function fbm(fn, x, y, octaves, freq, persistence) {
  const lacunarity = 2.1379;
  let value = 0;
  let amplitude = 1;
  let maxAmplitude = 0;
  let f = freq;

  for (let i = 0; i < octaves; i++) {
    value += amplitude * fn(x * f, y * f);
    maxAmplitude += amplitude;
    amplitude *= persistence;
    f *= lacunarity;
  }

  return value / maxAmplitude;
}

// ---------------------------------------------------------------------------
// Preset generators
// ---------------------------------------------------------------------------

/**
 * Each generator receives (gw, gh, params, noiseFn) and writes into the
 * provided Float32Array `field` in RGBA layout.
 *
 * Coordinates are normalized to [0, 1] for both x and y.
 */
const GENERATORS = {

  /**
   * Curl noise: u = dpsi/dy, v = -dpsi/dx
   * where psi = FBM noise. Finite differences with eps = 0.01.
   */
  'curl-noise'(field, gw, gh, params, noiseFn) {
    const { magnitude, angle } = params;
    const mag = magnitude * 0.01;
    const eps = 0.01;
    const freq = 2.0;
    const octaves = 4;
    const persistence = 0.5;

    for (let j = 0; j < gh; j++) {
      const ny = j / (gh - 1);
      for (let i = 0; i < gw; i++) {
        const nx = i / (gw - 1);
        const idx = (j * gw + i) * 4;

        const psiUp   = fbm(noiseFn, nx, ny + eps, octaves, freq, persistence);
        const psiDown = fbm(noiseFn, nx, ny - eps, octaves, freq, persistence);
        const psiRight = fbm(noiseFn, nx + eps, ny, octaves, freq, persistence);
        const psiLeft  = fbm(noiseFn, nx - eps, ny, octaves, freq, persistence);

        field[idx]     = (psiUp - psiDown) / (2.0 * eps) * mag;   // u = dpsi/dy
        field[idx + 1] = -(psiRight - psiLeft) / (2.0 * eps) * mag; // v = -dpsi/dx
        field[idx + 2] = 0;
        field[idx + 3] = 0;
      }
    }
  },

  /**
   * Laminar horizontal: uniform flow in the direction of `angle`.
   */
  'laminar-h'(field, gw, gh, params) {
    const { magnitude, angle } = params;
    const mag = magnitude * 0.05;
    const rad = angle * Math.PI / 180;
    const u = Math.cos(rad) * mag;
    const v = Math.sin(rad) * mag;

    for (let j = 0; j < gh; j++) {
      for (let i = 0; i < gw; i++) {
        const idx = (j * gw + i) * 4;
        field[idx]     = u;
        field[idx + 1] = v;
        field[idx + 2] = 0;
        field[idx + 3] = 0;
      }
    }
  },

  /**
   * Laminar vertical: uniform flow perpendicular to `angle`.
   */
  'laminar-v'(field, gw, gh, params) {
    const { magnitude, angle } = params;
    const mag = magnitude * 0.05;
    const rad = angle * Math.PI / 180;
    const u = -Math.sin(rad) * mag;
    const v =  Math.cos(rad) * mag;

    for (let j = 0; j < gh; j++) {
      for (let i = 0; i < gw; i++) {
        const idx = (j * gw + i) * 4;
        field[idx]     = u;
        field[idx + 1] = v;
        field[idx + 2] = 0;
        field[idx + 3] = 0;
      }
    }
  },

  /**
   * Radial outward: velocity pointing away from center.
   * Scaled by mag * 0.05 * (1 - r * 0.5) so it fades at the edges.
   */
  'radial-out'(field, gw, gh, params) {
    const { magnitude } = params;
    const mag = magnitude * 0.05;

    for (let j = 0; j < gh; j++) {
      const ny = j / (gh - 1);
      for (let i = 0; i < gw; i++) {
        const nx = i / (gw - 1);
        const idx = (j * gw + i) * 4;

        const dx = nx - 0.5;
        const dy = ny - 0.5;
        const r = Math.sqrt(dx * dx + dy * dy) + 0.001;
        const scale = mag * (1.0 - r * 0.5);

        field[idx]     = (dx / r) * scale;
        field[idx + 1] = (dy / r) * scale;
        field[idx + 2] = 0;
        field[idx + 3] = 0;
      }
    }
  },

  /**
   * Radial inward: velocity pointing toward center.
   * Scaled by mag * 0.05 * r so it strengthens away from center.
   */
  'radial-in'(field, gw, gh, params) {
    const { magnitude } = params;
    const mag = magnitude * 0.05;

    for (let j = 0; j < gh; j++) {
      const ny = j / (gh - 1);
      for (let i = 0; i < gw; i++) {
        const nx = i / (gw - 1);
        const idx = (j * gw + i) * 4;

        const dx = nx - 0.5;
        const dy = ny - 0.5;
        const r = Math.sqrt(dx * dx + dy * dy) + 0.001;
        const scale = mag * r;

        field[idx]     = -(dx / r) * scale;
        field[idx + 1] = -(dy / r) * scale;
        field[idx + 2] = 0;
        field[idx + 3] = 0;
      }
    }
  },

  /**
   * Single vortex: tangential velocity = (-dy, dx) / r * mag * exp(-r*4).
   * Creates a tight swirl at the center with exponential falloff.
   */
  'vortex'(field, gw, gh, params) {
    const { magnitude } = params;
    const mag = magnitude * 0.05;

    for (let j = 0; j < gh; j++) {
      const ny = j / (gh - 1);
      for (let i = 0; i < gw; i++) {
        const nx = i / (gw - 1);
        const idx = (j * gw + i) * 4;

        const dx = nx - 0.5;
        const dy = ny - 0.5;
        const r = Math.sqrt(dx * dx + dy * dy) + 0.001;
        const scale = mag * Math.exp(-r * 4.0);

        field[idx]     = (-dy / r) * scale;
        field[idx + 1] = ( dx / r) * scale;
        field[idx + 2] = 0;
        field[idx + 3] = 0;
      }
    }
  },

  /**
   * Double vortex: two counter-rotating vortices.
   * Left vortex at (0.35, 0.5) spins counter-clockwise.
   * Right vortex at (0.65, 0.5) spins clockwise.
   * Each has exp(-r*1.5) falloff.
   */
  'double-vortex'(field, gw, gh, params) {
    const { magnitude } = params;
    const mag = magnitude * 0.05;

    const cx1 = 0.35, cy1 = 0.5;
    const cx2 = 0.65, cy2 = 0.5;

    for (let j = 0; j < gh; j++) {
      const ny = j / (gh - 1);
      for (let i = 0; i < gw; i++) {
        const nx = i / (gw - 1);
        const idx = (j * gw + i) * 4;

        // Vortex 1 (counter-clockwise)
        const dx1 = nx - cx1;
        const dy1 = ny - cy1;
        const r1 = Math.sqrt(dx1 * dx1 + dy1 * dy1) + 0.001;
        const s1 = mag * Math.exp(-r1 * 1.5);

        // Vortex 2 (clockwise — reversed tangent)
        const dx2 = nx - cx2;
        const dy2 = ny - cy2;
        const r2 = Math.sqrt(dx2 * dx2 + dy2 * dy2) + 0.001;
        const s2 = mag * Math.exp(-r2 * 1.5);

        field[idx]     = (-dy1 / r1) * s1 + ( dy2 / r2) * s2;
        field[idx + 1] = ( dx1 / r1) * s1 + (-dx2 / r2) * s2;
        field[idx + 2] = 0;
        field[idx + 3] = 0;
      }
    }
  },

  /**
   * Turbulent: high-frequency curl noise.
   * Uses freq*4, 6 octaves, persistence 0.6 for chaotic flow.
   */
  'turbulent'(field, gw, gh, params, noiseFn) {
    const { magnitude } = params;
    const mag = magnitude * 0.015;
    const eps = 0.01;
    const freq = 2.0 * 4.0; // high frequency
    const octaves = 6;
    const persistence = 0.6;

    for (let j = 0; j < gh; j++) {
      const ny = j / (gh - 1);
      for (let i = 0; i < gw; i++) {
        const nx = i / (gw - 1);
        const idx = (j * gw + i) * 4;

        const psiUp    = fbm(noiseFn, nx, ny + eps, octaves, freq, persistence);
        const psiDown  = fbm(noiseFn, nx, ny - eps, octaves, freq, persistence);
        const psiRight = fbm(noiseFn, nx + eps, ny, octaves, freq, persistence);
        const psiLeft  = fbm(noiseFn, nx - eps, ny, octaves, freq, persistence);

        field[idx]     = (psiUp - psiDown) / (2.0 * eps) * mag;
        field[idx + 1] = -(psiRight - psiLeft) / (2.0 * eps) * mag;
        field[idx + 2] = 0;
        field[idx + 3] = 0;
      }
    }
  },
};

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** All available preset names. */
export const PRESET_NAMES = Object.keys(GENERATORS);

/**
 * Generate a velocity field for the given preset.
 *
 * @param {string}   preset  - One of PRESET_NAMES
 * @param {number}   gw      - Grid width in cells
 * @param {number}   gh      - Grid height in cells
 * @param {Object}   params  - { magnitude, angle, turbulence, seed }
 * @param {Function} [noiseFn] - Optional 2D noise function (x, y) => [-1, 1].
 *                               If not provided, a simple hash-based fallback is used.
 * @returns {Float32Array} RGBA velocity field [u0,v0,0,0, u1,v1,0,0, ...]
 */
export function generateVelocityField(preset, gw, gh, params, noiseFn) {
  const p = {
    magnitude:  params?.magnitude  ?? 80,
    angle:      params?.angle      ?? 0,
    turbulence: params?.turbulence ?? 0,
    seed:       params?.seed       ?? 42,
  };

  const generator = GENERATORS[preset];
  if (!generator) {
    throw new Error(
      `Unknown velocity preset "${preset}". ` +
      `Valid presets: ${PRESET_NAMES.join(', ')}`
    );
  }

  // Resolve noise function: use provided or fall back to simple hash noise
  const noise = noiseFn || makeSimpleNoise(p.seed);

  const size = gw * gh * 4;
  const field = new Float32Array(size);

  // Generate base velocity field
  generator(field, gw, gh, p, noise);

  // Overlay turbulence perturbation if requested
  if (p.turbulence > 0) {
    const tMag = p.turbulence * 0.01 * p.magnitude;
    const eps = 0.01;
    const freq = 6.0;
    const octaves = 4;
    const persistence = 0.5;

    // Use a different seed offset for turbulence noise so it does not
    // correlate with the base field's noise.
    const turbNoise = makeSimpleNoise(p.seed + 9973);

    for (let j = 0; j < gh; j++) {
      const ny = j / (gh - 1);
      for (let i = 0; i < gw; i++) {
        const nx = i / (gw - 1);
        const idx = (j * gw + i) * 4;

        const psiUp    = fbm(turbNoise, nx, ny + eps, octaves, freq, persistence);
        const psiDown  = fbm(turbNoise, nx, ny - eps, octaves, freq, persistence);
        const psiRight = fbm(turbNoise, nx + eps, ny, octaves, freq, persistence);
        const psiLeft  = fbm(turbNoise, nx - eps, ny, octaves, freq, persistence);

        field[idx]     += (psiUp - psiDown) / (2.0 * eps) * tMag * 0.01;
        field[idx + 1] += -(psiRight - psiLeft) / (2.0 * eps) * tMag * 0.01;
      }
    }
  }

  return field;
}
