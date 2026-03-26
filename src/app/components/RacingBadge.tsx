import { motion } from "motion/react";

interface RacingBadgeProps {
  title: string;
  description: string;
  unlocked: boolean;
  category?: "progress" | "technique" | "consistency" | "learning" | "endurance";
}

const categoryColors = {
  progress: "#C9A84C",
  technique: "#22C55E",
  consistency: "#FACC15",
  learning: "#8B5CF6",
  endurance: "#FF2A2A",
};

// Each badge gets a unique SVG icon reflecting its meaning
function BadgeIcon({ title, color, unlocked }: { title: string; color: string; unlocked: boolean }) {
  const fill = unlocked ? color : "#949494";
  const opacity = unlocked ? 1 : 0.3;
  const size = 28;

  const icons: Record<string, JSX.Element> = {
    // === PROGRESS & MILESTONES ===
    "First Lap": (
      // Single lap/circle with "1"
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <text x="12" y="16" textAnchor="middle" fill={fill} fontSize="10" fontWeight="bold">1</text>
      </svg>
    ),
    "Session Starter": (
      // Play button
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <polygon points="10,8 17,12 10,16" fill={fill} />
      </svg>
    ),
    "Data Rookie": (
      // Upload arrow with data bars
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 3L8 7h3v6h2V7h3L12 3z" fill={fill} />
        <rect x="5" y="16" width="3" height="5" rx="0.5" fill={fill} opacity={0.6} />
        <rect x="10.5" y="14" width="3" height="7" rx="0.5" fill={fill} opacity={0.8} />
        <rect x="16" y="17" width="3" height="4" rx="0.5" fill={fill} opacity={0.5} />
      </svg>
    ),
    "Clean Driver": (
      // Checkmark with sparkle
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M9 12l2 2 4-4" stroke={fill} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <circle cx="19" cy="5" r="1.5" fill={fill} />
      </svg>
    ),
    "Hotlap Hunter": (
      // Flame / fire
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 2C8 7 5 10 5 14a7 7 0 0014 0c0-4-3-7-7-12z" fill={fill} opacity={0.3} />
        <path d="M12 8c-2 3-4 5-4 7a4 4 0 008 0c0-2-2-4-4-7z" fill={fill} />
      </svg>
    ),
    "Delta Chaser": (
      // Delta triangle with arrow
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 4L4 20h16L12 4z" stroke={fill} strokeWidth="2" fill="none" />
        <path d="M12 10v5m0 0l-2-2m2 2l2-2" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    "Tenths Collector": (
      // Stopwatch with .1
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="13" r="8" stroke={fill} strokeWidth="2" />
        <path d="M12 5V3M10 3h4" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <text x="12" y="16" textAnchor="middle" fill={fill} fontSize="7" fontWeight="bold">.1</text>
      </svg>
    ),
    "Half-Second Hero": (
      // Stopwatch with .5
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="13" r="8" stroke={fill} strokeWidth="2" />
        <path d="M12 5V3M10 3h4" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <text x="12" y="16" textAnchor="middle" fill={fill} fontSize="7" fontWeight="bold">.5</text>
      </svg>
    ),
    "Second Slayer": (
      // Stopwatch with -1s and sword-like slash
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="13" r="8" stroke={fill} strokeWidth="2" />
        <path d="M12 5V3M10 3h4" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <text x="12" y="16" textAnchor="middle" fill={fill} fontSize="7" fontWeight="bold">1s</text>
        <path d="M17 5l3-3" stroke={fill} strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),

    // === TECHNIQUE & DRIVING QUALITY ===
    "Brake Marker": (
      // Brake disc with dot marker
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <circle cx="12" cy="12" r="4" stroke={fill} strokeWidth="2" />
        <circle cx="12" cy="3" r="1.5" fill={fill} />
        <line x1="12" y1="3" x2="12" y2="8" stroke={fill} strokeWidth="1.5" />
      </svg>
    ),
    "Late Braker": (
      // Brake pad pressed deep
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <rect x="4" y="4" width="6" height="16" rx="1" stroke={fill} strokeWidth="2" />
        <rect x="14" y="4" width="6" height="16" rx="1" stroke={fill} strokeWidth="2" />
        <path d="M10 9h4M10 12h4M10 15h4" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
        <path d="M12 19l-2 2m2-2l2 2" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    "Trail Braker": (
      // Curved trail with brake fade
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M4 18C4 18 8 6 12 6s8 12 8 12" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <circle cx="6" cy="15" r="1.5" fill={fill} opacity={1} />
        <circle cx="9" cy="10" r="1.2" fill={fill} opacity={0.7} />
        <circle cx="12" cy="7" r="1" fill={fill} opacity={0.4} />
      </svg>
    ),
    "Smooth Hands": (
      // Smooth sine wave / steering input
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M2 12C4 8 6 8 8 12s4 4 4 0 2-4 4 0 2 4 4 0" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <circle cx="4" cy="4" r="2" stroke={fill} strokeWidth="1.5" />
        <circle cx="4" cy="4" r="0.5" fill={fill} />
      </svg>
    ),
    "Throttle Artist": (
      // Progressive throttle curve going up
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M3 20C3 20 6 18 9 14s4-6 6-8c2-2 3-3 6-4" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M18 4l2-1m-2 1l1 2" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    "Early On Power": (
      // Lightning bolt with throttle
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M13 2L4 14h6l-1 8 9-12h-6l1-8z" fill={fill} />
      </svg>
    ),
    "Apex Hunter": (
      // Corner apex with crosshair
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M20 4L12 12 4 20" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <circle cx="12" cy="12" r="4" stroke={fill} strokeWidth="1.5" />
        <circle cx="12" cy="12" r="1" fill={fill} />
        <path d="M12 6V8M12 16v2M6 12H8M16 12h2" stroke={fill} strokeWidth="1" strokeLinecap="round" />
      </svg>
    ),
    "Exit Maximizer": (
      // Arrow exiting corner accelerating
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M4 20Q4 12 12 12h6" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M16 8l4 4-4 4" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    "Minimum Speed Master": (
      // Speedometer at minimum
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M4 18a9 9 0 0118 0" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M12 18l-4-6" stroke={fill} strokeWidth="2.5" strokeLinecap="round" />
        <circle cx="12" cy="18" r="2" fill={fill} />
      </svg>
    ),
    "Weight Transfer Wizard": (
      // Balance / scales
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 3v16" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M5 7l7-2 7 2" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M3 13l2-6 2 6a2 2 0 01-4 0zM17 13l2-6 2 6a2 2 0 01-4 0z" fill={fill} opacity={0.4} stroke={fill} strokeWidth="1.5" />
        <path d="M8 21h8" stroke={fill} strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),

    // === CONSISTENCY & DISCIPLINE ===
    "Metronome": (
      // Metronome pendulum
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M8 22l4-18 4 18" stroke={fill} strokeWidth="2" strokeLinejoin="round" />
        <path d="M12 8l5-4" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <circle cx="17" cy="4" r="1.5" fill={fill} />
        <path d="M6 22h12" stroke={fill} strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),
    "Consistent One": (
      // Flat line / heartbeat-like consistent
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M2 12h4l2-3 2 6 2-6 2 3h8" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    "No Excuses": (
      // Eye examining
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" stroke={fill} strokeWidth="2" />
        <circle cx="12" cy="12" r="3" fill={fill} />
      </svg>
    ),
    "Repeatable Pace": (
      // Equals sign / repeat arrows
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M17 2l3 3-3 3" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M4 5h16" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M7 22l-3-3 3-3" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M20 19H4" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M7 12h10" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeDasharray="2 2" />
      </svg>
    ),
    "Zero Drama": (
      // Zen circle / calm water
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <path d="M8 12h8" stroke={fill} strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),
    "Precision Driver": (
      // Target / bullseye
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="1.5" />
        <circle cx="12" cy="12" r="6" stroke={fill} strokeWidth="1.5" />
        <circle cx="12" cy="12" r="3" stroke={fill} strokeWidth="1.5" />
        <circle cx="12" cy="12" r="1" fill={fill} />
      </svg>
    ),
    "Discipline Over Heroics": (
      // Steady upward trend line
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M3 20L9 14l4 2 8-10" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="3" y="18" width="2" height="4" fill={fill} opacity={0.3} />
        <rect x="8" y="14" width="2" height="8" fill={fill} opacity={0.5} />
        <rect x="13" y="11" width="2" height="11" fill={fill} opacity={0.7} />
        <rect x="18" y="7" width="2" height="15" fill={fill} opacity={0.9} />
      </svg>
    ),
    "Pressure Proof": (
      // Diamond / pressure resistant
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 2l8 8-8 12-8-12 8-8z" stroke={fill} strokeWidth="2" fill={fill} fillOpacity={0.15} />
        <path d="M4 10h16" stroke={fill} strokeWidth="1.5" />
        <path d="M8 10l4 12 4-12" stroke={fill} strokeWidth="1.5" />
      </svg>
    ),
    "One More Lap": (
      // Finish flag + plus
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
    "Recovery Specialist": (
      // Bounce-back arrow
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M4 18l4-8 4 6 4-10 4 6" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M18 8l2 4 2-2" stroke={fill} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    "Stable Platform": (
      // Flat horizontal bars / stability
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <rect x="3" y="6" width="18" height="3" rx="1" fill={fill} opacity={0.4} />
        <rect x="3" y="11" width="18" height="3" rx="1" fill={fill} opacity={0.7} />
        <rect x="3" y="16" width="18" height="3" rx="1" fill={fill} />
      </svg>
    ),

    // === TRACK LEARNING & ANALYSIS ===
    "Track Scout": (
      // Compass / explore
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <polygon points="16,6 10,10 8,18 14,14" fill={fill} fillOpacity={0.5} stroke={fill} strokeWidth="1" />
        <circle cx="12" cy="12" r="1.5" fill={fill} />
      </svg>
    ),
    "Corner Student": (
      // Book open with corner line
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M2 4l10 2 10-2v15l-10 2-10-2V4z" stroke={fill} strokeWidth="1.5" />
        <path d="M12 6v15" stroke={fill} strokeWidth="1.5" />
        <path d="M6 10q2 0 2 2t2 2" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    "Track Mapper": (
      // Map with track outline
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <rect x="3" y="3" width="18" height="18" rx="2" stroke={fill} strokeWidth="2" />
        <path d="M7 7C7 7 10 7 12 10s5 7 5 7" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <circle cx="7" cy="7" r="1.5" fill={fill} />
        <circle cx="17" cy="17" r="1.5" fill={fill} />
      </svg>
    ),
    "Reference Builder": (
      // Waypoint markers
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M3 20L21 4" stroke={fill} strokeWidth="1.5" strokeDasharray="3 2" />
        <circle cx="5" cy="18" r="2.5" fill={fill} />
        <circle cx="10" cy="13" r="2" fill={fill} opacity={0.8} />
        <circle cx="15" cy="8" r="2" fill={fill} opacity={0.6} />
        <circle cx="20" cy="4" r="1.5" fill={fill} opacity={0.4} />
      </svg>
    ),
    "Sector Surgeon": (
      // Pie chart with one sector highlighted
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <path d="M12 3v9l7 5" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M12 12l-6 7" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
        <path d="M12 3a9 9 0 015.5 2.5L12 12V3z" fill={fill} opacity={0.4} />
      </svg>
    ),
    "Line Detective": (
      // Magnifying glass over racing line
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="10" cy="10" r="7" stroke={fill} strokeWidth="2" />
        <path d="M15 15l6 6" stroke={fill} strokeWidth="2.5" strokeLinecap="round" />
        <path d="M7 10q3-4 6 0" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    "Telemetry Explorer": (
      // Graph with multiple data lines
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M3 3v18h18" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M6 15l4-4 3 2 5-7" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M6 18l4-2 3-1 5-3" stroke={fill} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity={0.5} />
      </svg>
    ),
    "Compare Mode": (
      // Two overlapping traces
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M3 16l4-4 4 2 4-6 4 2" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M3 18l4-2 4 1 4-4 4 1" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" opacity={0.4} strokeDasharray="3 2" />
      </svg>
    ),
    "Theory to Track": (
      // Lightbulb to checkmark
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M9 21h6M10 18h4" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
        <path d="M12 2a7 7 0 00-3 13.3V17h6v-1.7A7 7 0 0012 2z" fill={fill} fillOpacity={0.2} stroke={fill} strokeWidth="1.5" />
        <path d="M10 11l2 2 3-3" stroke={fill} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    "Lesson Locked In": (
      // Lock with star/badge inside
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <rect x="5" y="11" width="14" height="10" rx="2" stroke={fill} strokeWidth="2" />
        <path d="M8 11V7a4 4 0 018 0v4" stroke={fill} strokeWidth="2" />
        <path d="M12 14l1.5 1-0.5 1.5L12 18l-1-1.5-0.5-1.5z" fill={fill} />
      </svg>
    ),

    // === ENDURANCE & RACECRAFT ===
    "Stint Manager": (
      // Clock with segments
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <path d="M12 6v6l4 3" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M12 3v1M21 12h-1M12 21v-1M3 12h1" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    "Endurance Mindset": (
      // Infinity symbol
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M8 12c-2-2-4-2-4 0s2 4 4 2l4-4c2-2 4-2 4 0s-2 4-4 2l-4-4z" stroke={fill} strokeWidth="2.5" strokeLinecap="round" />
      </svg>
    ),
    "Tire Whisperer": (
      // Tire / wheel
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="12" cy="12" r="9" stroke={fill} strokeWidth="2" />
        <circle cx="12" cy="12" r="4" stroke={fill} strokeWidth="2" />
        <path d="M12 3v5M12 16v5M3 12h5M16 12h5M5.6 5.6l3.6 3.6M14.8 14.8l3.6 3.6M5.6 18.4l3.6-3.6M14.8 9.2l3.6-3.6" stroke={fill} strokeWidth="1" />
      </svg>
    ),
    "Fuel Saver": (
      // Gas drop / fuel icon
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M12 2C8 8 5 12 5 16a7 7 0 0014 0c0-4-3-8-7-14z" fill={fill} fillOpacity={0.3} stroke={fill} strokeWidth="2" />
        <path d="M10 16a2 2 0 004 0c0-1-1-3-2-5-1 2-2 4-2 5z" fill={fill} />
      </svg>
    ),
    "Traffic Navigator": (
      // Multiple cars / weaving
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <rect x="3" y="6" width="5" height="3" rx="1" fill={fill} opacity={0.4} />
        <rect x="16" y="10" width="5" height="3" rx="1" fill={fill} opacity={0.4} />
        <rect x="5" y="15" width="5" height="3" rx="1" fill={fill} opacity={0.4} />
        <path d="M10 12C12 8 14 8 16 12s4 6 6 4" stroke={fill} strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),
    "Racecraft Ready": (
      // Checkered flag
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
    "Closer": (
      // Finish line with lightning
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M20 3v18" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M20 5h-4v4h4v4h-4v4h4" stroke={fill} strokeWidth="1" />
        <path d="M5 8l4-2-1 5 4-2-5 8" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    "Iron Focus": (
      // Eye with iron/strength lines
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" stroke={fill} strokeWidth="2" />
        <circle cx="12" cy="12" r="3" fill={fill} />
        <path d="M12 2v3M12 19v3M2 12h2M20 12h2" stroke={fill} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    "Team Player": (
      // Two people / handshake
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" opacity={opacity}>
        <circle cx="8" cy="7" r="3" fill={fill} opacity={0.7} />
        <circle cx="16" cy="7" r="3" fill={fill} opacity={0.7} />
        <path d="M2 20c0-3 3-6 6-6 1.5 0 2.5.5 3 1" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M22 20c0-3-3-6-6-6-1.5 0-2.5.5-3 1" stroke={fill} strokeWidth="2" strokeLinecap="round" />
        <path d="M10 16l2 2 2-2" stroke={fill} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    "Lap Coach Certified": (
      // Trophy / crown with LAP
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
  };

  return icons[title] || (
    // Fallback star
    <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} opacity={opacity}>
      <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
    </svg>
  );
}

export function RacingBadge({ title, description, unlocked, category = "progress" }: RacingBadgeProps) {
  const color = categoryColors[category];
  const safeId = title.replace(/[^a-zA-Z0-9]/g, "-");

  return (
    <motion.div
      whileHover={unlocked ? { scale: 1.05, y: -3 } : {}}
      transition={{ type: "spring", stiffness: 400, damping: 20 }}
      className="relative group"
    >
      {/* Hexagon container */}
      <div className="relative w-32 h-36 flex flex-col items-center justify-center">
        {/* Hexagon SVG */}
        <svg
          viewBox="0 0 100 115"
          className={`absolute inset-0 w-full h-full ${unlocked ? "" : "opacity-30"}`}
          style={{ filter: unlocked ? `drop-shadow(0 0 12px ${color}40)` : "none" }}
        >
          <defs>
            <linearGradient id={`gradient-${safeId}`} x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" style={{ stopColor: unlocked ? color : "#949494", stopOpacity: 0.2 }} />
              <stop offset="100%" style={{ stopColor: unlocked ? color : "#949494", stopOpacity: 0.05 }} />
            </linearGradient>
          </defs>
          <path
            d="M50 0 L93.3 28.75 L93.3 86.25 L50 115 L6.7 86.25 L6.7 28.75 Z"
            fill={`url(#gradient-${safeId})`}
            stroke={unlocked ? color : "#949494"}
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
            className={`text-[9px] font-bold text-center leading-tight mt-1 px-2 ${
              unlocked ? "text-[#F0EDE5]" : "text-[#949494]"
            }`}
            style={{ maxWidth: "90px" }}
          >
            {title}
          </div>
        </div>

        {/* Locked overlay */}
        {!unlocked && (
          <div className="absolute inset-0 flex items-center justify-center z-20">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="#949494" opacity="0.5">
              <path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zM9 6c0-1.66 1.34-3 3-3s3 1.34 3 3v2H9V6zm9 14H6V10h12v10zm-6-3c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2z"/>
            </svg>
          </div>
        )}
      </div>

      {/* Hover tooltip */}
      <div
        className="absolute left-1/2 -translate-x-1/2 top-full mt-2 bg-[#141414] border border-[rgba(240,237,229,0.1)] rounded px-3 py-2 text-xs text-[#F0EDE5] whitespace-nowrap z-30 pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-200"
        style={{ boxShadow: `0 0 20px ${color}20` }}
      >
        {description}
        <div className="absolute left-1/2 -translate-x-1/2 -top-1 w-2 h-2 bg-[#141414] border-l border-t border-[rgba(240,237,229,0.1)] rotate-45" />
      </div>
    </motion.div>
  );
}
