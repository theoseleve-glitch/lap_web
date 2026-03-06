// Deep black — not pure #000 to avoid looking digital
export const BLACK = { r: 10, g: 10, b: 12 };

// Off-white — warm cream tone, not sterile white
export const OFF_WHITE = { r: 235, g: 230, b: 220 };

// Base metallic gold
const GOLD_BASE = { r: 195, g: 165, b: 75 };

// Gold highlight (lighter, simulates specular)
const GOLD_LIGHT = { r: 235, g: 210, b: 120 };

// Gold shadow (darker, simulates ambient occlusion)
const GOLD_DARK = { r: 140, g: 115, b: 45 };

/**
 * Lerp between two colors.
 */
function lerpColor(a, b, t) {
  const tc = Math.max(0, Math.min(1, t));
  return {
    r: Math.round(a.r + (b.r - a.r) * tc),
    g: Math.round(a.g + (b.g - a.g) * tc),
    b: Math.round(a.b + (b.b - a.b) * tc),
  };
}

/**
 * Blend between black and off-white based on dye value.
 * Uses a smoothstep transition in the blend zone.
 *
 * @param {number} dye - dye field value in [0, 1]
 * @param {number} blackThreshold - below this → black
 * @param {number} whiteThreshold - above this → off-white
 * @param {number} contrast - contrast boost (1.0 = neutral)
 * @returns {{ r, g, b }}
 */
export function mapDyeToColor(dye, blackThreshold, whiteThreshold, contrast) {
  // Apply contrast curve around 0.5 midpoint
  const adjusted = 0.5 + (dye - 0.5) * contrast;
  const d = Math.max(0, Math.min(1, adjusted));

  if (d <= blackThreshold) return { ...BLACK };
  if (d >= whiteThreshold) return { ...OFF_WHITE };

  // Smoothstep in transition zone
  const t = (d - blackThreshold) / (whiteThreshold - blackThreshold);
  const smooth = t * t * (3 - 2 * t);
  return lerpColor(BLACK, OFF_WHITE, smooth);
}

/**
 * Metallic gold shader — modulates gold brightness based on gradient
 * to simulate specular highlights on vein edges.
 *
 * @param {number} gradient - gradient magnitude at this pixel
 * @param {number} goldThreshold - minimum gradient for gold
 * @returns {{ r, g, b }}
 */
export function metallicGold(gradient, goldThreshold) {
  // Normalize gradient intensity above threshold → [0, 1]
  const intensity = Math.min(1, (gradient - goldThreshold) / (1 - goldThreshold));

  // Metallic variation: blend from dark→base→light based on intensity
  if (intensity < 0.5) {
    const t = intensity * 2; // 0→1 over first half
    return lerpColor(GOLD_DARK, GOLD_BASE, t);
  } else {
    const t = (intensity - 0.5) * 2; // 0→1 over second half
    return lerpColor(GOLD_BASE, GOLD_LIGHT, t);
  }
}
