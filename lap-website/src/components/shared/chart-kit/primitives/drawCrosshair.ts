/**
 * drawCrosshair — vertical (and optional horizontal) hover indicator.
 *
 * Always quiet — this is a frame element, not data. Default behaviour is a
 * thin, low-opacity vertical line spanning the plot area at the hover x.
 */

import { defaultTheme, type ChartTheme } from '../tokens';
import type { PlotRect } from './drawAxis';

export interface DrawCrosshairOptions {
  plot: PlotRect;
  /** Pixel X position. If null/undefined, no vertical line is drawn. */
  x?: number | null;
  /** Pixel Y position. If null/undefined, no horizontal line is drawn. */
  y?: number | null;
  /** Override the default crosshair color. */
  color?: string;
  /** Override the default dash pattern. Pass [] for solid. */
  dash?: readonly number[];
  theme?: ChartTheme;
}

export function drawCrosshair(ctx: CanvasRenderingContext2D, opts: DrawCrosshairOptions): void {
  const theme = opts.theme ?? defaultTheme;
  const { plot } = opts;

  const xValid = opts.x != null && opts.x >= plot.left && opts.x <= plot.left + plot.width;
  const yValid = opts.y != null && opts.y >= plot.top && opts.y <= plot.top + plot.height;
  if (!xValid && !yValid) return;

  ctx.save();
  ctx.strokeStyle = opts.color ?? theme.color.crosshair;
  ctx.lineWidth = theme.stroke.crosshair;
  ctx.setLineDash([...(opts.dash ?? theme.dash.crosshair)]);

  if (xValid) {
    ctx.beginPath();
    ctx.moveTo(opts.x as number, plot.top);
    ctx.lineTo(opts.x as number, plot.top + plot.height);
    ctx.stroke();
  }
  if (yValid) {
    ctx.beginPath();
    ctx.moveTo(plot.left, opts.y as number);
    ctx.lineTo(plot.left + plot.width, opts.y as number);
    ctx.stroke();
  }

  ctx.restore();
}
