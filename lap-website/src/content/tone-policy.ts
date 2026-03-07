/**
 * Persona tone policy.
 *
 * Default: single voice (direct, confident, technical-but-accessible).
 * Per-persona tone variants allowed ONLY when:
 *   1. Persona has distinct buying context AND
 *   2. Copy differs meaningfully (not just synonym swaps)
 *
 * Rule: max 2 tone variants per page.
 *
 * Designated persona-specific pages (tone variants allowed):
 *   - / (home): kart_driver (default), venue_operator
 *   - /product: kart_driver (default), endurance_strategist
 *   - /pricing: shared (no variants)
 *   - /customers: junior_coach (default), venue_operator
 *   - /contact: shared (no variants)
 *
 * All other pages: use base tone only.
 */

export type ToneVariant = 'base' | 'venue' | 'endurance' | 'coach';

export interface ToneConfig {
  page: string;
  allowedVariants: ToneVariant[];
  defaultVariant: ToneVariant;
}

export const TONE_CONFIGS: ToneConfig[] = [
  { page: '/', allowedVariants: ['base', 'venue'], defaultVariant: 'base' },
  { page: '/product', allowedVariants: ['base', 'endurance'], defaultVariant: 'base' },
  { page: '/pricing', allowedVariants: ['base'], defaultVariant: 'base' },
  { page: '/customers', allowedVariants: ['base', 'coach'], defaultVariant: 'base' },
  { page: '/contact', allowedVariants: ['base'], defaultVariant: 'base' },
];

export const MAX_VARIANTS_PER_PAGE = 2;

export function getAllowedVariants(page: string): ToneVariant[] {
  const config = TONE_CONFIGS.find((c) => c.page === page);
  return config?.allowedVariants ?? ['base'];
}

export function isToneAllowed(page: string, variant: ToneVariant): boolean {
  const allowed = getAllowedVariants(page);
  return allowed.includes(variant);
}
