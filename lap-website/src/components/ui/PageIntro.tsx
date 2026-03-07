import type { ReactNode } from 'react';

interface PageIntroProps {
  title: string;
  subtitle?: string;
  eyebrow?: string;
  badge?: string;
  actions?: ReactNode;
}

export function PageIntro({ title, subtitle, eyebrow, badge, actions }: PageIntroProps) {
  return (
    <div className="mb-[var(--space-8)]">
      <div className="flex items-start justify-between">
        <div>
          {eyebrow && (
            <p className="font-telemetry text-steel text-[11px] tracking-[0.12em] uppercase mb-3">{eyebrow}</p>
          )}
          <h1 className="font-monument text-[var(--text-h1)] leading-[var(--lh-heading)] tracking-[var(--ls-display)]">
            {title}
            {badge && (
              <span className="ml-3 align-middle inline-block text-xs font-telemetry tracking-[0.12em] uppercase border border-pit-orange/40 text-pit-orange px-2 py-0.5 rounded">
                {badge}
              </span>
            )}
          </h1>
          {subtitle && (
            <p className="mt-[var(--space-2)] max-w-3xl text-steel text-lg font-body leading-[var(--lh-body)]">{subtitle}</p>
          )}
        </div>
        {actions && <div className="flex items-center gap-3 shrink-0">{actions}</div>}
      </div>
    </div>
  );
}
