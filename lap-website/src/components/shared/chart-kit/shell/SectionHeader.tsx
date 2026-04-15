/**
 * SectionHeader — establishes the rhythm between tiers of the analytics page.
 *
 * Minimal, engineering-publication style: a muted numeric index, a small
 * uppercase title, an optional one-line description, and a hairline rule
 * extending to the right edge. No decorative elements.
 *
 * Use once per tier. Do NOT repeat inside tiers — grouping within a tier
 * is the job of the ChartHeader on each chart.
 */

import type { ReactNode } from 'react';

export interface SectionHeaderProps {
  /** Small numeric or short identifier ("01", "02", etc.). */
  index: string;
  /** Tier title, rendered UPPER CASE with wide tracking. */
  title: string;
  /** Optional one-line description — kept small and muted. */
  description?: string;
  /** Optional right-aligned action node (controls, filter, etc.). */
  actions?: ReactNode;
}

export function SectionHeader({
  index,
  title,
  description,
  actions,
}: SectionHeaderProps) {
  return (
    <header className="flex items-center gap-4 pt-2" aria-label={title}>
      <div className="flex items-baseline gap-3 shrink-0">
        <span
          className="text-[10px] font-telemetry text-steel/50 tracking-[0.25em]"
          aria-hidden
        >
          {index}
        </span>
        <h2 className="text-xs font-monument text-chalk uppercase tracking-[0.18em]">
          {title}
        </h2>
      </div>
      {description && (
        <span className="hidden md:inline text-[11px] font-telemetry text-steel/80 truncate">
          {description}
        </span>
      )}
      <div className="flex-1 h-px bg-steel/15" aria-hidden />
      {actions && <div className="shrink-0">{actions}</div>}
    </header>
  );
}
