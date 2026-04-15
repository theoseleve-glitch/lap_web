/**
 * Chart kit — barrel export.
 *
 * Import everything you need from `@/components/shared/chart-kit`.
 * Do not deep-import from internal paths — they are private to the kit.
 */

// ── Tokens ────────────────────────────────────────────────────────────────
export {
  chartColor,
  chartSpacing,
  plotPadding,
  chartFont,
  chartStroke,
  chartDash,
  chartRadius,
  defaultTheme,
  type Density,
  type ChartTheme,
} from './tokens';

// ── Scales + ticks ────────────────────────────────────────────────────────
export {
  createLinearScale,
  createSymmetricScale,
  closestIndex,
  type LinearScale,
} from './scales';

export {
  niceTicks,
  niceSymmetricTicks,
  decimalsForStep,
} from './ticks';

// ── Drawing primitives ────────────────────────────────────────────────────
export {
  drawAxis,
  type DrawAxisOptions,
  type PlotRect,
} from './primitives/drawAxis';
export { drawGrid, type DrawGridOptions } from './primitives/drawGrid';
export { drawCrosshair, type DrawCrosshairOptions } from './primitives/drawCrosshair';
export { drawSeriesLabel, type DrawSeriesLabelOptions } from './primitives/drawSeriesLabel';
export { drawReferenceLine, type DrawReferenceLineOptions } from './primitives/drawReferenceLine';

// ── Hooks ─────────────────────────────────────────────────────────────────
export {
  useChartCanvas,
  type ChartCanvas,
  type UseChartCanvasOptions,
} from './hooks/useChartCanvas';
export {
  useChartPointer,
  type ChartPointerBounds,
  type ChartPointerState,
  type UseChartPointerOptions,
} from './hooks/useChartPointer';

// ── Shell components ──────────────────────────────────────────────────────
export { ChartCard, type ChartCardProps, type CardTone } from './shell/ChartCard';
export { ChartHeader, type ChartHeaderProps } from './shell/ChartHeader';
export { ChartBody, type ChartBodyProps } from './shell/ChartBody';
export { ChartLegend, type ChartLegendProps, type LegendItem } from './shell/ChartLegend';
export { ChartTooltip, type ChartTooltipProps, type TooltipRow } from './shell/ChartTooltip';
export {
  ChartLoadingState,
  ChartEmptyState,
  ChartErrorState,
  type ChartLoadingStateProps,
  type ChartEmptyStateProps,
  type ChartErrorStateProps,
} from './shell/ChartStates';
