/**
 * Pixel classification and coverage metrics.
 *
 * Classifies each pixel into black/off-white/gold based on RGB proximity,
 * then computes percentage breakdown.
 */

// Luminance thresholds for classification
const DARK_LUM_MAX = 60;     // below this → black
const LIGHT_LUM_MIN = 180;   // above this → off-white
// Between these → check for gold hue

/**
 * Compute perceived luminance (Rec. 709).
 */
function luminance(r, g, b) {
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/**
 * Check if a pixel is in the gold hue range.
 * Gold has: R > G > B, moderate-to-high saturation, warm tone.
 */
function isGoldHue(r, g, b) {
  if (r < 80 || g < 60) return false;    // too dark to be gold
  if (r <= g) return false;              // gold requires R > G
  if (b >= g) return false;              // gold requires G > B
  const saturation = (r - b) / Math.max(r, 1);
  return saturation > 0.25;             // needs visible warmth
}

/**
 * Classify a single pixel.
 * @param {number} r
 * @param {number} g
 * @param {number} b
 * @returns {'black' | 'white' | 'gold'}
 */
export function classifyPixel(r, g, b) {
  if (isGoldHue(r, g, b)) return 'gold';
  const lum = luminance(r, g, b);
  if (lum <= DARK_LUM_MAX) return 'black';
  if (lum >= LIGHT_LUM_MIN) return 'white';
  // Mid-tones: assign to closest pole
  return lum < (DARK_LUM_MAX + LIGHT_LUM_MIN) / 2 ? 'black' : 'white';
}

/**
 * Compute coverage metrics from a raw RGBA buffer.
 *
 * @param {Buffer} buffer - RGBA pixel data (4 bytes per pixel)
 * @param {number} width
 * @param {number} height
 * @returns {{ black: number, white: number, gold: number, total: number }}
 *          percentages in [0, 100]
 */
export function computeCoverage(buffer, width, height) {
  const total = width * height;
  let black = 0;
  let white = 0;
  let gold = 0;

  for (let i = 0; i < total; i++) {
    const off = i * 4;
    const cls = classifyPixel(buffer[off], buffer[off + 1], buffer[off + 2]);
    if (cls === 'black') black++;
    else if (cls === 'white') white++;
    else gold++;
  }

  return {
    black: (black / total) * 100,
    white: (white / total) * 100,
    gold: (gold / total) * 100,
    total,
  };
}

/**
 * Check if coverage is within tolerance of targets.
 *
 * @param {{ black: number, white: number, gold: number }} coverage
 * @param {{ black: number, white: number, gold: number }} targets - target percentages
 * @param {number} tolerance - acceptable deviation in percentage points
 * @returns {boolean}
 */
export function withinTolerance(coverage, targets, tolerance) {
  return (
    Math.abs(coverage.black - targets.black) <= tolerance &&
    Math.abs(coverage.white - targets.white) <= tolerance &&
    Math.abs(coverage.gold - targets.gold) <= tolerance
  );
}
