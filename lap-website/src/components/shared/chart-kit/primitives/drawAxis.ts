/**
 * drawAxis — pure canvas axis renderer.
 *
 * Draws the axis line, tick marks, and tick labels for one axis of a chart.
 * Adheres to chart-kit theme: no inline colors, no inline fonts.
 *
 * Y-axis labels are right-aligned to the axis with consistent decimal width.
 * X-axis labels are centered under their tick.
 */

import { defaultTheme, type ChartTheme } from '../tokens';
import type { LinearScale } from '../scales';
import { niceTicks, decimalsForStep } from '../ticks';

export interface PlotRect {
  /** Left edge of plot area, in CSS pixels. */
  left: number;
  /** Top edge of plot area, in CSS pixels. */
  top: number;
  /** Plot area width. */
  width: number;
  /** Plot area height. */
  height: number;
}

export interface DrawAxisOptions {
  orientation: 'x' | 'y';
  plot: PlotRect;
  scale: LinearScale;
  /** Pre-computed tick values. If omitted, `niceTicks` is used. */
  ticks?: readonly number[];
  /** Target tick count when ticks are auto-generated. Default 6. */
  tickCount?: number;
  /** Format function. If omitted, decimals are inferred from step size. */
  format?: (value: number) => string;
  /** Optional axis title (e.g. "Distance (m)"). */
  title?: string;
  /** Show the axis line itself. Default true. */
  showAxisLine?: boolean;
  /** Show tick marks (small lines extending from the axis). Default true. */
  showTicks?: boolean;
  theme?: ChartTheme;
}

const TICK_LENGTH = 4;

export function drawAxis(ctx: CanvasRenderingContext2D, opts: DrawAxisOptions): void {
  const theme = opts.theme ?? defaultTheme;
  const { orientation, plot, scale } = opts;
  const showAxisLine = opts.showAxisLine ?? true;
  const showTicks = opts.showTicks ?? true;

  const ticks =
    opts.ticks ??
    niceTicks(scale.domain[0], scale.domain[1], opts.tickCount ?? 6);

  // Determine step (assumes uniform spacing; ok since niceTicks produces uniform)
  const step = ticks.length >= 2 ? Math.abs(ticks[1] - ticks[0]) : 1;
  const decimals = decimalsForStep(step);
  const fmt = opts.format ?? ((v: number) => v.toFixed(decimals));

  ctx.save();
  ctx.strokeStyle = theme.color.axis;
  ctx.lineWidth = theme.stroke.axis;
  // Canvas doesn't honour CSS font-variant-numeric, but Space Mono is monospace
  // so digits align naturally. Keep it consistent with DOM typography (10px).
  ctx.fillStyle = theme.color.textMuted;
  ctx.font = theme.font.tickLabel;

  if (orientation === 'x') {
    const y = plot.top + plot.height;

    // Axis line
    if (showAxisLine) {
      ctx.beginPath();
      ctx.moveTo(plot.left, y);
      ctx.lineTo(plot.left + plot.width, y);
      ctx.stroke();
    }

    // Ticks + labels
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (const t of ticks) {
      const x = scale.toPixel(t);
      if (x < plot.left - 0.5 || x > plot.left + plot.width + 0.5) continue;
      if (showTicks) {
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x, y + TICK_LENGTH);
        ctx.stroke();
      }
      ctx.fillText(fmt(t), x, y + TICK_LENGTH + 4);
    }

    if (opts.title) {
      ctx.font = theme.font.axisTitle;
      ctx.fillStyle = theme.color.textSecondary;
      ctx.fillText(opts.title, plot.left + plot.width / 2, y + 22);
    }
  } else {
    const x = plot.left;

    if (showAxisLine) {
      ctx.beginPath();
      ctx.moveTo(x, plot.top);
      ctx.lineTo(x, plot.top + plot.height);
      ctx.stroke();
    }

    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (const t of ticks) {
      const py = scale.toPixel(t);
      if (py < plot.top - 0.5 || py > plot.top + plot.height + 0.5) continue;
      if (showTicks) {
        ctx.beginPath();
        ctx.moveTo(x, py);
        ctx.lineTo(x - TICK_LENGTH, py);
        ctx.stroke();
      }
      ctx.fillText(fmt(t), x - TICK_LENGTH - 4, py);
    }

    if (opts.title) {
      ctx.save();
      ctx.font = theme.font.axisTitle;
      ctx.fillStyle = theme.color.textSecondary;
      ctx.translate(plot.left - 38, plot.top + plot.height / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(opts.title, 0, 0);
      ctx.restore();
    }
  }

  ctx.restore();
}
