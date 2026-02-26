// Simplified corner physics for the S1 interactive mechanism.
// Maps 3 control points (entry, apex, exit) to a time delta vs optimal.

export interface ControlPoint {
  x: number; // 0-1 normalized
  y: number; // 0-1 normalized
}

export interface CornerResult {
  delta: number;      // seconds: negative = faster, positive = slower
  lineLength: number; // relative path length (1.0 = optimal)
}

// Optimal positions for a 90° right-hander
const OPTIMAL = {
  entry: { x: 0.15, y: 0.9 },
  apex: { x: 0.55, y: 0.45 },
  exit: { x: 0.95, y: 0.15 },
};

function dist(a: ControlPoint, b: ControlPoint): number {
  return Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);
}

// Approximate racing line length through 3 points using quadratic Bezier
function bezierLength(p0: ControlPoint, p1: ControlPoint, p2: ControlPoint, steps = 20): number {
  let length = 0;
  let prev = p0;
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    const x = (1 - t) ** 2 * p0.x + 2 * (1 - t) * t * p1.x + t ** 2 * p2.x;
    const y = (1 - t) ** 2 * p0.y + 2 * (1 - t) * t * p1.y + t ** 2 * p2.y;
    const curr = { x, y };
    length += dist(prev, curr);
    prev = curr;
  }
  return length;
}

export function computeCornerDelta(
  entry: ControlPoint,
  apex: ControlPoint,
  exit: ControlPoint,
): CornerResult {
  const optimalLength = bezierLength(OPTIMAL.entry, OPTIMAL.apex, OPTIMAL.exit);
  const userLength = bezierLength(entry, apex, exit);

  // Deviation from optimal apex position affects cornering speed
  const apexError = dist(apex, OPTIMAL.apex);

  // Longer line + apex error = time lost
  const lengthPenalty = (userLength / optimalLength - 1) * 0.8; // ~0.8s per 100% extra length
  const apexPenalty = apexError * 0.6; // ~0.6s per unit apex error

  const delta = -(lengthPenalty + apexPenalty); // negative = time gained (closer to optimal)
  const clampedDelta = Math.max(-0.5, Math.min(0.8, delta));

  return {
    delta: Math.round(clampedDelta * 100) / 100,
    lineLength: userLength / optimalLength,
  };
}
