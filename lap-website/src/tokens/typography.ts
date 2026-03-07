/**
 * Typography tokens — single source of truth.
 *
 * Every component must reference these tokens (via CSS vars or Tailwind classes).
 * No raw px font-size, no inline font-family, no ad-hoc letter-spacing.
 *
 * Font stacks:
 *   Display: Space Grotesk  → var(--font-display) / font-monument
 *   Body:    Inter           → var(--font-body)    / font-body
 *   Mono:    Space Mono      → var(--font-mono)    / font-telemetry
 */

/* ── Font Stacks ─────────────────────────────── */

export const FONT_STACKS = {
  display: '"Space Grotesk", "Arial Black", sans-serif',
  body: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  mono: '"Space Mono", "Fira Code", "Courier New", monospace',
} as const;

/* ── Type Scale (rem, base = 16px) ───────────── */

export const TYPE_SCALE = {
  /** Monument headlines: clamp(3.75rem, 12vw, 12.25rem) */
  'monument-xl': 'clamp(3.75rem, 12vw, 12.25rem)',
  /** Page titles: clamp(3rem, 6vw, 5.25rem) */
  h1: 'clamp(3rem, 6vw, 5.25rem)',
  /** Section headings: clamp(2.25rem, 4vw, 3.5rem) */
  h2: 'clamp(2.25rem, 4vw, 3.5rem)',
  /** Subsection headings: clamp(1.5rem, 2.5vw, 2rem) */
  h3: 'clamp(1.5rem, 2.5vw, 2rem)',
  /** Body text: clamp(1.0625rem, 1.3vw, 1.25rem) */
  body: 'clamp(1.0625rem, 1.3vw, 1.25rem)',
  /** Captions, secondary text: 0.8125rem */
  caption: '0.8125rem',
  /** Telemetry labels, stamps, badges: 0.6875rem */
  telemetry: '0.6875rem',
  /** Tiny labels (scrutineering stamps detail): 0.5625rem */
  tiny: '0.5625rem',
} as const;

/* ── Line Heights ────────────────────────────── */

export const LINE_HEIGHTS = {
  /** Monument/display: tight, stacked */
  display: '0.85',
  /** Headings: comfortable for multi-line */
  heading: '1.15',
  /** Body: optimized for 60-75 ch reading */
  body: '1.72',
  /** Telemetry labels: compact */
  label: '1.2',
} as const;

/* ── Letter Spacing ──────────────────────────── */

export const LETTER_SPACING = {
  /** Monument display: tight */
  display: '-0.02em',
  /** Telemetry/label: wide, uppercase */
  wide: '0.12em',
  /** Marquee/decorative: medium */
  medium: '0.08em',
  /** Extra-wide: badges, status */
  xwide: '0.15em',
} as const;

/* ── Font Weights ────────────────────────────── */

export const FONT_WEIGHTS = {
  regular: '400',
  medium: '500',
  semibold: '600',
  bold: '700',
} as const;

/* ── Max Line Length ─────────────────────────── */

export const MAX_LINE_LENGTH = {
  /** Prose paragraphs: 65ch for optimal readability */
  prose: '65ch',
  /** Wide content (tables, code): 90ch */
  wide: '90ch',
  /** Tooltip max width */
  tooltip: '18rem',
} as const;

/* ── Spacing Tokens (Hero Block: H1 + subline + CTA) ── */

export const HERO_SPACING = {
  /** Gap between monument text and subline */
  monumentToSubline: 'var(--space-3)',
  /** Gap between subline and CTA button */
  sublineToCta: 'var(--space-5)',
  /** Vertical padding above/below hero block */
  blockPadding: 'var(--space-12)',
} as const;

/* ── Link Styles ─────────────────────────────── */

export const LINK_STYLES = {
  /** Default: chalk text, animated underline on hover */
  default: {
    color: 'var(--chalk)',
    hoverColor: 'var(--accent)',
    underline: 'animated-sweep',
  },
  /** Nav: no underline, opacity change */
  nav: {
    color: 'var(--steel)',
    hoverColor: 'var(--chalk)',
    underline: 'none',
  },
} as const;

/* ── Label Styles ────────────────────────────── */

export const LABEL_STYLES = {
  /** Standard telemetry label: mono, uppercase, wide tracking, 11px */
  standard: {
    font: 'mono',
    size: 'telemetry',
    weight: 'regular',
    letterSpacing: 'wide',
    textTransform: 'uppercase' as const,
  },
  /** Badge/status label: mono, uppercase, extra-wide tracking, 9-10px */
  badge: {
    font: 'mono',
    size: 'tiny',
    weight: 'regular',
    letterSpacing: 'xwide',
    textTransform: 'uppercase' as const,
  },
} as const;

/* ── Button Casing Rule ──────────────────────── */

/**
 * All CTA buttons use Sentence case: "Start free", "See pricing".
 * Exception: immersive room CTAs are UPPERCASE by design.
 * Enforced by lint-cta-text.mjs (CTA_DICTIONARY).
 */
export const BUTTON_CASING = 'sentence-case' as const;

/* ── Emphasis Rules ──────────────────────────── */

export const EMPHASIS_RULES = {
  /** Bold: for key terms in body copy (sparingly) */
  bold: 'font-weight: 500 (Inter medium, not 700)',
  /** Accent color: for metrics, scores, and interactive elements */
  accentColor: 'var(--accent) text color',
  /** Underline: links only, never for emphasis in body text */
  underline: 'reserved for hyperlinks',
  /** Mono font: for numeric values, data, code tokens */
  mono: 'font-telemetry class for numbers in UI',
} as const;

/* ── Quote/Testimonial Styles ────────────────── */

export const QUOTE_STYLES = {
  font: 'body',
  size: 'body',
  weight: 'regular',
  lineHeight: 'body',
  /** Italic for testimonial text */
  fontStyle: 'italic' as const,
  /** Attribution: telemetry label style */
  attribution: LABEL_STYLES.standard,
} as const;

/* ── Heading Rules ───────────────────────────── */

export const HEADING_RULES = {
  /** No trailing period on headings */
  trailingPunctuation: 'none',
  /** Monument headings: uppercase, display letter-spacing */
  monument: {
    textTransform: 'uppercase' as const,
    letterSpacing: 'display',
    lineHeight: 'display',
    fontWeight: 'bold',
  },
  /** Body headings (h3 in prose): sentence case, no letter-spacing */
  prose: {
    textTransform: 'none' as const,
    letterSpacing: '0',
    lineHeight: 'heading',
    fontWeight: 'semibold',
  },
} as const;
