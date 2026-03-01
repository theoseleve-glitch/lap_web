/**
 * Chart wrappers — React components that bridge the Old Tool's vanilla JS
 * chart modules into the Next.js frontend.
 *
 * Each wrapper:
 *  1. Loads infrastructure scripts (ModuleManager, LifecycleHelpers, Theme, FetchHelper)
 *  2. Loads the chart-specific JS module(s)
 *  3. Patches FetchHelper to prepend the API base URL
 *  4. Creates DOM elements with the expected IDs for the vanilla JS to find
 *  5. Bridges hover events to the Zustand chart-hover-store
 *  6. Cleans up on unmount
 */
export { SpeedTraceZoom } from './SpeedTraceZoom';
export { GpsTrace } from './GpsTrace';
export { GGExplorer } from './GGExplorer';
export { useVanillaChart } from './useVanillaChart';
