/**
 * Shared hover state for chart-map synchronization.
 *
 * When hovering on SpeedTrace, the corresponding GPS position is highlighted
 * on TrackMap, and vice versa.  The store holds a single normalized index
 * (0..N-1 into the data arrays shared by both components).
 */
import { create } from 'zustand';

export interface ChartHoverState {
  /** Index into the data array, or null when not hovering */
  hoverIndex: number | null;
  /** Which component originated the hover ('speed-trace' | 'track-map' | null) */
  source: string | null;
  /** Set hover index from a specific source component */
  setHover: (index: number | null, source: string | null) => void;
  /** Clear hover state */
  clearHover: () => void;
}

export const useChartHoverStore = create<ChartHoverState>((set) => ({
  hoverIndex: null,
  source: null,
  setHover: (index, source) => set({ hoverIndex: index, source }),
  clearHover: () => set({ hoverIndex: null, source: null }),
}));
