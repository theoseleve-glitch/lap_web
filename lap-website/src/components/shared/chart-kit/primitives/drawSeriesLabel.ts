/**
 * drawSeriesLabel — small inline label anchored to a series endpoint.
 *
 * Used to annotate the final value of a line, the last point of a delta,
 * or any single point that benefits from an in-canvas label rather than
 * a legend entry far away.
 */

import { defaultTheme, type ChartTheme } from '../tokens';

export interface DrawSeriesLabelOptions {
  /** Pixel X position to anchor to. */
  x: number;
  /** Pixel Y position to anchor to. */
  y: number;
  text: string;
  color?: string;
  /** Horizontal anchor. Default 'start'. */
  anchor?: 'start' | 'end' | 'middle';
  /** Vertical anchor. Default 'middle'. */
  baseline?: 'top' | 'middle' | 'bottom';
  /** Use bold weight. */
  bold?: boolean;
  /** Pixel offset away from the anchor point. Default 6. */
  offset?: number;
  theme?: ChartTheme;
}

export function drawSeriesLabel(
  ctx: CanvasRenderingContext2D,
  opts: DrawSeriesLabelOptions,
): void {
  const theme = opts.theme ?? defaultTheme;
  const anchor = opts.anchor ?? 'start';
  const baseline = opts.baseline ?? 'middle';
  const offset = opts.offset ?? 6;

  ctx.save();
  ctx.font = opts.bold
    ? theme.font.tooltipBold
    : theme.font.seriesLabel;
  ctx.fillStyle = opts.color ?? theme.color.text;
  ctx.textAlign = anchor;
  ctx.textBaseline = baseline;

  const dx = anchor === 'end' ? -offset : anchor === 'start' ? offset : 0;
  ctx.fillText(opts.text, opts.x + dx, opts.y);

  ctx.restore();
}
