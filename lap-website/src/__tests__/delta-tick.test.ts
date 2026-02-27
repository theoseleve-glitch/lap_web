import { describe, it, expect, beforeEach } from 'vitest';
import { useKernelStore } from '@/experience/state/store';
import { computeDeltaJitter, computeDeltaValue } from '@/experience/narrative/DeltaTickController';

describe('Delta tick logic', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('computeDeltaJitter maps mask coverage to jitter', () => {
    expect(computeDeltaJitter(0)).toBe(8);
    expect(computeDeltaJitter(0.5)).toBe(4);
    expect(computeDeltaJitter(1.0)).toBe(0);
  });

  it('computeDeltaValue trends toward 0 with progress', () => {
    const base = 0.5;
    expect(computeDeltaValue(base, 0)).toBeCloseTo(0.5);
    expect(computeDeltaValue(base, 0.5)).toBeCloseTo(0.25);
    expect(computeDeltaValue(base, 1.0)).toBeCloseTo(0);
  });

  it('computeDeltaValue respects settled state', () => {
    useKernelStore.getState().settleDelta();
    const { hudDelta } = useKernelStore.getState();
    expect(hudDelta.settled).toBe(true);
  });
});
