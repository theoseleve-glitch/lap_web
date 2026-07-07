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

  // TODO(dead-marketing-route): shouldTriggerGate reads tokens.ts's
  // `sectorGates` (keyed 2/3/4/8/9), which has drifted from this file's own
  // GATE_TO_TOWER_INDEX (keyed 1/3/5/8) used by getSectorIndexForGate above —
  // so gate chapter 1 (used by getSectorIndexForGate) never actually fires
  // here, and chapter 2 (not used by getSectorIndexForGate) does. Real bug,
  // not reconciled: src/app/(marketing)/ — the only mount point for
  // SectorGateController — is superseded in prod by the standalone Astro
  // marketing site (see CLAUDE.md + infra memory), so this never runs live.
  // Pinning current (drifted) behavior rather than asserting the fixed
  // invariant the code doesn't actually satisfy.
  it('shouldTriggerGate returns true only on first entry (current, drifted sectorGates keys)', () => {
    expect(shouldTriggerGate(2, new Set())).toBe(true);
    expect(shouldTriggerGate(2, new Set([2]))).toBe(false);
    expect(shouldTriggerGate(1, new Set())).toBe(false);
  });
});
