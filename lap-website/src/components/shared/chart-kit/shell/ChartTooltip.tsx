/**
 * ChartTooltip — overlay-positioned tooltip rendered as DOM (not canvas).
 *
 * Typography:
 *   title  — 9px uppercase tracking-[0.18em] steel/80      (context cue)
 *   label  — 11px telemetry steel/80                        (what)
 *   value  — 11px telemetry chalk tabular-nums              (how much)
 *
 * Chrome:
 *   bg         asphalt @ 96% (chartColor.tooltipBg via the backdrop class)
 *   border     steel @ 20%, 1px
 *   radius     rounded-md (8px) — tight, not pill-like
 *   shadow     shadow-lg — subtle elevation, no glow
 *
 * Auto-flips horizontally when near the right edge.
 */

import type { ReactNode } from 'react';

export interface TooltipRow {
  label: string;
  value: string;
  /** Optional accent dot color matching the series this row refers to. */
  color?: string;
}

export interface ChartTooltipProps {
  /** Pixel X coordinate inside the chart body. */
  x: number;
  /** Pixel Y coordinate inside the chart body. */
  y: number;
  /** Total chart body width — used for edge-flip detection. */
  containerWidth: number;
  /** Optional title (e.g. "245m"). */
  title?: string;
  /** Tabular rows shown under the title. */
  rows?: readonly TooltipRow[];
  /** Or pass arbitrary content. Rows are ignored if children present. */
  children?: ReactNode;
}

const TOOLTIP_OFFSET = 12;
const ESTIMATED_WIDTH = 180;

export function ChartTooltip({
  x,
  y,
  containerWidth,
  title,
  rows,
  children,
}: ChartTooltipProps) {
  // Flip horizontally if too close to the right edge.
  const wouldOverflow = x + TOOLTIP_OFFSET + ESTIMATED_WIDTH > containerWidth;
  const left = wouldOverflow ? x - TOOLTIP_OFFSET : x + TOOLTIP_OFFSET;
  const transform = wouldOverflow ? 'translate(-100%, -50%)' : 'translate(0, -50%)';

  return (
    <div
      className="pointer-events-none absolute z-30 rounded-md border border-steel/20 bg-asphalt/95 backdrop-blur-sm px-3 py-2 shadow-lg min-w-[132px]"
      style={{ left, top: y, transform, fontVariantNumeric: 'tabular-nums slashed-zero' }}
      role="tooltip"
    >
      {title && (
        <div className="text-[9px] font-telemetry text-steel/80 uppercase tracking-[0.18em] mb-1.5">
          {title}
        </div>
      )}
      {children}
      {rows && rows.length > 0 && (
        <div className="space-y-1">
          {rows.map((r) => (
            <div
              key={r.label}
              className="flex items-center gap-2 text-[11px] font-telemetry leading-tight"
            >
              {r.color && (
                <span
                  className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ backgroundColor: r.color }}
                  aria-hidden
                />
              )}
              <span className="text-steel/80">{r.label}</span>
              <span className="text-chalk ml-auto tabular-nums">{r.value}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
