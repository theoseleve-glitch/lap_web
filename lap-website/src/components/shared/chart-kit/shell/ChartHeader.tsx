/**
 * ChartHeader — title + subtitle + info + actions row.
 *
 * One canonical header layout for every chart:
 *  - title (font-monument, chalk)
 *  - subtitle (font-telemetry, steel) — optional, sits inline after title
 *  - info button (?) — opens an a11y description when needed
 *  - actions (right-aligned) — lap selectors, mode toggles, tab buttons
 *
 * No chart should render its own <h3> ad-hoc.
 */

import type { ReactNode } from 'react';

export interface ChartHeaderProps {
  title: string;
  subtitle?: string;
  /** Optional info text — shown as a `title=` tooltip on a small (i) marker. */
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
    <header className="flex items-center justify-between gap-3 mb-3 min-h-[24px]">
      <div className="flex items-baseline gap-2 min-w-0">
        <Heading className="text-sm font-monument text-chalk truncate">
          {title}
        </Heading>
        {subtitle && (
          <span className="text-[11px] font-telemetry text-steel truncate">
            {subtitle}
          </span>
        )}
        {info && (
          <span
            className="text-[10px] font-telemetry text-steel/60 cursor-help select-none"
            title={info}
            aria-label={info}
          >
            (i)
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
