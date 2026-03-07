/**
 * OG card design system — per-page OG image templates with tokens.
 *
 * Each page type gets a standardized OG card layout:
 *   - Background: asphalt (#000)
 *   - Brand mark: top-left corner
 *   - Title: monument font, chalk color
 *   - Subtitle: body font, steel color
 *   - Accent bar: 4px left border in page accent color
 *
 * Usage: import the template config for dynamic OG image generation.
 */

export interface OgTemplate {
  pageType: string;
  title: string;
  subtitle?: string;
  accentColor: string;
  layout: 'default' | 'stats' | 'comparison';
}

export const OG_DEFAULTS = {
  width: 1200,
  height: 630,
  fontFamily: {
    title: 'Space Grotesk',
    body: 'Inter',
    data: 'Space Mono',
  },
  colors: {
    bg: '#000000',
    title: '#F0EDE5',
    subtitle: '#888888',
    brand: '#C9A84C',
  },
  padding: 64,
} as const;

export const OG_TEMPLATES: Record<string, OgTemplate> = {
  home: {
    pageType: 'home',
    title: 'LAP',
    subtitle: 'Motorsport telemetry analysis',
    accentColor: '#C9A84C',
    layout: 'default',
  },
  product: {
    pageType: 'product',
    title: 'Product',
    subtitle: 'From CSV to coaching report in seconds',
    accentColor: '#22C55E',
    layout: 'default',
  },
  pricing: {
    pageType: 'pricing',
    title: 'Pricing',
    subtitle: 'Plans for drivers, teams, and venues',
    accentColor: '#C9A84C',
    layout: 'default',
  },
  session: {
    pageType: 'session',
    title: 'Session Analysis',
    accentColor: '#22C55E',
    layout: 'stats',
  },
  compare: {
    pageType: 'compare',
    title: 'Session Comparison',
    accentColor: '#FACC15',
    layout: 'comparison',
  },
} as const;

/**
 * Favicon configuration.
 * Monochrome variants for different contexts.
 */
export const FAVICON_CONFIG = {
  /** Standard favicon — SVG for modern browsers */
  svg: '/favicon.svg',
  /** Fallback PNG favicons */
  png: {
    '16': '/favicon-16x16.png',
    '32': '/favicon-32x32.png',
    '192': '/android-chrome-192x192.png',
    '512': '/android-chrome-512x512.png',
  },
  /** Apple touch icon (180x180) */
  apple: '/apple-touch-icon.png',
  /** Theme color for browser chrome */
  themeColor: '#000000',
} as const;
