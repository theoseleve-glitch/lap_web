/**
 * ChartHeader — title + subtitle + info + actions row.
 *
 * One canonical header layout for every chart:
 *  - title (font-monument, chalk, 13px) — concise, confident
 *  - subtitle (font-telemetry, steel/75, 11px) — optional, inline after title
 *    separated by a thin middle-dot for rhythm
 *  - info (ⓘ) — small circle-i with title-attr description on hover
 *  - actions (right-aligned) — lap selectors, mode toggles, tab buttons
 *
 * Rules:
 *  - 13px title (not 14px) — restrained, engineering-tool feel
 *  - subtitle at steel/75 — quieter than titles, louder than axis labels
 *  - tabular-nums not needed here (no digits); applied where values render
 */

import type { ReactNode } from 'react';

export interface ChartHeaderProps {
  title: string;
  subtitle?: string;
  /** Optional info text — shown as a `title=` tooltip on a small ⓘ marker. */
  info?: string;
  /** Right-aligned controls (e.g. lap selector, mode buttons). */
  actions?: ReactNode;
  /** Override the heading level. Default 3. */
  as?: 'h2' | 'h3' | 'h4';
}

export function ChartHeader({
  title,
  subtitle,
  info,
  actions,
  as: Heading = 'h3',
}: ChartHeaderProps) {
  return (
    <header className="flex items-center justify-between gap-3 mb-3 min-h-[22px]">
      <div className="flex items-baseline gap-2 min-w-0">
        <Heading className="text-[13px] leading-5 font-monument text-chalk truncate tracking-[-0.005em]">
          {title}
        </Heading>
        {subtitle && (
          <>
            <span className="text-steel/40 text-[10px] select-none" aria-hidden>
              ·
            </span>
            <span className="text-[11px] font-telemetry text-steel/75 truncate">
              {subtitle}
            </span>
          </>
        )}
        {info && (
          <span
            className="text-[11px] font-telemetry text-steel/50 hover:text-steel cursor-help select-none transition-colors"
            title={info}
            aria-label={info}
          >
            ⓘ
          </span>
        )}
      </div>
      {actions && (
        <div className="flex items-center gap-2 shrink-0">
          {actions}
        </div>
      )}
    </header>
  );
}
