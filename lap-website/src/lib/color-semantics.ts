/**
 * Color semantics — meaning rules + optional color-blind palette.
 *
 * Rules:
 * - Red (#FF2A2A) = destructive actions + errors ONLY
 * - Green (#22C55E) = success + improvement + positive delta
 * - Yellow (#FACC15) = warnings + caution
 * - Purple (#8B5CF6) = informational + neutral state
 * - Gold (#C9A84C) = brand / premium accent (governed by brand-assets.ts)
 *
 * Links must be distinguishable by more than color alone:
 * - Underline on hover/focus (enforced via globals.css .room a::after)
 * - Focus ring on focus-visible (global :focus-visible rule)
 */

import { colors, semantic, chartPalette } from './tokens';

export const colorMeaning = {
  destructive: colors.safetyRed,
  error: colors.safetyRed,
  success: colors.acidGreen,
  improvement: colors.acidGreen,
  warning: colors.marshalYellow,
  caution: colors.marshalYellow,
  info: colors.racingPurple,
  neutral: colors.racingPurple,
  brand: colors.pitOrange,
  premium: colors.pitOrange,
} as const;

/**
 * Color-blind safe palette (deuteranopia / protanopia friendly).
 * Uses blue/orange discrimination instead of red/green.
 * Toggle via user preference stored in localStorage key 'lap_colorblind'.
 */
export const colorBlindPalette = {
  success: '#2563EB',   // blue instead of green
  warning: '#F59E0B',   // amber (unchanged — already safe)
  error: '#DC2626',     // darker red with pattern indicator
  info: '#7C3AED',      // purple (unchanged)
  brand: '#C9A84C',     // gold (unchanged)
} as const;

export const colorBlindChartPalette = [
  '#2563EB', '#F59E0B', '#7C3AED', '#DC2626', '#06B6D4', '#EC4899',
] as const;

/** Returns the active palette based on user preference */
export function getSemanticColors(colorBlind: boolean) {
  return colorBlind ? colorBlindPalette : semantic;
}

export function getChartColors(colorBlind: boolean) {
  return colorBlind ? colorBlindChartPalette : chartPalette;
}
