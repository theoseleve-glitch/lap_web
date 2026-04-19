/**
 * drawReferenceLine — horizontal or vertical reference at a domain value.
 *
 * Use cases: best-lap target, theoretical floor, max permitted G-load, etc.
 * Renders the line and an optional inline label at the right/top edge.
 */

import { defaultTheme, type ChartTheme } from '../tokens';
import type { LinearScale } from '../scales';
import type { PlotRect } from './drawAxis';

export interface DrawReferenceLineOptions {
  orientation: 'horizontal' | 'vertical';
  plot: PlotRect;
  scale: LinearScale;
  /** Domain value at which to draw the line. */
  value: number;
  /** Optional label rendered at the line endpoint. */
  label?: string;
  /** Color. Defaults to the chart's neutral series color. */
  color?: string;
  /** Dashed style. Defaults to the theme's reference dash. */
  dashed?: boolean;
  theme?: ChartTheme;
}

export function drawReferenceLine(
  ctx: CanvasRenderingContext2D,
  opts: DrawReferenceLineOptions,
): void {
  const theme = opts.theme ?? defaultTheme;
  const { plot, scale, value } = opts;
  const color = opts.color ?? theme.color.series.neutral;
  const dashed = opts.dashed ?? true;

  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = theme.stroke.reference;
  if (dashed) ctx.setLineDash([...theme.dash.reference]);

  if (opts.orientation === 'horizontal') {
    const py = scale.toPixel(value);
    if (py < plot.top || py > plot.top + plot.height) {
      ctx.restore();
      return;
    }
    ctx.beginPath();
    ctx.moveTo(plot.left, py);
    ctx.lineTo(plot.left + plot.width, py);
    ctx.stroke();
    if (opts.label) {
      ctx.setLineDash([]);
      ctx.font = theme.font.seriesLabel;
      ctx.fillStyle = color;
      ctx.textAlign = 'right';
      ctx.textBaseline = 'bottom';
      ctx.fillText(opts.label, plot.left + plot.width - 4, py - 3);
    }
  } else {
    const px = scale.toPixel(value);
    if (px < plot.left || px > plot.left + plot.width) {
      ctx.restore();
      return;
    }
    ctx.beginPath();
    ctx.moveTo(px, plot.top);
    ctx.lineTo(px, plot.top + plot.height);
    ctx.stroke();
    if (opts.label) {
      ctx.setLineDash([]);
      ctx.font = theme.font.seriesLabel;
      ctx.fillStyle = color;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      ctx.fillText(opts.label, px + 4, plot.top + 2);
    }
  }

  ctx.restore();
}
