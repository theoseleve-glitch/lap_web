/**
 * Tests for the chart-map hover synchronization store and integration logic.
 *
 * Validates:
 * 1. Zustand store state transitions (setHover, clearHover, source tracking)
 * 2. Index clamping for mismatched data lengths
 * 3. Source-based filtering (speed-trace hover only reaches track-map, not self)
 * 4. Bidirectional sync correctness
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useChartHoverStore } from '@/lib/chart-hover-store';

/* ─── Helpers ─────────────────────────────────────────────────────────── */

/** Reset store to initial state between tests */
function resetStore() {
  useChartHoverStore.setState({ hoverIndex: null, source: null });
}

/** Simulate the index-clamping logic used in TrackMap draw() */
function clampExternalIndex(extIdx: number, dataLength: number): number | null {
  if (extIdx >= 0 && extIdx < dataLength) return extIdx;
  if (extIdx >= dataLength) return dataLength - 1;
  return null;
}

/** Simulate the source-filtering logic in the session detail page */
function getExternalIndex(
  hoverIndex: number | null,
  hoverSource: string | null,
  targetComponent: 'speed-trace' | 'track-map',
): number | undefined {
  // Only pass hover to the OTHER component
  const expectedSource = targetComponent === 'speed-trace' ? 'track-map' : 'speed-trace';
  if (hoverSource === expectedSource && hoverIndex != null) return hoverIndex;
  return undefined;
}

/* ─── Store Tests ─────────────────────────────────────────────────────── */

describe('useChartHoverStore', () => {
  beforeEach(resetStore);

  it('starts with null hover state', () => {
    const state = useChartHoverStore.getState();
    expect(state.hoverIndex).toBeNull();
    expect(state.source).toBeNull();
  });

  it('setHover updates index and source', () => {
    useChartHoverStore.getState().setHover(42, 'speed-trace');
    const state = useChartHoverStore.getState();
    expect(state.hoverIndex).toBe(42);
    expect(state.source).toBe('speed-trace');
  });

  it('clearHover resets to null', () => {
    useChartHoverStore.getState().setHover(10, 'track-map');
    useChartHoverStore.getState().clearHover();
    const state = useChartHoverStore.getState();
    expect(state.hoverIndex).toBeNull();
    expect(state.source).toBeNull();
  });

  it('supports rapid updates without stale state', () => {
    const { setHover } = useChartHoverStore.getState();
    setHover(0, 'speed-trace');
    setHover(50, 'speed-trace');
    setHover(100, 'speed-trace');
    const state = useChartHoverStore.getState();
    expect(state.hoverIndex).toBe(100);
    expect(state.source).toBe('speed-trace');
  });

  it('switching source overwrites previous', () => {
    const { setHover } = useChartHoverStore.getState();
    setHover(10, 'speed-trace');
    setHover(20, 'track-map');
    const state = useChartHoverStore.getState();
    expect(state.hoverIndex).toBe(20);
    expect(state.source).toBe('track-map');
  });

  it('setHover with null index and null source clears state', () => {
    useChartHoverStore.getState().setHover(42, 'speed-trace');
    useChartHoverStore.getState().setHover(null, null);
    const state = useChartHoverStore.getState();
    expect(state.hoverIndex).toBeNull();
    expect(state.source).toBeNull();
  });
});

/* ─── Index Clamping Tests ────────────────────────────────────────────── */

describe('External index clamping (TrackMap)', () => {
  it('passes through valid index within range', () => {
    expect(clampExternalIndex(50, 200)).toBe(50);
  });

  it('clamps index at array boundary', () => {
    expect(clampExternalIndex(200, 200)).toBe(199);
  });

  it('clamps large overshoot', () => {
    expect(clampExternalIndex(1000, 100)).toBe(99);
  });

  it('passes through index 0', () => {
    expect(clampExternalIndex(0, 100)).toBe(0);
  });

  it('passes through last valid index', () => {
    expect(clampExternalIndex(99, 100)).toBe(99);
  });

  it('returns null for negative index', () => {
    expect(clampExternalIndex(-1, 100)).toBeNull();
  });
});

/* ─── Source-Based Filtering Tests ────────────────────────────────────── */

describe('Source-based hover routing', () => {
  it('speed-trace hover is passed to track-map', () => {
    const idx = getExternalIndex(42, 'speed-trace', 'track-map');
    expect(idx).toBe(42);
  });

  it('speed-trace hover is NOT passed to speed-trace (no self-loop)', () => {
    const idx = getExternalIndex(42, 'speed-trace', 'speed-trace');
    expect(idx).toBeUndefined();
  });

  it('track-map hover is passed to speed-trace', () => {
    const idx = getExternalIndex(10, 'track-map', 'speed-trace');
    expect(idx).toBe(10);
  });

  it('track-map hover is NOT passed to track-map (no self-loop)', () => {
    const idx = getExternalIndex(10, 'track-map', 'track-map');
    expect(idx).toBeUndefined();
  });

  it('null source returns undefined', () => {
    const idx = getExternalIndex(42, null, 'track-map');
    expect(idx).toBeUndefined();
  });

  it('null index returns undefined', () => {
    const idx = getExternalIndex(null, 'speed-trace', 'track-map');
    expect(idx).toBeUndefined();
  });
});

/* ─── Integration: Full Sync Cycle ────────────────────────────────────── */

describe('Full hover sync cycle', () => {
  beforeEach(resetStore);

  it('speed-trace hover → store → track-map receives index', () => {
    // 1. SpeedTrace publishes hover
    useChartHoverStore.getState().setHover(75, 'speed-trace');

    // 2. Session page reads store
    const { hoverIndex, source } = useChartHoverStore.getState();

    // 3. Route to TrackMap (not to SpeedTrace itself)
    const trackMapIdx = getExternalIndex(hoverIndex, source, 'track-map');
    const speedTraceIdx = getExternalIndex(hoverIndex, source, 'speed-trace');

    expect(trackMapIdx).toBe(75);
    expect(speedTraceIdx).toBeUndefined();
  });

  it('track-map hover → store → speed-trace receives index', () => {
    // 1. TrackMap publishes hover
    useChartHoverStore.getState().setHover(30, 'track-map');

    // 2. Session page reads store
    const { hoverIndex, source } = useChartHoverStore.getState();

    // 3. Route to SpeedTrace (not to TrackMap itself)
    const speedTraceIdx = getExternalIndex(hoverIndex, source, 'speed-trace');
    const trackMapIdx = getExternalIndex(hoverIndex, source, 'track-map');

    expect(speedTraceIdx).toBe(30);
    expect(trackMapIdx).toBeUndefined();
  });

  it('clearing hover removes state for all consumers', () => {
    useChartHoverStore.getState().setHover(50, 'speed-trace');
    useChartHoverStore.getState().clearHover();

    const { hoverIndex, source } = useChartHoverStore.getState();
    const trackMapIdx = getExternalIndex(hoverIndex, source, 'track-map');
    const speedTraceIdx = getExternalIndex(hoverIndex, source, 'speed-trace');

    expect(trackMapIdx).toBeUndefined();
    expect(speedTraceIdx).toBeUndefined();
  });
});
