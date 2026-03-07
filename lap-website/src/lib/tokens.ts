// Token values exported for JS/GSAP usage (mirrors tokens.css)

export const colors = {
  asphalt: '#000000',
  concrete: '#141414',
  chalk: '#F0EDE5',
  steel: '#888888',
  acidGreen: '#F0EDE5',
  safetyRed: '#FF2A2A',
  marshalYellow: '#F0EDE5',
  pitOrange: '#C9A84C',
  racingPurple: '#C9A84C',
} as const;

export const timing = {
  micro: 0.42,    // 420ms in seconds (for GSAP)
  room: 0.9,      // 900ms
  monument: 1.4,  // 1400ms
  sectorGate: 0.4, // 400ms
  drs: 2.0,        // 2000ms
  pit: 0.6,        // 600ms
  finish: 0.6,     // 600ms
} as const;

export const easing = {
  inertia: 'power3.out',            // approx cubic-bezier(0.16, 1, 0.3, 1)
  overshoot: 'back.out(1.7)',       // approx cubic-bezier(0.34, 1.56, 0.64, 1)
  spring: 'back.out(1.2)',          // approx cubic-bezier(0.22, 1.2, 0.36, 1)
  snap: 'power2.in',               // approx cubic-bezier(0.7, 0, 0.84, 0)
  anticipate: 'power2.inOut',       // approx cubic-bezier(0.45, 0, 0.55, 1)
  sectorGate: 'power4.out',    // approx cubic-bezier(0.0, 0, 0.2, 1)
  pitEnter: 'power2.in',       // approx cubic-bezier(0.8, 0, 1, 1)
  pitExit: 'power4.out',       // approx cubic-bezier(0, 0, 0.2, 1)
} as const;

export const roomAccents: Record<string, string> = {
  'start-grid': 'none',
  's1-pain': 'green',
  's1-deep': 'green',
  's2-pipeline': 'yellow',
  's2-proof': 'yellow',
  's3-product': 'green',     // switches to yellow in B2B mode
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

// Sector gate triggers: chapter index → sector ID completed
export const sectorGates: Record<number, string> = {
  1: 'S1',     // Start Grid → S1 Pain
  3: 'S2',     // S1 Deep → S2 Pipeline
  5: 'S3',     // S2 Proof → S3 Product
  8: 'PIT',    // S5 Personas → Pit Stop
  10: 'FINISH', // Garage → Podium
} as const;

// Sector tab entries (deduplicated for display)
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

export const elevation = {
  e0: 'var(--shadow-e0)',
  e1: 'var(--shadow-e1)',
  e2: 'var(--shadow-e2)',
  e3: 'var(--shadow-e3)',
  e4: 'var(--shadow-e4)',
} as const;

export const radius = {
  r0: 0,
  r1: 4,
  r2: 8,
  r3: 12,
  r4: 16,
  full: 9999,
} as const;

export const border = {
  default: 1,
  thick: 2,
} as const;

export const semantic = {
  success: '#22C55E',
  warning: '#FACC15',
  error: '#FF2A2A',
  info: '#8B5CF6',
  brand: '#C9A84C',
} as const;

export const chartPalette = [
  '#22C55E', '#3B82F6', '#F59E0B', '#EF4444', '#A78BFA', '#EC4899',
] as const;
