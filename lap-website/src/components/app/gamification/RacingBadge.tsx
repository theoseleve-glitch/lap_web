'use client';

/* ── Types ────────────────────────────────────────────────── */

interface RacingBadgeProps {
  title: string;
  description: string;
  unlocked: boolean;
  category?: 'progress' | 'technique' | 'consistency' | 'learning' | 'endurance';
}

const categoryColors: Record<string, string> = {
  progress: '#C9A84C',    // gold
  technique: '#22C55E',   // acid-green
  consistency: '#FACC15', // marshal-yellow
  learning: '#8B5CF6',    // racing-purple
  endurance: '#FF2A2A',   // safety-red
};

/* ── Badge Icons ──────────────────────────────────────────── */

function BadgeIcon({ title, color, unlocked }: { title: string; color: string; unlocked: boolean }) {
  const fill = unlocked ? color : '#949494';
  const opacity = unlocked ? 1 : 0.3;
  const size = 28;

  const icons: Record<string, JSX.Element> = {
    /* === PROGRESS & MILESTONES === */
    'First Lap': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <text x="12" y="16" textAnchor="middle" fill={fill} fontSize="10" fontWeight="bold">1</text>
      </svg>
    ),
    'Session Starter': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <polygon points="10,8 17,12 10,16" fill={fill} />
      </svg>
    ),
    'Data Rookie': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 3L8 7h3v6h2V7h3L12 3z" fill={fill} />
        <rect x="5" y="16" width="3" height="5" rx="0.5" fill={fill} opacity={0.6} />
        <rect x="10.5" y="14" width="3" height="7" rx="0.5" fill={fill} opacity={0.8} />
        <rect x="16" y="17" width="3" height="4" rx="0.5" fill={fill} opacity={0.5} />
      </svg>
    ),
    'Clean Driver': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M9 12l2 2 4-4" stroke={fill} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <circle cx="19" cy="5" r="1.5" fill={fill} />
      </svg>
    ),
    'Hotlap Hunter': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 2C8 7 5 10 5 14a7 7 0 0014 0c0-4-3-7-7-12z" fill={fill} opacity={0.3} />
        <path d="M12 8c-2 3-4 5-4 7a4 4 0 008 0c0-2-2-4-4-7z" fill={fill} />
      </svg>
    ),
    'Delta Chaser': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 4L4 20h16L12 4z" stroke={fill} strokeWidth="2" fill="none" />
        <path d="M12 10v5m0 0l-2-2m2 2l2-2" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    'Tenths Collector': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="13" r="8" stroke={fill} strokeWidth="2" />
        <path d="M12 5V3M10 3h4" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <text x="12" y="16" textAnchor="middle" fill={fill} fontSize="7" fontWeight="bold">.1</text>
      </svg>
    ),
    'Half-Second Hero': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="13" r="8" stroke={fill} strokeWidth="2" />
        <path d="M12 5V3M10 3h4" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <text x="12" y="16" textAnchor="middle" fill={fill} fontSize="7" fontWeight="bold">.5</text>
      </svg>
    ),
    'Second Slayer': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="13" r="8" stroke={fill} strokeWidth="2" />
        <path d="M12 5V3M10 3h4" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <text x="12" y="16" textAnchor="middle" fill={fill} fontSize="7" fontWeight="bold">1s</text>
        <path d="M17 5l3-3" stroke={fill} strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),

    /* === TECHNIQUE & DRIVING QUALITY === */
    'Brake Marker': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <circle cx="12" cy="12" r="4" stroke={fill} strokeWidth="2" />
        <circle cx="12" cy="3" r="1.5" fill={fill} />
        <line x1="12" y1="3" x2="12" y2="8" stroke={fill} strokeWidth="1.5" />
      </svg>
    ),
    'Late Braker': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <rect x="4" y="4" width="6" height="16" rx="1" stroke={fill} strokeWidth="2" />
        <rect x="14" y="4" width="6" height="16" rx="1" stroke={fill} strokeWidth="2" />
        <path d="M10 9h4M10 12h4M10 15h4" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
        <path d="M12 19l-2 2m2-2l2 2" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    'Trail Braker': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M4 18C4 18 8 6 12 6s8 12 8 12" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <circle cx="6" cy="15" r="1.5" fill={fill} opacity={1} />
        <circle cx="9" cy="10" r="1.2" fill={fill} opacity={0.7} />
        <circle cx="12" cy="7" r="1" fill={fill} opacity={0.4} />
      </svg>
    ),
    'Smooth Hands': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M2 12C4 8 6 8 8 12s4 4 4 0 2-4 4 0 2 4 4 0" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <circle cx="4" cy="4" r="2" stroke={fill} strokeWidth="1.5" />
        <circle cx="4" cy="4" r="0.5" fill={fill} />
      </svg>
    ),
    'Throttle Artist': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M3 20C3 20 6 18 9 14s4-6 6-8c2-2 3-3 6-4" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M18 4l2-1m-2 1l1 2" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    'Early On Power': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M13 2L4 14h6l-1 8 9-12h-6l1-8z" fill={fill} />
      </svg>
    ),
    'Apex Hunter': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M20 4L12 12 4 20" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <circle cx="12" cy="12" r="4" stroke={fill} strokeWidth="1.5" />
        <circle cx="12" cy="12" r="1" fill={fill} />
        <path d="M12 6V8M12 16v2M6 12H8M16 12h2" stroke={fill} strokeWidth="1" strokeLinecap="round" />
      </svg>
    ),
    'Exit Maximizer': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M4 20Q4 12 12 12h6" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M16 8l4 4-4 4" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    'Minimum Speed Master': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M4 18a9 9 0 0118 0" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M12 18l-4-6" stroke={fill} strokeWidth="2.5" strokeLinecap="round" />
        <circle cx="12" cy="18" r="2" fill={fill} />
      </svg>
    ),
    'Weight Transfer Wizard': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 3v16" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M5 7l7-2 7 2" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M3 13l2-6 2 6a2 2 0 01-4 0zM17 13l2-6 2 6a2 2 0 01-4 0z" fill={fill} opacity={0.4} stroke={fill} strokeWidth="1.5" />
        <path d="M8 21h8" stroke={fill} strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),

    /* === CONSISTENCY & DISCIPLINE === */
    'Metronome': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M8 22l4-18 4 18" stroke={fill} strokeWidth="2" strokeLinejoin="round" />
        <path d="M12 8l5-4" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <circle cx="17" cy="4" r="1.5" fill={fill} />
        <path d="M6 22h12" stroke={fill} strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),
    'Consistent One': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M2 12h4l2-3 2 6 2-6 2 3h8" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    'No Excuses': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" stroke={fill} strokeWidth="2" />
        <circle cx="12" cy="12" r="3" fill={fill} />
      </svg>
    ),
    'Repeatable Pace': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M17 2l3 3-3 3" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M4 5h16" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M7 22l-3-3 3-3" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M20 19H4" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M7 12h10" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeDasharray="2 2" />
      </svg>
    ),
    'Zero Drama': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <path d="M8 12h8" stroke={fill} strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),
    'Precision Driver': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="1.5" />
        <circle cx="12" cy="12" r="6" stroke={fill} strokeWidth="1.5" />
        <circle cx="12" cy="12" r="3" stroke={fill} strokeWidth="1.5" />
        <circle cx="12" cy="12" r="1" fill={fill} />
      </svg>
    ),
    'Discipline Over Heroics': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M3 20L9 14l4 2 8-10" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="3" y="18" width="2" height="4" fill={fill} opacity={0.3} />
        <rect x="8" y="14" width="2" height="8" fill={fill} opacity={0.5} />
        <rect x="13" y="11" width="2" height="11" fill={fill} opacity={0.7} />
        <rect x="18" y="7" width="2" height="15" fill={fill} opacity={0.9} />
      </svg>
    ),
    'Pressure Proof': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 2l8 8-8 12-8-12 8-8z" stroke={fill} strokeWidth="2" fill={fill} fillOpacity={0.15} />
        <path d="M4 10h16" stroke={fill} strokeWidth="1.5" />
        <path d="M8 10l4 12 4-12" stroke={fill} strokeWidth="1.5" />
      </svg>
    ),
    'One More Lap': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M4 3v18" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <rect x="4" y="3" width="12" height="9" stroke={fill} strokeWidth="1.5" />
        <rect x="4" y="3" width="4" height="3" fill={fill} />
        <rect x="12" y="3" width="4" height="3" fill={fill} />
        <rect x="8" y="6" width="4" height="3" fill={fill} />
        <rect x="4" y="9" width="4" height="3" fill={fill} />
        <rect x="12" y="9" width="4" height="3" fill={fill} />
        <circle cx="19" cy="17" r="4" stroke={fill} strokeWidth="1.5" />
        <path d="M19 15v4M17 17h4" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    'Recovery Specialist': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M4 18l4-8 4 6 4-10 4 6" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M18 8l2 4 2-2" stroke={fill} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    'Stable Platform': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <rect x="3" y="6" width="18" height="3" rx="1" fill={fill} opacity={0.4} />
        <rect x="3" y="11" width="18" height="3" rx="1" fill={fill} opacity={0.7} />
        <rect x="3" y="16" width="18" height="3" rx="1" fill={fill} />
      </svg>
    ),

    /* === TRACK LEARNING & ANALYSIS === */
    'Track Scout': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <polygon points="16,6 10,10 8,18 14,14" fill={fill} fillOpacity={0.5} stroke={fill} strokeWidth="1" />
        <circle cx="12" cy="12" r="1.5" fill={fill} />
      </svg>
    ),
    'Corner Student': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M2 4l10 2 10-2v15l-10 2-10-2V4z" stroke={fill} strokeWidth="1.5" />
        <path d="M12 6v15" stroke={fill} strokeWidth="1.5" />
        <path d="M6 10q2 0 2 2t2 2" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    'Track Mapper': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <rect x="3" y="3" width="18" height="18" rx="2" stroke={fill} strokeWidth="2" />
        <path d="M7 7C7 7 10 7 12 10s5 7 5 7" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <circle cx="7" cy="7" r="1.5" fill={fill} />
        <circle cx="17" cy="17" r="1.5" fill={fill} />
      </svg>
    ),
    'Reference Builder': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M3 20L21 4" stroke={fill} strokeWidth="1.5" strokeDasharray="3 2" />
        <circle cx="5" cy="18" r="2.5" fill={fill} />
        <circle cx="10" cy="13" r="2" fill={fill} opacity={0.8} />
        <circle cx="15" cy="8" r="2" fill={fill} opacity={0.6} />
        <circle cx="20" cy="4" r="1.5" fill={fill} opacity={0.4} />
      </svg>
    ),
    'Sector Surgeon': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <path d="M12 3v9l7 5" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M12 12l-6 7" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
        <path d="M12 3a9 9 0 015.5 2.5L12 12V3z" fill={fill} opacity={0.4} />
      </svg>
    ),
    'Line Detective': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="10" cy="10" r="7" stroke={fill} strokeWidth="2" />
        <path d="M15 15l6 6" stroke={fill} strokeWidth="2.5" strokeLinecap="round" />
        <path d="M7 10q3-4 6 0" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    'Telemetry Explorer': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M3 3v18h18" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M6 15l4-4 3 2 5-7" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M6 18l4-2 3-1 5-3" stroke={fill} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity={0.5} />
      </svg>
    ),
    'Compare Mode': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M3 16l4-4 4 2 4-6 4 2" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M3 18l4-2 4 1 4-4 4 1" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" opacity={0.4} strokeDasharray="3 2" />
      </svg>
    ),
    'Theory to Track': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M9 21h6M10 18h4" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
        <path d="M12 2a7 7 0 00-3 13.3V17h6v-1.7A7 7 0 0012 2z" fill={fill} fillOpacity={0.2} stroke={fill} strokeWidth="1.5" />
        <path d="M10 11l2 2 3-3" stroke={fill} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    'Lesson Locked In': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <rect x="5" y="11" width="14" height="10" rx="2" stroke={fill} strokeWidth="2" />
        <path d="M8 11V7a4 4 0 018 0v4" stroke={fill} strokeWidth="2" />
        <path d="M12 14l1.5 1-0.5 1.5L12 18l-1-1.5-0.5-1.5z" fill={fill} />
      </svg>
    ),

    /* === ENDURANCE & RACECRAFT === */
    'Stint Manager': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <path d="M12 6v6l4 3" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M12 3v1M21 12h-1M12 21v-1M3 12h1" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    'Endurance Mindset': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M8 12c-2-2-4-2-4 0s2 4 4 2l4-4c2-2 4-2 4 0s-2 4-4 2l-4-4z" stroke={fill} strokeWidth="2.5" strokeLinecap="round" />
      </svg>
    ),
    'Tire Whisperer': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <circle cx="12" cy="12" r="4" stroke={fill} strokeWidth="2" />
        <path d="M12 3v5M12 16v5M3 12h5M16 12h5M5.6 5.6l3.6 3.6M14.8 14.8l3.6 3.6M5.6 18.4l3.6-3.6M14.8 9.2l3.6-3.6" stroke={fill} strokeWidth="1" />
      </svg>
    ),
    'Fuel Saver': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 2C8 8 5 12 5 16a7 7 0 0014 0c0-4-3-8-7-14z" fill={fill} fillOpacity={0.3} stroke={fill} strokeWidth="2" />
        <path d="M10 16a2 2 0 004 0c0-1-1-3-2-5-1 2-2 4-2 5z" fill={fill} />
      </svg>
    ),
    'Traffic Navigator': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <rect x="3" y="6" width="5" height="3" rx="1" fill={fill} opacity={0.4} />
        <rect x="16" y="10" width="5" height="3" rx="1" fill={fill} opacity={0.4} />
        <rect x="5" y="15" width="5" height="3" rx="1" fill={fill} opacity={0.4} />
        <path d="M10 12C12 8 14 8 16 12s4 6 6 4" stroke={fill} strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),
    'Racecraft Ready': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M4 3v18" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <rect x="4" y="3" width="16" height="12" stroke={fill} strokeWidth="1.5" />
        <rect x="4" y="3" width="4" height="4" fill={fill} />
        <rect x="12" y="3" width="4" height="4" fill={fill} />
        <rect x="8" y="7" width="4" height="4" fill={fill} />
        <rect x="16" y="7" width="4" height="4" fill={fill} />
        <rect x="4" y="11" width="4" height="4" fill={fill} />
        <rect x="12" y="11" width="4" height="4" fill={fill} />
      </svg>
    ),
    'Closer': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M20 3v18" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M20 5h-4v4h4v4h-4v4h4" stroke={fill} strokeWidth="1" />
        <path d="M5 8l4-2-1 5 4-2-5 8" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    'Iron Focus': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" stroke={fill} strokeWidth="2" />
        <circle cx="12" cy="12" r="3" fill={fill} />
        <path d="M12 2v3M12 19v3M2 12h2M20 12h2" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    'Team Player': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="8" cy="7" r="3" fill={fill} opacity={0.7} />
        <circle cx="16" cy="7" r="3" fill={fill} opacity={0.7} />
        <path d="M2 20c0-3 3-6 6-6 1.5 0 2.5.5 3 1" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M22 20c0-3-3-6-6-6-1.5 0-2.5.5-3 1" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M10 16l2 2 2-2" stroke={fill} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    'Lap Coach Certified': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M6 2l2 5h8l2-5" stroke={fill} strokeWidth="2" strokeLinejoin="round" />
        <path d="M8 7v5a4 4 0 008 0V7" stroke={fill} strokeWidth="2" />
        <path d="M4 7h4M16 7h4" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M4 7c-1 0-2 1-2 3s1 3 2 3" stroke={fill} strokeWidth="1.5" />
        <path d="M20 7c1 0 2 1 2 3s-1 3-2 3" stroke={fill} strokeWidth="1.5" />
        <path d="M10 17v2h4v-2" stroke={fill} strokeWidth="2" />
        <path d="M8 21h8" stroke={fill} strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),

    /* === BACKEND ACHIEVEMENT LABELS (driver_achievements.py) === */
    'First Laps': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M5 3v18" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M5 3h10l-3 4 3 4H5" fill={fill} fillOpacity={0.3} stroke={fill} strokeWidth="2" strokeLinejoin="round" />
      </svg>
    ),
    'First Steps': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M9 4a2 2 0 014 0v3a2 2 0 01-4 0V4z" fill={fill} opacity={0.6} />
        <path d="M11 12a2 2 0 014 0v3a2 2 0 01-4 0v-3z" fill={fill} opacity={0.8} />
        <path d="M8 19a2 2 0 014 0v1a2 2 0 01-4 0v-1z" fill={fill} />
        <circle cx="11" cy="2" r="1" fill={fill} opacity={0.4} />
        <circle cx="13" cy="10" r="1" fill={fill} opacity={0.6} />
      </svg>
    ),
    'Getting Serious': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 2C8 7 5 10 5 14a7 7 0 0014 0c0-4-3-7-7-12z" fill={fill} opacity={0.3} />
        <path d="M12 8c-2 3-4 5-4 7a4 4 0 008 0c0-2-2-4-4-7z" fill={fill} />
        <path d="M11 14h2v3h-2z" fill={fill} opacity={0.5} />
      </svg>
    ),
    'Century Club': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <text x="12" y="16" textAnchor="middle" fill={fill} fontSize="9" fontWeight="bold">100</text>
      </svg>
    ),
    'Track Warrior': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 2l2 4h4l-3 3 1 5-4-2-4 2 1-5-3-3h4l2-4z" fill={fill} />
        <path d="M7 18l5-4 5 4" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M9 22h6" stroke={fill} strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),
    'Lap Legend': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M5 16l3-7h8l3 7-3 4H8l-3-4z" fill={fill} fillOpacity={0.3} stroke={fill} strokeWidth="2" strokeLinejoin="round" />
        <path d="M8 12h8M9 16h6" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="12" cy="6" r="3" fill={fill} opacity={0.6} />
      </svg>
    ),
    'Regular Driver': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <rect x="3" y="4" width="18" height="16" rx="2" stroke={fill} strokeWidth="2" />
        <path d="M3 9h18" stroke={fill} strokeWidth="2" />
        <path d="M8 4V2M16 4V2" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <rect x="7" y="12" width="3" height="3" rx="0.5" fill={fill} />
        <rect x="11" y="12" width="3" height="3" rx="0.5" fill={fill} opacity={0.6} />
        <rect x="15" y="12" width="3" height="3" rx="0.5" fill={fill} opacity={0.3} />
      </svg>
    ),
    'Dedicated': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 21C12 21 4 15 4 9a4 4 0 018 0 4 4 0 018 0c0 6-8 12-8 12z" fill={fill} fillOpacity={0.3} stroke={fill} strokeWidth="2" />
        <path d="M12 13l-2-2 2-2 2 2-2 2z" fill={fill} />
      </svg>
    ),
    'Track Addict': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <path d="M12 7v6" stroke={fill} strokeWidth="2.5" strokeLinecap="round" />
        <path d="M12 13l4 3" stroke={fill} strokeWidth="2.5" strokeLinecap="round" />
        <path d="M8 3l1 2M16 3l-1 2M20 8l-2 1M4 8l2 1" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    'Above Average': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M3 17l4-4 4 2 4-6 4 3" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M16 6h5v5" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M21 6l-5 5" stroke={fill} strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),
    'High Performer': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 20V8" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M8 12l4-8 4 8" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M5 20h14" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <circle cx="12" cy="4" r="2" fill={fill} opacity={0.5} />
      </svg>
    ),
    'Elite Driver': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 2l4 8-4 4-4-4 4-8z" fill={fill} fillOpacity={0.3} stroke={fill} strokeWidth="2" />
        <path d="M8 10l-4 8h16l-4-8" stroke={fill} strokeWidth="2" strokeLinejoin="round" />
        <path d="M6 18l6 4 6-4" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    'Consistent Run': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M2 12h4l2-3 2 6 2-6 2 3h8" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="20" cy="12" r="2" fill={fill} opacity={0.5} />
      </svg>
    ),
    'Iron Consistency': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="6" cy="12" r="3" stroke={fill} strokeWidth="2" />
        <circle cx="12" cy="12" r="3" stroke={fill} strokeWidth="2" />
        <circle cx="18" cy="12" r="3" stroke={fill} strokeWidth="2" />
        <path d="M9 12h-0M15 12h-0" stroke={fill} strokeWidth="3" strokeLinecap="round" />
      </svg>
    ),
    'Explorer': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <polygon points="16,6 10,10 8,18 14,14" fill={fill} fillOpacity={0.5} stroke={fill} strokeWidth="1" />
        <circle cx="12" cy="12" r="1.5" fill={fill} />
      </svg>
    ),
    'Globetrotter': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <ellipse cx="12" cy="12" rx="4" ry="9" stroke={fill} strokeWidth="1.5" />
        <path d="M3 12h18M4 7h16M4 17h16" stroke={fill} strokeWidth="1" />
      </svg>
    ),
    'Circuit Collector': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 2l2 3h3l-1 3 2 2-3 1-1 3-2-2-2 2-1-3-3-1 2-2-1-3h3l2-3z" fill={fill} fillOpacity={0.3} stroke={fill} strokeWidth="1.5" />
        <circle cx="12" cy="12" r="3" fill={fill} />
        <text x="12" y="14.5" textAnchor="middle" fill="black" fontSize="5" fontWeight="bold">10</text>
      </svg>
    ),
    'Record Breaker': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M13 2L4 14h6l-1 8 9-12h-6l1-8z" fill={fill} />
        <path d="M16 2l2 2-2 2" stroke={fill} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    'Relentless': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 2v20" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M8 6l4-4 4 4" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M8 11l4-4 4 4" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" opacity={0.6} />
        <path d="M8 16l4-4 4 4" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" opacity={0.3} />
      </svg>
    ),

    /* === BACKEND ACHIEVEMENT LABELS (gamification/achievements.py) === */
    'Regular': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <rect x="3" y="4" width="18" height="16" rx="2" stroke={fill} strokeWidth="2" />
        <path d="M3 9h18" stroke={fill} strokeWidth="2" />
        <path d="M8 4V2M16 4V2" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <circle cx="12" cy="14" r="2" fill={fill} />
      </svg>
    ),
    'Veteran': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 2l2 4h4l-3 3 1 5-4-2-4 2 1-5-3-3h4l2-4z" fill={fill} fillOpacity={0.4} stroke={fill} strokeWidth="1.5" />
        <path d="M7 15l5-2 5 2v6l-5-2-5 2v-6z" fill={fill} fillOpacity={0.3} stroke={fill} strokeWidth="1.5" />
      </svg>
    ),
    'Medal Winner': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="15" r="6" stroke={fill} strokeWidth="2" />
        <path d="M8 3h8l-2 8h-4l-2-8z" fill={fill} fillOpacity={0.3} stroke={fill} strokeWidth="1.5" />
        <path d="M12 13v4M10 15h4" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    'Bronze Collection': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M5 3h14l-2 5H7L5 3z" fill={fill} fillOpacity={0.2} stroke={fill} strokeWidth="1.5" />
        <path d="M7 8v8l5 4 5-4V8" stroke={fill} strokeWidth="2" />
        <text x="12" y="16" textAnchor="middle" fill={fill} fontSize="8" fontWeight="bold">B</text>
      </svg>
    ),
    'Silver Collection': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M5 3h14l-2 5H7L5 3z" fill={fill} fillOpacity={0.3} stroke={fill} strokeWidth="1.5" />
        <path d="M7 8v8l5 4 5-4V8" stroke={fill} strokeWidth="2" />
        <text x="12" y="16" textAnchor="middle" fill={fill} fontSize="8" fontWeight="bold">S</text>
      </svg>
    ),
    'Gold Standard': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M5 16l3-7h8l3 7-3 4H8l-3-4z" fill={fill} fillOpacity={0.4} stroke={fill} strokeWidth="2" strokeLinejoin="round" />
        <path d="M9 14h6" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
        <path d="M8 9l4-7 4 7" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    'Hat Trick': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M7 4l5 3 5-3v5l-5 3-5-3V4z" fill={fill} fillOpacity={0.2} stroke={fill} strokeWidth="1.5" />
        <text x="12" y="9" textAnchor="middle" fill={fill} fontSize="5" fontWeight="bold">3</text>
        <path d="M4 15h16" stroke={fill} strokeWidth="1.5" />
        <path d="M6 15l-1 6h14l-1-6" stroke={fill} strokeWidth="1.5" />
      </svg>
    ),
    'Week Warrior': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <rect x="3" y="4" width="18" height="16" rx="2" stroke={fill} strokeWidth="2" />
        <path d="M3 9h18" stroke={fill} strokeWidth="2" />
        <path d="M8 4V2M16 4V2" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        {/* 7 dots for 7 days */}
        <circle cx="6" cy="13" r="1" fill={fill} />
        <circle cx="9" cy="13" r="1" fill={fill} />
        <circle cx="12" cy="13" r="1" fill={fill} />
        <circle cx="15" cy="13" r="1" fill={fill} />
        <circle cx="18" cy="13" r="1" fill={fill} />
        <circle cx="6" cy="17" r="1" fill={fill} />
        <circle cx="9" cy="17" r="1" fill={fill} />
      </svg>
    ),
    'Iron Will': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 2C8 7 5 10 5 14a7 7 0 0014 0c0-4-3-7-7-12z" stroke={fill} strokeWidth="2" />
        <path d="M12 8c-2 3-3 4-3 6a3 3 0 006 0c0-2-1-3-3-6z" fill={fill} />
        <path d="M10 20h4" stroke={fill} strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),
    'Plan Complete': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <path d="M8 12l3 3 5-6" stroke={fill} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    'Perfect Week': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <rect x="3" y="4" width="18" height="16" rx="2" stroke={fill} strokeWidth="2" />
        <path d="M3 9h18" stroke={fill} strokeWidth="2" />
        <path d="M8 4V2M16 4V2" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M9 14l2 2 4-4" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    'New PB': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M13 2L4 14h6l-1 8 9-12h-6l1-8z" fill={fill} />
      </svg>
    ),
    'Level Up': (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 19V5" stroke={fill} strokeWidth="2.5" strokeLinecap="round" />
        <path d="M5 12l7-7 7 7" stroke={fill} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M5 20h14" stroke={fill} strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),
  };

  return icons[title] || (
    // Fallback star
    <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} opacity={opacity}>
      <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
    </svg>
  );
}

/* ── Component ────────────────────────────────────────────── */

export function RacingBadge({ title, description, unlocked, category = 'progress' }: RacingBadgeProps) {
  const color = categoryColors[category];
  const safeId = title.replace(/[^a-zA-Z0-9]/g, '-');

  return (
    <div
      className="relative group"
      style={{ transition: 'transform 0.2s ease' }}
      onMouseEnter={(e) => {
        if (unlocked) e.currentTarget.style.transform = 'scale(1.05) translateY(-3px)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = '';
      }}
    >
      {/* Hexagon container */}
      <div className="relative w-32 h-36 flex flex-col items-center justify-center">
        {/* Hexagon SVG */}
        <svg
          viewBox="0 0 100 115"
          className={`absolute inset-0 w-full h-full ${unlocked ? '' : 'opacity-30'}`}
          style={{ filter: unlocked ? `drop-shadow(0 0 12px ${color}40)` : 'none' }}
        >
          <defs>
            <linearGradient id={`gradient-${safeId}`} x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" style={{ stopColor: unlocked ? color : '#949494', stopOpacity: 0.2 }} />
              <stop offset="100%" style={{ stopColor: unlocked ? color : '#949494', stopOpacity: 0.05 }} />
            </linearGradient>
          </defs>
          <path
            d="M50 0 L93.3 28.75 L93.3 86.25 L50 115 L6.7 86.25 L6.7 28.75 Z"
            fill={`url(#gradient-${safeId})`}
            stroke={unlocked ? color : '#949494'}
            strokeWidth="2"
            opacity={unlocked ? 1 : 0.3}
          />
        </svg>

        {/* Unique icon per badge */}
        <div className="relative z-10 flex flex-col items-center justify-center">
          <div className="mb-1">
            <BadgeIcon title={title} color={color} unlocked={unlocked} />
          </div>

          {/* Title */}
          <div
            className={`font-telemetry text-[9px] font-bold text-center leading-tight mt-1 px-2 ${
              unlocked ? 'text-chalk' : 'text-steel'
            }`}
            style={{ maxWidth: '90px' }}
          >
            {title}
          </div>
        </div>

        {/* Locked overlay */}
        {!unlocked && (
          <div className="absolute inset-0 flex items-center justify-center z-20">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="#949494" opacity="0.5">
              <path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zM9 6c0-1.66 1.34-3 3-3s3 1.34 3 3v2H9V6zm9 14H6V10h12v10zm-6-3c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2z" />
            </svg>
          </div>
        )}
      </div>

      {/* Hover tooltip */}
      <div
        className="absolute left-1/2 -translate-x-1/2 top-full mt-2 bg-concrete border border-chalk/10 rounded px-3 py-2 font-body text-xs text-chalk whitespace-nowrap z-30 pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-200"
        style={{ boxShadow: `0 0 20px ${color}20` }}
      >
        {description}
        <div className="absolute left-1/2 -translate-x-1/2 -top-1 w-2 h-2 bg-concrete border-l border-t border-chalk/10 rotate-45" />
      </div>
    </div>
  );
}
