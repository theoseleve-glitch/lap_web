/**
 * Design tokens — single source of truth (mirrors tokens.css).
 *
 * CSS variables in tokens.css are the canonical definitions.
 * This file re-exports the same values for JS/GSAP/Three usage.
 * Keep BOTH files in sync. Lint: `npm run lint:design-tokens`.
 */

// ── Base + Accent Colors ────────────────────────────────────────────
export const colors = {
  asphalt: '#000000',
  concrete: '#141414',
  chalk: '#F0EDE5',
  steel: '#888888',
  acidGreen: '#22C55E',
  safetyRed: '#FF2A2A',
  marshalYellow: '#FACC15',
  pitOrange: '#C9A84C',
  racingPurple: '#8B5CF6',
} as const;

// ── Semantic Colors ─────────────────────────────────────────────────
export const semantic = {
  success: colors.acidGreen,
  warning: colors.marshalYellow,
  error: colors.safetyRed,
  info: colors.racingPurple,
  brand: colors.pitOrange,
} as const;

// ── Chart Palette ───────────────────────────────────────────────────
export const chartPalette = [
  '#22C55E', '#3B82F6', '#F59E0B', '#EF4444', '#A78BFA', '#EC4899',
] as const;

// ── Timing (seconds for GSAP, CSS uses --duration-* vars) ───────────
export const timing = {
  micro: 0.42,
  room: 0.9,
  monument: 1.4,
  sectorGate: 0.4,
  drs: 2.0,
  pit: 0.6,
  finish: 0.6,
} as const;

// ── Easing (GSAP strings; CSS equivalents in tokens.css) ────────────
export const easing = {
  inertia: 'power3.out',
  overshoot: 'back.out(1.7)',
  spring: 'back.out(1.2)',
  snap: 'power2.in',
  anticipate: 'power2.inOut',
  sectorGate: 'power4.out',
  pitEnter: 'power2.in',
  pitExit: 'power4.out',
} as const;

// ── Elevation (shadow levels e0–e4) ─────────────────────────────────
export const elevation = {
  e0: 'var(--shadow-e0)',
  e1: 'var(--shadow-e1)',
  e2: 'var(--shadow-e2)',
  e3: 'var(--shadow-e3)',
  e4: 'var(--shadow-e4)',
} as const;

// ── Radius ──────────────────────────────────────────────────────────
export const radius = {
  r0: 0,
  r1: 4,
  r2: 8,
  r3: 12,
  r4: 16,
  full: 9999,
} as const;

// ── Border ──────────────────────────────────────────────────────────
export const border = {
  default: 1,
  thick: 2,
} as const;

// ── Spacing (8px baseline) ──────────────────────────────────────────
export const spacing = {
  1: 8,
  2: 16,
  3: 24,
  4: 32,
  5: 40,
  6: 48,
  8: 64,
  10: 80,
  12: 96,
  16: 128,
} as const;

// ── Typography ──────────────────────────────────────────────────────
export const fontFamily = {
  display: '"Space Grotesk", "Arial Black", sans-serif',
  body: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  mono: '"Space Mono", "Fira Code", "Courier New", monospace',
} as const;

export const lineHeight = {
  display: 0.85,
  heading: 1.15,
  body: 1.72,
  label: 1.2,
} as const;

export const letterSpacing = {
  display: '-0.02em',
  wide: '0.12em',
  medium: '0.08em',
  xwide: '0.15em',
} as const;

// ── Z-Index ─────────────────────────────────────────────────────────
export const zIndex = {
  base: 0,
  panels: 10,
  stamps: 20,
  delta: 30,
  hud: 35,
  drs: 36,
  finishLine: 37,
  sector: 40,
  timecode: 50,
  nav: 60,
  overlay: 100,
  cursor: 999,
} as const;

// ── Focus + Touch ───────────────────────────────────────────────────
export const focus = {
  ringWidth: 3,
  ringOffset: 2,
} as const;

export const touchMin = 44;

// ── Grid ────────────────────────────────────────────────────────────
export const grid = {
  columns: 12,
} as const;

// ── Room / Narrative (marketing page scroll sections) ───────────────
export const roomAccents: Record<string, string> = {
  'start-grid': 'none',
  's1-pain': 'green',
  's1-deep': 'green',
  's2-pipeline': 'yellow',
  's2-proof': 'yellow',
  's3-product': 'green',
  's4-workflows': 'yellow',
  's5-personas': 'orange',
  'pit-stop': 'orange',
  'garage': 'none',
  'podium': 'orange',
} as const;

export const rooms = [
  { id: 'start-grid', label: 'START', sector: '—' },
  { id: 's1-pain', label: 'S1', sector: 'S1' },
  { id: 's1-deep', label: 'S1', sector: 'S1' },
  { id: 's2-pipeline', label: 'S2', sector: 'S2' },
  { id: 's2-proof', label: 'S2', sector: 'S2' },
  { id: 's3-product', label: 'S3', sector: 'S3' },
  { id: 's4-workflows', label: 'S4', sector: 'S4' },
  { id: 's5-personas', label: 'S5', sector: 'S5' },
  { id: 'pit-stop', label: 'PIT', sector: 'PIT' },
  { id: 'garage', label: 'GAR', sector: 'GAR' },
  { id: 'podium', label: 'POD', sector: 'POD' },
] as const;

export const sectorGates: Record<number, string> = {
  1: 'S1',
  3: 'S2',
  5: 'S3',
  8: 'PIT',
  10: 'FINISH',
} as const;

export const sectorTabs = [
  { id: 's1-pain', label: 'S1' },
  { id: 's2-pipeline', label: 'S2' },
  { id: 's3-product', label: 'S3' },
  { id: 's4-workflows', label: 'S4' },
  { id: 's5-personas', label: 'S5' },
  { id: 'pit-stop', label: 'PIT' },
  { id: 'garage', label: 'GAR' },
  { id: 'podium', label: 'POD' },
] as const;
