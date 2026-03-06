/**
 * N-color palette system for marble generation.
 * Converts hex colors to normalized RGB floats and builds
 * ratio/threshold arrays for distribution mapping.
 */

/**
 * Parse a hex color string to normalized RGB floats.
 *
 * @param {string} hex - Color in "#rrggbb" format
 * @returns {{ r: number, g: number, b: number }} RGB with values in [0, 1]
 */
export function hexToRgb(hex) {
  const h = hex.replace('#', '');
  return {
    r: parseInt(h.substring(0, 2), 16) / 255,
    g: parseInt(h.substring(2, 4), 16) / 255,
    b: parseInt(h.substring(4, 6), 16) / 255,
  };
}

/**
 * Convert normalized RGB floats back to a hex string.
 *
 * @param {{ r: number, g: number, b: number }} c - RGB with values in [0, 1]
 * @returns {string} Color in "#rrggbb" format
 */
export function rgbToHex(c) {
  const clamp = (v) => Math.max(0, Math.min(255, Math.round(v * 255)));
  const r = clamp(c.r).toString(16).padStart(2, '0');
  const g = clamp(c.g).toString(16).padStart(2, '0');
  const b = clamp(c.b).toString(16).padStart(2, '0');
  return `#${r}${g}${b}`;
}

/**
 * Build an N-color palette from an array of color entries.
 *
 * Each entry specifies a hex color, a ratio (relative weight),
 * and optional per-color physical properties (density, viscosity)
 * used by the fluid simulation.
 *
 * @param {Array<{ hex: string, ratio: number, density?: number, viscosity?: number }>} entries
 * @returns {{
 *   colors: Array<{ r: number, g: number, b: number }>,
 *   ratios: Float32Array,
 *   densities: Float32Array,
 *   viscosities: Float32Array,
 *   thresholds: Float32Array,
 *   count: number,
 * }}
 */
export function createPalette(entries) {
  const count = entries.length;

  const colors = entries.map((e) => hexToRgb(e.hex));

  // Normalize ratios so they sum to 1.0
  const rawSum = entries.reduce((s, e) => s + e.ratio, 0);
  const ratios = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    ratios[i] = entries[i].ratio / rawSum;
  }

  // Per-color densities (default 1.0)
  const densities = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    densities[i] = entries[i].density != null ? entries[i].density : 1.0;
  }

  // Per-color viscosities (default 0.001)
  const viscosities = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    viscosities[i] = entries[i].viscosity != null ? entries[i].viscosity : 0.001;
  }

  // Cumulative thresholds for distribution mapping.
  // E.g. ratios [0.6, 0.35, 0.05] -> thresholds [0.6, 0.95, 1.0]
  const thresholds = new Float32Array(count);
  let cumulative = 0;
  for (let i = 0; i < count; i++) {
    cumulative += ratios[i];
    thresholds[i] = cumulative;
  }
  // Ensure last threshold is exactly 1.0 to avoid floating-point gaps
  thresholds[count - 1] = 1.0;

  return { colors, ratios, densities, viscosities, thresholds, count };
}
