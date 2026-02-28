/**
 * Tests for defensive guards in chart components.
 *
 * These tests verify that the guard patterns used across all 10 medium-risk
 * chart components correctly handle NaN, Infinity, empty arrays, division by
 * zero, and negative canvas values without crashing.
 */
import { describe, it, expect } from 'vitest';

// ─── Guard pattern helpers (extracted from chart components) ───────────────

/** Safe Math.max on filtered arrays — used in FatigueChart, WorkloadChart, etc. */
function safeMax(arr: number[], floor: number): number {
  const clean = arr.filter(Number.isFinite);
  return clean.length > 0 ? Math.max(...clean, floor) : floor;
}

/** Safe Math.min on filtered arrays — used in EnergyBalance, ComparisonMatrix */
function safeMin(arr: number[], ceiling: number): number {
  const clean = arr.filter(Number.isFinite);
  return clean.length > 0 ? Math.min(...clean, ceiling) : ceiling;
}

/** Safe radius — prevents negative canvas arc radius (DrivingStyle) */
function safeRadius(cx: number, cy: number, margin: number): number {
  return Math.max(1, Math.min(cx, cy) - margin);
}

/** Safe toY — returns finite fallback if computation produces NaN/Infinity */
function safeToY(val: number, max: number, plotH: number, padTop: number): number {
  const safe = Number.isFinite(val) ? val : 0;
  const y = padTop + plotH - (safe / Math.max(max, 0.001)) * plotH;
  return Number.isFinite(y) ? y : padTop;
}

/** Safe division range — used for dR, eR, tempR, lapR etc. */
function safeRange(a: number, b: number): number {
  return a - b || 1;
}

/** Cell color NaN guard — used in ComparisonMatrix */
function safeCellT(val: number, min: number, max: number): number {
  const safeVal = Number.isFinite(val) ? val : min;
  return (safeVal - min) / (max - min || 1);
}

// ─── Tests ────────────────────────────────────────────────────────────────

describe('Chart guard: safeMax', () => {
  it('returns floor for empty array', () => {
    expect(safeMax([], 0.1)).toBe(0.1);
  });

  it('returns floor for all-NaN array', () => {
    expect(safeMax([NaN, NaN, NaN], 0.1)).toBe(0.1);
  });

  it('returns floor for all-Infinity array', () => {
    expect(safeMax([Infinity, -Infinity], 0.1)).toBe(0.1);
  });

  it('returns max of valid values', () => {
    expect(safeMax([1, 5, 3], 0.1)).toBe(5);
  });

  it('filters NaN but keeps valid values', () => {
    expect(safeMax([NaN, 2, NaN, 8, Infinity], 0.1)).toBe(8);
  });

  it('uses floor when all valid values are below floor', () => {
    expect(safeMax([0.01, 0.02], 0.1)).toBe(0.1);
  });
});

describe('Chart guard: safeMin', () => {
  it('returns ceiling for empty array', () => {
    expect(safeMin([], 0)).toBe(0);
  });

  it('returns ceiling for all-NaN array', () => {
    expect(safeMin([NaN, NaN], 0)).toBe(0);
  });

  it('returns min of valid values', () => {
    expect(safeMin([5, 1, 3], 10)).toBe(1);
  });

  it('filters NaN from mixed array', () => {
    expect(safeMin([NaN, 100, NaN, 50], 0)).toBe(0);
  });
});

describe('Chart guard: safeRadius (DrivingStyle)', () => {
  it('returns 1 when canvas is too small for margin', () => {
    // Canvas 20x20 → cx=10, cy=10, margin=30 → min(10,10)-30 = -20 → clamped to 1
    expect(safeRadius(10, 10, 30)).toBe(1);
  });

  it('returns positive value for normal canvas', () => {
    expect(safeRadius(200, 150, 30)).toBe(120);
  });

  it('returns 1 for zero-size canvas', () => {
    expect(safeRadius(0, 0, 30)).toBe(1);
  });
});

describe('Chart guard: safeToY', () => {
  it('handles NaN value', () => {
    const y = safeToY(NaN, 100, 200, 10);
    expect(Number.isFinite(y)).toBe(true);
  });

  it('handles Infinity value', () => {
    const y = safeToY(Infinity, 100, 200, 10);
    expect(Number.isFinite(y)).toBe(true);
  });

  it('handles zero max (division by zero)', () => {
    const y = safeToY(50, 0, 200, 10);
    expect(Number.isFinite(y)).toBe(true);
  });

  it('handles NaN max', () => {
    const y = safeToY(50, NaN, 200, 10);
    expect(Number.isFinite(y)).toBe(true);
  });

  it('returns correct value for normal inputs', () => {
    // val=50, max=100, plotH=200, padTop=10 → 10 + 200 - (50/100)*200 = 110
    expect(safeToY(50, 100, 200, 10)).toBe(110);
  });
});

describe('Chart guard: safeRange', () => {
  it('returns 1 for identical values (prevents divide-by-zero)', () => {
    expect(safeRange(5, 5)).toBe(1);
  });

  it('returns difference for distinct values', () => {
    expect(safeRange(10, 3)).toBe(7);
  });

  it('returns 1 for NaN difference', () => {
    // NaN - 5 = NaN, NaN || 1 = 1
    expect(safeRange(NaN, 5)).toBe(1);
  });
});

describe('Chart guard: safeCellT (ComparisonMatrix)', () => {
  it('handles NaN value — uses min as fallback', () => {
    const t = safeCellT(NaN, 0, 100);
    expect(t).toBe(0); // (0 - 0) / 100 = 0
  });

  it('handles equal min and max (prevents divide-by-zero)', () => {
    const t = safeCellT(5, 5, 5);
    expect(Number.isFinite(t)).toBe(true);
    expect(t).toBe(0); // (5-5) / (5-5 || 1) = 0/1 = 0
  });

  it('returns correct value for normal inputs', () => {
    const t = safeCellT(75, 0, 100);
    expect(t).toBe(0.75);
  });
});

describe('Chart guard: useInteractiveCanvas plotW/plotH floor', () => {
  it('prevents division by zero when plot area is zero', () => {
    // Simulates the guard: Math.max(rect.width - pad.left - pad.right, 1)
    const rectWidth = 50; // Less than pad.left + pad.right
    const padLeft = 30;
    const padRight = 30;
    const plotW = Math.max(rectWidth - padLeft - padRight, 1);
    expect(plotW).toBe(1); // -10 clamped to 1
    const nx = Math.max(0, Math.min(1, (25 - padLeft) / plotW));
    expect(Number.isFinite(nx)).toBe(true);
  });
});

describe('Chart guard: large array spread protection (TyreChart)', () => {
  it('uses loop-based max instead of Math.max spread for large arrays', () => {
    // Simulate the TyreChart pattern: loop-based max finder
    const arr = Array.from({ length: 100000 }, (_, i) => i * 0.01);
    arr.push(NaN);
    arr.push(Infinity);
    const clean = arr.filter(Number.isFinite);
    let maxVal = 1;
    for (let i = 0; i < clean.length; i++) {
      if (clean[i] > maxVal) maxVal = clean[i];
    }
    expect(maxVal).toBe(999.99);
    expect(Number.isFinite(maxVal)).toBe(true);
  });
});

describe('Chart guard: CornerReplayCockpit radius guards', () => {
  /** Mirrors the speedR calculation with min 20px floor */
  function cockpitSpeedR(w: number, h: number): number {
    return Math.max(20, Math.min(w * 0.22, h * 0.32));
  }

  /** Mirrors tickR, innerR, labelR, arc-radius, needle-length derivations */
  function cockpitDerivedRadii(speedR: number) {
    const tickR = Math.max(0, speedR - 4);
    const innerRMajor = Math.max(0, tickR - 8);
    const innerRMinor = Math.max(0, tickR - 4);
    const labelR = Math.max(0, innerRMajor - 10);
    const arcR = Math.max(0, speedR - 10);
    const needleLen = Math.max(0, speedR - 16);
    return { tickR, innerRMajor, innerRMinor, labelR, arcR, needleLen };
  }

  /** Mirrors gR and steerR with min 1px floor */
  function cockpitGR(w: number, h: number): number {
    return Math.max(1, Math.min(w * 0.18, h * 0.28));
  }
  function cockpitSteerR(w: number, h: number): number {
    return Math.max(1, Math.min(w * 0.14, h * 0.12));
  }

  it('speedR is at least 20 even for zero-size canvas', () => {
    expect(cockpitSpeedR(0, 0)).toBe(20);
  });

  it('speedR is at least 20 for tiny canvas', () => {
    expect(cockpitSpeedR(10, 10)).toBe(20);
  });

  it('speedR uses computed value for normal canvas', () => {
    // w=400 → 88, h=300 → 96, min=88 → max(20, 88)=88
    expect(cockpitSpeedR(400, 300)).toBe(88);
  });

  it('all derived radii are non-negative for minimum speedR=20', () => {
    const r = cockpitDerivedRadii(20);
    expect(r.tickR).toBeGreaterThanOrEqual(0);
    expect(r.innerRMajor).toBeGreaterThanOrEqual(0);
    expect(r.innerRMinor).toBeGreaterThanOrEqual(0);
    expect(r.labelR).toBeGreaterThanOrEqual(0);
    expect(r.arcR).toBeGreaterThanOrEqual(0);
    expect(r.needleLen).toBeGreaterThanOrEqual(0);
  });

  it('derived radii clamp to 0 when speedR is very small', () => {
    // Even though speedR has a 20px floor, test the guard pattern directly
    const r = cockpitDerivedRadii(2);
    expect(r.tickR).toBe(0);
    expect(r.innerRMajor).toBe(0);
    expect(r.innerRMinor).toBe(0);
    expect(r.labelR).toBe(0);
    expect(r.arcR).toBe(0);
    expect(r.needleLen).toBe(0);
  });

  it('gR is at least 1 for zero-size canvas', () => {
    expect(cockpitGR(0, 0)).toBe(1);
  });

  it('steerR is at least 1 for zero-size canvas', () => {
    expect(cockpitSteerR(0, 0)).toBe(1);
  });

  it('gR returns computed value for normal canvas', () => {
    // w=400 → 72, h=300 → 84, min=72
    expect(cockpitGR(400, 300)).toBe(72);
  });

  it('steerR returns computed value for normal canvas', () => {
    // w=400 → 56, h=300 → 36, min=36
    expect(cockpitSteerR(400, 300)).toBeCloseTo(36, 5);
  });
});

describe('Chart guard: DrivingStyle NaN value clamping', () => {
  it('clamps NaN radar value to 0', () => {
    const rawVal = NaN;
    const val = Math.max(0, Math.min(1, Number.isFinite(rawVal) ? rawVal : 0));
    expect(val).toBe(0);
  });

  it('clamps Infinity radar value to 0', () => {
    const rawVal = Infinity;
    const val = Math.max(0, Math.min(1, Number.isFinite(rawVal) ? rawVal : 0));
    expect(val).toBe(0);
  });

  it('preserves valid radar values', () => {
    const rawVal = 0.75;
    const val = Math.max(0, Math.min(1, Number.isFinite(rawVal) ? rawVal : 0));
    expect(val).toBe(0.75);
  });
});
