/**
 * PageHeader — standardized page title + subtitle + actions row.
 *
 * Every app page uses this instead of ad-hoc <h1> + <div> combinations.
 * Consistent vertical rhythm, typography hierarchy, and action placement.
 *
 * Usage:
 *   <PageHeader
 *     title="Sessions"
 *     subtitle="Your telemetry session history"
 *     actions={<Button>Upload</Button>}
 *   />
 */

import type { ReactNode } from 'react';

export interface PageHeaderProps {
  title: string;
  subtitle?: string;
  /** Right-aligned controls (upload button, filter, etc.) */
  actions?: ReactNode;
  /** Optional breadcrumb trail rendered above the title. */
  breadcrumb?: ReactNode;
  /** Heading level. Default h1. */
  as?: 'h1' | 'h2';
}

export function PageHeader({
  title,
  subtitle,
  actions,
  breadcrumb,
  as: Heading = 'h1',
}: PageHeaderProps) {
  return (
    <header className="mb-6">
      {breadcrumb && (
        <nav className="mb-2 text-[10px] font-telemetry text-steel/50 uppercase tracking-[0.15em]">
          {breadcrumb}
        </nav>
      )}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <Heading className="text-lg font-monument text-chalk tracking-[-0.01em] leading-tight">
            {title}
          </Heading>
          {subtitle && (
            <p className="mt-1 text-sm font-body text-steel">
              {subtitle}
            </p>
          )}
        </div>
        {actions && (
          <div className="flex items-center gap-2 shrink-0 pt-0.5">
            {actions}
          </div>
        )}
      </div>
    </header>
  );
}
