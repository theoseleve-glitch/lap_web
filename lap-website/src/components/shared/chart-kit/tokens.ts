/**
 * Chart kit design tokens.
 *
 * Single source of truth for every color, spacing, font, and weight used
 * inside any chart. Drawing primitives and shell components MUST consume
 * these — never inline hex values, never inline px values for padding.
 *
 * Token names are semantic (what they mean), never visual (what they look
 * like). This is what allows the analytics UI to feel like one product.
 */

// ── Color tokens (canonical, mapped from src/styles/tokens.css) ───────────
export const chartColor = {
  // Surface
  surface: '#141414',          // concrete — chart card bg
  surfaceMuted: '#0a0a0a',     // a notch darker — for inset zones
  surfaceRaised: '#1a1a1a',    // a notch lighter — for tooltips, hover

  // Frame
  border: 'rgba(148,148,148,0.15)',     // steel @ 15% — card border
  borderStrong: 'rgba(148,148,148,0.25)',
  axis: 'rgba(148,148,148,0.30)',       // axis line
  grid: 'rgba(148,148,148,0.08)',       // gridline — quiet
  gridStrong: 'rgba(148,148,148,0.14)', // emphasized gridline (zero baseline)

  // Text
  text: '#F0EDE5',                         // chalk — primary
  textSecondary: 'rgba(148,148,148,0.85)', // steel @ 85% — axis title, key labels
  textMuted: 'rgba(148,148,148,0.60)',     // steel @ 60% — tick labels (legible but quiet)

  // Crosshair
  crosshair: 'rgba(240,237,229,0.18)',  // chalk @ 18% — quiet vertical line

  // Tooltip
  tooltipBg: 'rgba(20,20,20,0.96)',
  tooltipBorder: 'rgba(148,148,148,0.20)',

  // Semantic series
  series: {
    primary: '#C9A84C',        // pit-orange / gold — your lap
    reference: '#8B5CF6',      // racing-purple — cross-session reference
    positive: '#22C55E',       // acid-green — faster / gain
    negative: '#FF2A2A',       // safety-red — slower / loss
    neutral: '#F0EDE5',        // chalk — comparison baseline
    warning: '#FACC15',        // marshal-yellow — out of band
  },

  // Multi-series palette (for lap overlays, color-blind friendly distinct hues)
  // Order chosen so first ~4 are the most distinguishable in dark mode.
  palette: [
    '#C9A84C', // gold
    '#8B5CF6', // purple
    '#22C55E', // green
    '#3B82F6', // blue
    '#F97316', // orange
    '#06B6D4', // cyan
    '#EC4899', // pink
    '#FACC15', // yellow
    '#A855F7', // violet
    '#10B981', // emerald
  ] as const,
} as const;

// ── Spacing — drives card padding, header gap, body padding ──────────────
// Density variants give a single knob to tune visual weight per row.
export type Density = 'comfortable' | 'compact';

export const chartSpacing = {
  comfortable: {
    cardPadding: 16,        // px — outer card padding
    headerGap: 12,          // px — gap between header and body
    plotInset: 0,           // px — extra padding inside body before canvas
    headerHeight: 32,       // px — header row height
    legendGap: 12,          // px — between body and legend
  },
  compact: {
    cardPadding: 12,
    headerGap: 8,
    plotInset: 0,
    headerHeight: 26,
    legendGap: 8,
  },
} as const satisfies Record<Density, Record<string, number>>;

// ── Plot-area padding: where canvas data starts inside the canvas ─────────
// These are NOT the card padding — they're the inset between the canvas
// edge and the plotted data, leaving room for axis labels.
export const plotPadding = {
  comfortable: { top: 16, right: 12, bottom: 32, left: 52 },
  compact:     { top: 12, right: 10, bottom: 26, left: 44 },
} as const satisfies Record<Density, { top: number; right: number; bottom: number; left: number }>;

// ── Typography ───────────────────────────────────────────────────────────
// font-monument and font-telemetry are mapped in tailwind.config.ts.
// In canvas we need raw font strings.
export const chartFont = {
  title: '600 13px "PP Monument Extended", "Inter", sans-serif',
  subtitle: '11px "Space Mono", "JetBrains Mono", monospace',
  axisLabel: '10px "Space Mono", "JetBrains Mono", monospace',
  axisTitle: '10px "Space Mono", "JetBrains Mono", monospace',
  tickLabel: '10px "Space Mono", "JetBrains Mono", monospace',
  tooltip: '11px "Space Mono", "JetBrains Mono", monospace',
  tooltipBold: '600 11px "Space Mono", "JetBrains Mono", monospace',
  legend: '10px "Space Mono", "JetBrains Mono", monospace',
  seriesLabel: '600 10px "Space Mono", "JetBrains Mono", monospace',
} as const;

// ── Stroke widths — keep frame quiet, data series prominent ──────────────
export const chartStroke = {
  axis: 1,
  grid: 0.5,
  gridStrong: 1,
  crosshair: 1,
  reference: 1.5,
  seriesPrimary: 2,        // your lap — boldest
  seriesSecondary: 1.5,    // other laps in same session
  seriesReference: 1.5,    // cross-session reference (dashed)
  seriesGhost: 1,          // theoretical / aggregate
} as const;

// ── Dash patterns ────────────────────────────────────────────────────────
export const chartDash = {
  reference: [6, 4],       // cross-session reference lines
  theoretical: [4, 4],     // theoretical / optimal
  grid: [],                // solid (use opacity for quietness)
  crosshair: [3, 3],
} as const;

// ── Radius — never round more than this on chart surfaces ────────────────
export const chartRadius = {
  card: 12,                // matches Tailwind rounded-xl
  tooltip: 8,
  pill: 6,
} as const;

export type ChartTheme = {
  color: typeof chartColor;
  font: typeof chartFont;
  stroke: typeof chartStroke;
  dash: typeof chartDash;
  radius: typeof chartRadius;
};

// Default theme exported as a single bundle so primitives can take one arg.
export const defaultTheme: ChartTheme = {
  color: chartColor,
  font: chartFont,
  stroke: chartStroke,
  dash: chartDash,
  radius: chartRadius,
};
