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
  /** Set hover state — called by the chart that the user is hovering. */
  setHover: (distance: number, source: string) => void;
  /** Clear hover state — called on mouseleave. */
  clearHover: () => void;
}

export const useChartHoverStore = create<ChartHoverState>((set) => ({
  hoverDistance: null,
  hoverSource: null,
  setHover: (distance, source) =>
    set({ hoverDistance: distance, hoverSource: source }),
  clearHover: () => set({ hoverDistance: null, hoverSource: null }),
}));
