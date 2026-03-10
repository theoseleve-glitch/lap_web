/**
 * Chart wrappers — Re-exports from shared chart library.
 *
 * App-specific names (GpsTrace, SpeedTraceZoom) map to the shared
 * library's canonical names (TrackMap, SpeedTraceChart) for backward
 * compatibility with existing session detail and visualize pages.
 */
export { SpeedTraceZoom } from './SpeedTraceZoom';
export { GpsTrace } from './GpsTrace';
export { GGExplorer } from './GGExplorer';
export { useVanillaChart } from './useVanillaChart';
export { CornerDefiner } from './CornerDefiner';
