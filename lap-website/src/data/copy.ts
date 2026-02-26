// All room copy — no hardcoded strings in components

export const startGrid = {
  monument: ['EVERY LAP', 'HAS A SECRET'],
  instruction: 'HOLD TO START // 2.0s',
} as const;

export const s1Pain = {
  monument: ["YOU'RE LOSING TIME", "IN PLACES YOU CAN'T SEE"],
  body: 'Every corner has an optimal line. The difference between your line and that line is measurable, repeatable, fixable.',
  tooltips: {
    entry: 'BRAKE POINT // EARLIER = SLOWER ENTRY, TIGHTER RADIUS',
    apex: 'APEX // GEOMETRIC vs LATE — AFFECTS EXIT SPEED',
    exit: 'THROTTLE APPLICATION // EARLIER = MORE TIME GAINED',
  },
  stamp: { label: 'DATA SOURCE', detail: 'GPS + IMU @ 25Hz' },
} as const;

export const s1Deep = {
  monument: 'DATA HAS A SHAPE',
  body: 'Speed. Brake. Steering. Three traces tell the whole story. LAP reads them, maps them to your track, and finds where time hides.',
  tooltips: {
    speed: 'SPEED // 87.4 KM/H — EXIT VELOCITY, CORNER 4',
    brake: 'BRAKE // 0.94G — PEAK DECELERATION',
    steering: 'STEERING // 12.4° — LOCK ANGLE AT APEX',
  },
} as const;

export const s2Pipeline = {
  monument: 'INGEST → CLEAN → MAP → ANALYZE → REPORT',
  body: 'From raw CSV to scored report in under 60 seconds. 14 pipeline stages. Every step validated. No black boxes.',
} as const;

export const s2Proof = {
  monument: 'SCRUTINEERING',
  subhead: 'THREE PROOFS THAT THE NUMBERS ARE REAL',
  plates: [
    {
      title: 'REPEATABILITY',
      front: 'Upload the same session twice. Get the same score twice. Every time.',
      reveal: 'Scoring uses deterministic physics models. No ML randomness in the core pipeline. SHA-256 checksum verifies identical input. Reproducible to ±0.001s on lap times.',
      stamp: { label: 'VERIFIED', detail: 'DETERMINISTIC PIPELINE' },
    },
    {
      title: 'REFERENCE ACCURACY',
      front: 'Corner-by-corner analysis validated against professional data engineering methodology.',
      reveal: 'Theoretical lap computed from friction model + optimal racing line geometry. Reference speeds derived from GPS + IMU sensor fusion at 25Hz. Not arbitrary — physics-based.',
      stamp: { label: 'VALIDATED', detail: 'PHYSICS-BASED MODEL' },
    },
    {
      title: 'CONDITION SENSITIVITY',
      front: 'Wet track? New tires? Different kart? The scoring adapts. Your progress is real.',
      reveal: 'Phase-aware scoring detects grip evolution. Wet/dry thresholds adjust expectations. Kart-specific profiles normalize comparisons. Detrending only applied when it helps — never hurts.',
      stamp: { label: 'CALIBRATED', detail: 'CONDITION-AWARE' },
    },
  ],
} as const;

export const s3Product = {
  monument: 'FIND TIME.',
  b2c: {
    subhead: 'FOR KART, CAR & SIM DRIVERS',
    tiles: [
      { label: 'YOUR SCORE: 86/A', detail: '4-pillar breakdown visible' },
      { label: 'CORNER 7: BRAKE 0.4s LATE', detail: 'Specific, actionable coaching' },
      { label: 'NEXT SESSION: 3 DRILLS', detail: 'Development plan generated' },
    ],
  },
  b2b: {
    subhead: 'FOR CIRCUITS, SCHOOLS & ORGANIZERS',
    placards: [
      { title: 'BRANDED REPORTS', body: 'Your logo. Your colors. Every driver gets a professional debrief after every session.' },
      { title: 'DRIVER RETENTION', body: 'Drivers who see progress come back. Average +40% return rate with data programs.' },
      { title: 'TIMING INTEGRATION', body: 'Connects to your existing timing system. No new hardware. No driver friction.' },
      { title: 'TURNKEY SETUP', body: 'We configure everything. You run events. Pilot program available.' },
    ],
    cta: 'REQUEST PILOT EVENT',
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
    '99.9% UPTIME',
    'MADE IN FRANCE',
  ],
} as const;

export const garage = {
  monument: 'GARAGE',
  subhead: 'TECHNICAL DOCUMENTATION // FOR SKEPTICS',
  panels: [
    {
      title: 'STACK',
      content: 'Python 3.x // Flask // pandas // scikit-learn\nPostgreSQL // Redis // Celery\n14-stage pipeline // Physics-based models\nPyInstaller desktop builds',
    },
    {
      title: 'DATA SOURCES',
      content: 'RaceChrono Pro (CSV export)\nRaceBox (via RaceChrono format)\nGPS + IMU @ 10-25Hz\nStreaming ingest for files up to 12GB\nAdaptive chunking — <1GB peak memory',
    },
    {
      title: 'METHODOLOGY',
      content: 'Scoring: Pace + Consistency + Execution + Robustness\nCorner analysis: brake point, apex speed, exit drive\nReference lap: friction model + optimal geometry\nDetrending: condition-aware, only applied when beneficial\nConfidence weighting: data quality affects score range',
    },
    {
      title: 'PRIVACY & COMPLIANCE',
      content: 'GDPR-ready: data stored in EU\nEncryption: AES-256 at rest, TLS in transit\nRetention: you choose — 30 days to forever\nDeletion: full account + data wipe on request\nAudit trail: every pipeline run logged\nData ownership: 100% yours. Export anytime. No lock-in.',
    },
  ],
} as const;

export const podium = {
  monument: ['READY TO RUN', 'A CLEAN LAP?'],
  ctaPrimary: 'TRY DEMO',
  ctaSecondary: 'TALK',
  subtext: 'FREE STARTER PLAN // NO CARD REQUIRED // 60 SECONDS TO FIRST SCORE',
  restart: '← RESTART LAP',
} as const;
