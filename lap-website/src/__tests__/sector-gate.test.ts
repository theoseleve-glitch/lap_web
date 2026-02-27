import { describe, it, expect, beforeEach } from 'vitest';
import { useKernelStore } from '@/experience/state/store';
import { getSectorIndexForGate, shouldTriggerGate } from '@/experience/narrative/SectorGateController';

describe('Sector gate logic', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('getSectorIndexForGate maps chapter to sector tower index', () => {
    expect(getSectorIndexForGate(1)).toBe(0);
    expect(getSectorIndexForGate(3)).toBe(1);
    expect(getSectorIndexForGate(5)).toBe(2);
    expect(getSectorIndexForGate(8)).toBe(5);
    expect(getSectorIndexForGate(10)).toBeNull();
    expect(getSectorIndexForGate(2)).toBeNull();
  });

  it('shouldTriggerGate returns true only on first entry', () => {
    expect(shouldTriggerGate(1, new Set())).toBe(true);
    expect(shouldTriggerGate(1, new Set([1]))).toBe(false);
    expect(shouldTriggerGate(2, new Set())).toBe(false);
  });
});
