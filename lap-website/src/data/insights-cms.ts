export interface InsightEntry {
  slug: string;
  title: string;
  intent: string;
  tags: string[];
  summary: string;
  relatedHref: string;
  bodyMdx: string;
}

export const insightEntries: InsightEntry[] = [
  {
    slug: 'telemetry-corner-analysis',
    title: 'Telemetry Corner Analysis for Kart Drivers',
    intent: 'corner telemetry analysis karting',
    tags: ['drivers', 'corners', 'coaching'],
    summary: 'Use entry, apex, and exit trace context to unlock repeatable lap-time gains.',
    relatedHref: '/product#key-corner-replay',
    bodyMdx:
      'Corner analysis is most useful when it gives one clear action. LAP aligns traces with track context so drivers can act quickly.',
  },
  {
    slug: 'session-vs-session-comparison',
    title: 'How Session-vs-Session Comparison Improves Race Pace',
    intent: 'session vs session motorsport analytics',
    tags: ['teams', 'progress', 'comparison'],
    summary: 'Compare sessions with confidence to verify progress and reduce inconsistency.',
    relatedHref: '/product#workflow-coverage',
    bodyMdx:
      'Comparisons expose which changes helped and which added noise, giving coaches and drivers a stable development loop.',
  },
  {
    slug: 'race-strategy-dashboard',
    title: 'Building a Race Strategy Dashboard for Endurance Teams',
    intent: 'race strategy dashboard endurance',
    tags: ['endurance', 'strategy', 'operations'],
    summary: 'Bring strategy calls, pace tracking, and pit timing into one operator-ready view.',
    relatedHref: '/product#race-strategy-dashboard',
    bodyMdx:
      'The race strategy dashboard reduces decision latency by placing stint trends and operational status in one board.',
  },
];

export const insightTags = Array.from(
  new Set(insightEntries.flatMap((entry) => entry.tags)),
).sort();
