/**
 * LAP monogram — abstract racing corner with apex dot.
 * Derived from the Figma brand guide ("The Precision Monogram").
 *
 * Two SVG paths in a 200×200 viewBox:
 *   1. L-shaped racing corner curve (entry → apex arc → exit)
 *   2. Circular dot at the mathematical apex
 */

interface LapMonogramProps {
  /** Rendered pixel size (width & height) */
  size?: number;
  /** Fill color — defaults to chalk (#F0EDE5) */
  color?: string;
  className?: string;
}

const CORNER_PATH =
  'M36 16V100C36 123.339 45.2714 145.722 61.7746 162.225C78.2778 178.729 100.661 188 124 188H180V140H124C115.513 140 107.374 136.629 101.373 130.627C95.3714 124.626 92 116.487 92 108V16H36Z';

const APEX_DOT_PATH =
  'M154 62C166.15 62 176 52.1503 176 40C176 27.8497 166.15 18 154 18C141.85 18 132 27.8497 132 40C132 52.1503 141.85 62 154 62Z';

export function LapMonogram({ size = 32, color = '#F0EDE5', className }: LapMonogramProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 200 200"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <path d={CORNER_PATH} fill={color} />
      <path d={APEX_DOT_PATH} fill={color} />
    </svg>
  );
}
