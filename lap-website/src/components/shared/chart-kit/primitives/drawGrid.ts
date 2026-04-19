/**
 * drawGrid — pure canvas gridline renderer.
 *
 * Quiet, low-contrast horizontal/vertical lines through the plot area.
 * Optional `emphasizeZero` draws the zero baseline at higher contrast —
 * essential for delta charts and any chart with positive/negative values.
 */

import { defaultTheme, type ChartTheme } from '../tokens';
import type { LinearScale } from '../scales';
import type { PlotRect } from './drawAxis';

export interface DrawGridOptions {
  plot: PlotRect;
  /** X-scale and ticks for vertical gridlines (omit to skip). */
  x?: { scale: LinearScale; ticks: readonly number[] };
  /** Y-scale and ticks for horizontal gridlines (omit to skip). */
  y?: { scale: LinearScale; ticks: readonly number[] };
  /** Draw the y=0 line at higher contrast. Default true if scale crosses 0. */
  emphasizeZero?: boolean;
  theme?: ChartTheme;
}

export function drawGrid(ctx: CanvasRenderingContext2D, opts: DrawGridOptions): void {
  const theme = opts.theme ?? defaultTheme;
  const { plot } = opts;

  ctx.save();
  ctx.lineWidth = theme.stroke.grid;
  ctx.strokeStyle = theme.color.grid;

  // Horizontal gridlines (y ticks)
  if (opts.y) {
    const { scale, ticks } = opts.y;
    for (const t of ticks) {
      const py = scale.toPixel(t);
      if (py < plot.top - 0.5 || py > plot.top + plot.height + 0.5) continue;
      ctx.beginPath();
      ctx.moveTo(plot.left, py);
      ctx.lineTo(plot.left + plot.width, py);
      ctx.stroke();
    }
  }

  // Vertical gridlines (x ticks)
  if (opts.x) {
    const { scale, ticks } = opts.x;
    for (const t of ticks) {
      const px = scale.toPixel(t);
      if (px < plot.left - 0.5 || px > plot.left + plot.width + 0.5) continue;
      ctx.beginPath();
      ctx.moveTo(px, plot.top);
      ctx.lineTo(px, plot.top + plot.height);
      ctx.stroke();
    }
  }

  // Zero baseline (emphasized)
  if (opts.y) {
    const [yMin, yMax] = opts.y.scale.domain;
    const crossesZero = yMin < 0 && yMax > 0;
    const emphasize = opts.emphasizeZero ?? crossesZero;
    if (emphasize && crossesZero) {
      const py = opts.y.scale.toPixel(0);
      ctx.lineWidth = theme.stroke.gridStrong;
      ctx.strokeStyle = theme.color.gridStrong;
      ctx.beginPath();
      ctx.moveTo(plot.left, py);
      ctx.lineTo(plot.left + plot.width, py);
      ctx.stroke();
    }
  }

  ctx.restore();
}
