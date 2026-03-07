/**
 * Brand asset rules — OG cards, favicons, imagery, logos, premium accent.
 *
 * Single source of truth for brand governance tokens.
 */

// ── OG Card Templates ──────────────────────────────────────────────
export const ogCard = {
  width: 1200,
  height: 630,
  bg: '#000000',
  text: '#F0EDE5',
  accent: '#C9A84C',
  fontFamily: 'var(--font-display)', // token-ok
  /** Per-page OG template overrides */
  templates: {
    home: { title: 'Lap Coach', subtitle: 'Motorsport telemetry for everyone' },
    pricing: { title: 'Plans & Pricing', subtitle: 'From karting to GT racing' },
    product: { title: 'Product', subtitle: 'Data-driven lap improvement' },
    customers: { title: 'Customers', subtitle: 'Teams using Lap Coach' },
  } as Record<string, { title: string; subtitle: string }>,
} as const;

// ── Favicon / Touch Icons ───────────────────────────────────────────
export const favicon = {
  /** Standard favicon sizes */
  sizes: [16, 32, 48, 180, 192, 512],
  /** Monochrome variant for dark/light OS themes */
  monochrome: { light: '#000000', dark: '#F0EDE5' },
  /** Apple touch icon uses brand color bg */
  appleBg: '#000000',
} as const;

// ── Imagery Framing ────────────────────────────────────────────────
export const imagery = {
  /** Screenshot frame: shadow + radius + bg */
  screenshotFrame: {
    shadow: 'var(--shadow-e3)',
    radius: 'var(--radius-3)',
    bg: 'var(--concrete)',
    padding: 8,
  },
  /** Trust / partner logo grid */
  logoGrid: {
    maxHeight: 28,
    opacity: 0.5,
    hoverOpacity: 0.9,
    gap: 'var(--space-6)',
    filter: 'grayscale(1)',
    hoverFilter: 'grayscale(0)',
  },
} as const;

// ── Premium Accent Governance ───────────────────────────────────────
export const premiumAccent = {
  color: '#C9A84C',
  cssVar: 'var(--pit-orange)',
  /** Components where gold accent is allowed */
  allowedComponents: [
    'PitButton',
    'PricingTable (Pro tier badge)',
    'OG card accent line',
    'Podium room highlights',
    'beam-card border animation',
  ],
  /** Max gold elements per page: 3 */
  maxPerPage: 3,
} as const;
