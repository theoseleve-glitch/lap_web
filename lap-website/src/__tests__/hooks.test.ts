import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useDelta } from '@/hooks/useDelta';
import { computeCornerDelta } from '@/lib/corner-physics';

describe('useDelta', () => {
  it('starts at 0', () => {
    const { result } = renderHook(() => useDelta());
    expect(result.current.delta).toBe(0);
    expect(result.current.totalDelta).toBe(0);
  });

  it('accumulates deltas', () => {
    const { result } = renderHook(() => useDelta());
    act(() => result.current.addDelta(-0.18));
    expect(result.current.delta).toBe(-0.18);
    act(() => result.current.addDelta(-0.05));
    expect(result.current.totalDelta).toBeCloseTo(-0.23);
  });

  it('resets', () => {
    const { result } = renderHook(() => useDelta());
    act(() => result.current.addDelta(-0.18));
    act(() => result.current.reset());
    expect(result.current.delta).toBe(0);
    expect(result.current.totalDelta).toBe(0);
  });
});

describe('computeCornerDelta', () => {
  it('returns ~0 for optimal positions', () => {
    const result = computeCornerDelta(
      { x: 0.15, y: 0.9 },
      { x: 0.55, y: 0.45 },
      { x: 0.95, y: 0.15 },
    );
    expect(Math.abs(result.delta)).toBeLessThan(0.05);
    expect(result.lineLength).toBeCloseTo(1.0, 1);
  });

  it('returns positive delta for wide line', () => {
    const result = computeCornerDelta(
      { x: 0.15, y: 0.9 },
      { x: 0.75, y: 0.65 }, // wide apex
      { x: 0.95, y: 0.15 },
    );
    expect(result.delta).toBeLessThan(0); // wider line = more penalty
    expect(result.lineLength).toBeGreaterThan(1.0);
  });
});
