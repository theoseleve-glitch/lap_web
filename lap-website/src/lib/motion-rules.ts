/**
 * Animation and motion rules — single source of truth.
 *
 * Defines allowed animation contexts, durations, and easings.
 * Enforces prefers-reduced-motion via CSS (reduced-motion.css).
 */

/** Animation duration tokens (in ms for CSS, seconds for GSAP) */
export const DURATION = {
  /** Micro interactions: hover, press, toggle — 420ms */
  micro: { css: '420ms', gsap: 0.42 },
  /** Room transitions: page/section changes — 900ms */
  room: { css: '900ms', gsap: 0.9 },
  /** Monument reveals: hero text, large elements — 1400ms */
  monument: { css: '1400ms', gsap: 1.4 },
  /** Sector gate: chapter transitions — 400ms */
  sectorGate: { css: '400ms', gsap: 0.4 },
  /** Pit: modal/panel open/close — 600ms */
  pit: { css: '600ms', gsap: 0.6 },
  /** Finish: success/completion animations — 600ms */
  finish: { css: '600ms', gsap: 0.6 },
} as const;

/** Easing tokens */
export const EASING = {
  /** Default deceleration — buttons, panels */
  inertia: { css: 'cubic-bezier(0.16, 1, 0.3, 1)', gsap: 'power3.out' },
  /** Slight bounce — playful interactions */
  overshoot: { css: 'cubic-bezier(0.34, 1.56, 0.64, 1)', gsap: 'back.out(1.7)' },
  /** Spring — drag release, snap-back */
  spring: { css: 'cubic-bezier(0.22, 1.2, 0.36, 1)', gsap: 'back.out(1.2)' },
  /** Sharp stop — closing, dismissing */
  snap: { css: 'cubic-bezier(0.7, 0, 0.84, 0)', gsap: 'power2.in' },
} as const;

/**
 * Allowed animation contexts.
 * Animations are FORBIDDEN on reading-heavy pages (pricing, terms, privacy, dpa).
 */
export const ANIMATION_ALLOWED_PAGES = [
  '/',           // home — full motion
  '/product',    // product — scroll-linked reveals
  '/customers',  // customers — proof animations
  '/demo',       // demo — interactive
] as const;

export const ANIMATION_FORBIDDEN_PAGES = [
  '/pricing',
  '/terms',
  '/privacy',
  '/dpa',
  '/subprocessors',
  '/security',
] as const;

/**
 * Motion rules summary:
 *
 * 1. prefers-reduced-motion: reduce → all animations disabled, transitions ≤ 200ms
 * 2. User toggle (.reduce-motion class on <html>) → same effect
 * 3. Mobile (< 768px): scroll pinning disabled, simplified transitions
 * 4. Reading pages: no GSAP/Three/Lenis, only CSS transitions for hover/focus
 * 5. Lenis smooth scroll: disabled on mobile + reduced motion
 * 6. Three.js scenes: frozen on reduced motion (no requestAnimationFrame loop)
 * 7. GSAP ScrollTrigger: disabled on reduced motion via ScrollTrigger.config({ autoRefreshEvents: 'none' })
 */
