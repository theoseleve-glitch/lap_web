// Token values exported for JS/GSAP usage (mirrors tokens.css)

export const colors = {
  asphalt: '#0B0C0F',
  concrete: '#161A20',
  chalk: '#F3F0E8',
  steel: '#8A8F98',
  acidGreen: '#B6FF2E',
  safetyRed: '#FF2A2A',
  marshalYellow: '#FFD400',
  pitOrange: '#FF6A00',
} as const;

export const timing = {
  micro: 0.42,    // 420ms in seconds (for GSAP)
  room: 0.9,      // 900ms
  monument: 1.4,  // 1400ms
} as const;

export const easing = {
  inertia: 'power3.out',            // approx cubic-bezier(0.16, 1, 0.3, 1)
  overshoot: 'back.out(1.7)',       // approx cubic-bezier(0.34, 1.56, 0.64, 1)
  spring: 'back.out(1.2)',          // approx cubic-bezier(0.22, 1.2, 0.36, 1)
  snap: 'power2.in',               // approx cubic-bezier(0.7, 0, 0.84, 0)
  anticipate: 'power2.inOut',       // approx cubic-bezier(0.45, 0, 0.55, 1)
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
