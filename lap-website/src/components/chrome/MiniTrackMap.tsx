'use client';

import { useMemo } from 'react';
import { useKernelStore } from '@/experience/state/store';
import { colors } from '@/lib/tokens';

// Simplified track outline as an SVG path
// Oval with rounded corners that resembles a circuit layout
const TRACK_PATH = 'M 20,10 L 60,10 Q 75,10 75,25 L 75,55 Q 75,70 60,70 L 20,70 Q 5,70 5,55 L 5,25 Q 5,10 20,10 Z';

// Corner zones (approximate positions along the path)
const CORNERS = [
  { cx: 70, cy: 17, label: 'T1' },
  { cx: 70, cy: 63, label: 'T2' },
  { cx: 10, cy: 63, label: 'T3' },
  { cx: 10, cy: 17, label: 'T4' },
];

// Map 0-1 progress to a position on the simplified track path
function getTrackPosition(progress: number): { x: number; y: number } {
  const p = ((progress % 1) + 1) % 1; // Normalize to 0-1

  // Approximate positions along the oval:
  // 0.00-0.25: top straight (left to right)
  // 0.25-0.50: right curve + right straight (top to bottom)
  // 0.50-0.75: bottom straight (right to left)
  // 0.75-1.00: left curve + left straight (bottom to top)
  if (p < 0.25) {
    const t = p / 0.25;
    return { x: 20 + t * 40, y: 10 };
  } else if (p < 0.5) {
    const t = (p - 0.25) / 0.25;
    return { x: 75, y: 10 + t * 60 };
  } else if (p < 0.75) {
    const t = (p - 0.5) / 0.25;
    return { x: 60 - t * 40, y: 70 };
  } else {
    const t = (p - 0.75) / 0.25;
    return { x: 5, y: 70 - t * 60 };
  }
}

export function MiniTrackMap() {
  const globalProgress = useKernelStore((s) => s.globalProgress);
  const isCorner = useKernelStore((s) => s.trackPath.isCorner);

  const dotPos = useMemo(() => getTrackPosition(globalProgress), [globalProgress]);

  // Determine which corner zone to highlight based on progress
  const activeCornerIndex = useMemo(() => {
    if (!isCorner) return -1;
    const p = globalProgress % 1;
    if (p >= 0.2 && p < 0.3) return 0;
    if (p >= 0.45 && p < 0.55) return 1;
    if (p >= 0.7 && p < 0.8) return 2;
    if (p >= 0.95 || p < 0.05) return 3;
    return -1;
  }, [globalProgress, isCorner]);

  return (
    <div
      className="fixed bottom-6 left-6 hidden md:block pointer-events-none"
      style={{ zIndex: 'var(--z-hud)' as unknown as number }}
      aria-hidden="true"
    >
      <svg width="80" height="80" viewBox="0 0 80 80" fill="none">
        {/* Track outline */}
        <path
          d={TRACK_PATH}
          stroke="var(--steel)"
          strokeWidth="1.5"
          fill="none"
          opacity="0.4"
        />

        {/* Corner zones */}
        {CORNERS.map((corner, i) => (
          <circle
            key={corner.label}
            cx={corner.cx}
            cy={corner.cy}
            r="6"
            fill={i === activeCornerIndex ? colors.racingPurple : 'transparent'}
            opacity={i === activeCornerIndex ? 0.3 : 0}
            className="transition-all duration-[420ms]"
          />
        ))}

        {/* Moving dot */}
        <circle
          cx={dotPos.x}
          cy={dotPos.y}
          r="3"
          fill={colors.racingPurple}
          className="transition-all duration-200"
        >
          {/* Pulse animation */}
          <animate
            attributeName="r"
            values="3;4;3"
            dur="2s"
            repeatCount="indefinite"
          />
        </circle>

        {/* Dot glow */}
        <circle
          cx={dotPos.x}
          cy={dotPos.y}
          r="6"
          fill={colors.racingPurple}
          opacity="0.2"
          className="transition-all duration-200"
        />
      </svg>
    </div>
  );
}
