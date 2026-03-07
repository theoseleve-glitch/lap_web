/**
 * Imagery system — standardized framing, trust badges, partner logos.
 *
 * Tokens for consistent screenshot/image treatment across marketing pages.
 */

/** Screenshot frame tokens */
export const SCREENSHOT_FRAME = {
  /** Background behind screenshot */
  bgColor: 'var(--concrete)',
  /** Border radius of frame */
  radius: 'var(--radius-3)',       // 12px
  /** Shadow elevation for floating screenshots */
  shadow: 'var(--shadow-e3)',
  /** Padding inside frame (browser-chrome style) */
  padding: '8px',
  /** Dot radius for fake browser chrome */
  chromeDotSize: '6px',
} as const;

/** Trust badge / partner logo grid tokens */
export const LOGO_GRID = {
  /** Max logo height */
  maxHeight: '32px',
  /** Opacity for inactive state */
  opacity: 0.5,
  /** Opacity on hover */
  hoverOpacity: 0.8,
  /** Gap between logos */
  gap: 'var(--space-6)',           // 48px
  /** Grayscale filter for inactive state */
  filter: 'grayscale(100%)',
  /** Grayscale filter on hover */
  hoverFilter: 'grayscale(0%)',
} as const;

/**
 * Premium accent (gold) governance.
 *
 * Gold (#C9A84C / --pit-orange) may ONLY be used in:
 *   - Primary CTA buttons (PitButton)
 *   - Brand mark / wordmark
 *   - Beam card border animation
 *   - Active nav indicator
 *   - Section divider accents (max 1 per page)
 *   - OG card accent bar
 *
 * Gold must NOT be used for:
 *   - Body text
 *   - Background fills (except small accents)
 *   - Status indicators (use semantic colors)
 *   - Data visualization (use chart palette)
 */
export const PREMIUM_ACCENT_COMPONENTS = [
  'PitButton',
  'Wordmark',
  'beam-card',
  'nav-indicator',
  'section-divider',
  'og-accent',
] as const;
