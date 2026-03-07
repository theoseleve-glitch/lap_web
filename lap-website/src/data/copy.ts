// Central copy used across immersive home rooms.

export const startGrid = {
  monument: ['EVERY LAP', 'HAS A SECRET'],
  instruction: 'HOLD TO START // 2.0s',
} as const;

export const s1Pain = {
  monument: ["YOU'RE LOSING TIME", "IN PLACES YOU CAN'T SEE"],
  body: 'LAP pinpoints exactly where you lose speed, then turns each corner into one clear next action for your next session.',
  tooltips: {
    entry: 'BRAKE POINT // Adjust this first for cleaner rotation',
    apex: 'APEX // Better apex means faster exit every lap',
    exit: 'THROTTLE // Earlier confidence = immediate lap-time gain',
  },
  stamp: { label: 'DATA SOURCE', detail: 'GPS + IMU @ 25Hz' },
} as const;

export const s1Deep = {
  monument: 'DATA HAS A SHAPE',
  body: 'Three traces show the full story: where you are stable, where you overwork the kart, and where easy time is available.',
  tooltips: {
    speed: 'SPEED // Exit velocity opportunity',
    brake: 'BRAKE // Peak deceleration and release timing',
    steering: 'STEERING // Lock angle at apex and unwind phase',
  },
} as const;

export const s2Pipeline = {
  monument: 'INGEST -> CLEAN -> MAP -> ANALYZE -> REPORT',
  body: 'Upload session data and get an actionable scorecard in under a minute, with a workflow your coaches and drivers can trust.',
} as const;

export const s2Proof = {
  monument: 'SCRUTINEERING',
  subhead: 'THREE PROOFS YOUR SCORE REFLECTS REAL PROGRESS',
  plates: [
    {
      title: 'REPEATABLE',
      front: 'Run the same session twice and you get the same result.',
      reveal: 'The scoring pipeline is deterministic and checksum-verified, so identical input produces identical output.',
      stamp: { label: 'VERIFIED', detail: 'CONSISTENT OUTPUT' },
    },
    {
      title: 'REALISTIC',
      front: 'Reference pace is physics-based, not arbitrary.',
      reveal: 'Corner expectations are derived from vehicle behavior and track geometry, so coaching stays grounded in race reality.',
      stamp: { label: 'VALIDATED', detail: 'PHYSICS MODEL' },
    },
    {
      title: 'CONTEXT-AWARE',
      front: 'Grip, weather, and setup changes are recognized.',
      reveal: 'Condition-aware adjustments keep progress tracking fair from session to session and weekend to weekend.',
      stamp: { label: 'CALIBRATED', detail: 'SESSION CONTEXT' },
    },
  ],
} as const;

export const s3Product = {
  monument: 'FIND TIME.',
  coaching: {
    subhead: 'COACHING MODE',
    tagline: 'Post-session. Find where you lost time.',
    tiles: [
      { label: 'YOUR SCORE: CLEAR', detail: 'Understand pace, consistency, execution, and confidence at a glance' },
      { label: 'KEY CORNER: TARGETED', detail: 'Fix the exact corner phase costing your lap time' },
      { label: 'NEXT SESSION: READY', detail: 'Leave with drills you can apply immediately on track' },
    ],
  },
  strategy: {
    subhead: 'STRATEGY MODE',
    tagline: 'Pre-event. Plan how you\'ll gain it back.',
    tiles: [
      { label: 'RACE PLAN: SET', detail: 'Build stint plans, pit windows, and fuel strategies before the green flag' },
      { label: 'LIVE PACE: MONITORED', detail: 'Track every driver\'s pace delta and stint health in real time' },
      { label: 'PIT CALLS: CONFIDENT', detail: 'Data-backed pit decisions with projected outcomes' },
    ],
  },
} as const;

export const pitStop = {
  monument: 'PIT STOP',
  subhead: 'PRICING // DEMO // CONTACT',
  riskReversal: [
    '30-DAY MONEY BACK',
    'CANCEL ANYTIME',
    'YOUR DATA, ALWAYS',
    'EXPORT EVERYTHING',
    'GDPR COMPLIANT',
    'NO LOCK-IN',
  ],
  trustStrip: [
    'GDPR READY',
    '256-BIT ENCRYPTED',
    '99.9% UPTIME TARGET',
    'MOTORSPORT-FOCUSED',
  ],
} as const;

export const garage = {
  monument: 'GARAGE',
  subhead: 'TECHNICAL NOTES // FOR OPERATORS AND ANALYSTS',
  panels: [
    {
      title: 'STACK',
      content: 'Next.js + telemetry backend services\nValidated processing pipeline\nDeterministic report generation\nOperational APIs for billing and lead flows',
    },
    {
      title: 'DATA SOURCES',
      content: 'RaceChrono-compatible session ingest\nGPS + IMU data streams\nLarge-file support with chunked processing\nStable memory usage for long sessions',
    },
    {
      title: 'METHODOLOGY',
      content: 'Scoring: pace + consistency + execution + robustness\nCorner analysis: entry, apex, exit phases\nReference lap: physics + geometry model\nConfidence weighting by signal quality',
    },
    {
      title: 'PRIVACY & COMPLIANCE',
      content: 'EU-ready residency controls\nEncryption at rest and in transit\nRetention windows per workspace\nFull deletion/export support\nAudit logs for workflow traceability',
    },
  ],
} as const;

export const podium = {
  monument: ['READY TO RUN', 'A CLEAN LAP?'],
  ctaPrimary: 'TRY DEMO',
  ctaSecondary: 'TALK',
  subtext: 'START FREE // NO CARD REQUIRED // FIRST OUTCOME IN MINUTES',
  restart: '<- RESTART LAP',
} as const;
