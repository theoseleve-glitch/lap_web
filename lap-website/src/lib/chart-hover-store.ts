/**
 * chart-hover-store.ts — Distance-based hover synchronization across charts.
 *
 * All chart wrappers publish/subscribe to this store so hovering one chart
 * highlights the corresponding position (by distance in meters) on every
 * other chart and the track map.
 *
 * This replaces the Old Tool's direct global-function calls
 * (GpsTrace.updateMarkerByDistance, ChartSync.updateCrosshair, etc.)
 * with a single Zustand store that React components can subscribe to.
 */
import { create } from 'zustand';

interface ChartHoverState {
  /** Distance along the lap in meters, or null when no hover is active. */
  hoverDistance: number | null;
  /** Identifier of the chart that triggered the hover (prevents echo). */
  hoverSource: string | null;
  /** Whether cross-chart sync is enabled. */
  syncEnabled: boolean;
  /** Set hover state — called by the chart that the user is hovering. */
  setHover: (distance: number, source: string) => void;
  /** Clear hover state — called on mouseleave. */
  clearHover: () => void;
  /** Toggle sync on/off. */
  toggleSync: () => void;
}

// RAF-throttled setter: coalesces rapid mousemove events to one update per frame.
let _rafId: number | null = null;
let _pendingDistance: number | null = null;
let _pendingSource: string | null = null;

export const useChartHoverStore = create<ChartHoverState>((set, get) => ({
  hoverDistance: null,
  hoverSource: null,
  syncEnabled: true,
  setHover: (distance, source) => {
    if (!get().syncEnabled) return;
    _pendingDistance = distance;
    _pendingSource = source;
    if (_rafId === null) {
      _rafId = requestAnimationFrame(() => {
        _rafId = null;
        set({ hoverDistance: _pendingDistance, hoverSource: _pendingSource });
      });
    }
  },
  clearHover: () => {
    if (_rafId !== null) {
      cancelAnimationFrame(_rafId);
      _rafId = null;
    }
    _pendingDistance = null;
    _pendingSource = null;
    set({ hoverDistance: null, hoverSource: null });
  },
  toggleSync: () => {
    const next = !get().syncEnabled;
    if (!next) {
      // Clear active hover when disabling
      if (_rafId !== null) {
        cancelAnimationFrame(_rafId);
        _rafId = null;
      }
      _pendingDistance = null;
      _pendingSource = null;
      set({ syncEnabled: next, hoverDistance: null, hoverSource: null });
    } else {
      set({ syncEnabled: next });
    }
  },
}));
