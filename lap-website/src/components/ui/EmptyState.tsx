import { type ReactNode } from 'react';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  hint?: string;
  action?: {
    label: string;
    href?: string;
    onClick?: () => void;
  };
}

const defaultIcon = (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <line x1="12" y1="8" x2="12" y2="12" />
    <line x1="12" y1="16" x2="12.01" y2="16" />
  </svg>
);

export function EmptyState({ icon, title, hint, action }: EmptyStateProps) {
  const btnClass =
    'inline-flex items-center justify-center min-h-[44px] px-5 py-2 ' +
    'text-xs font-telemetry uppercase tracking-[0.1em] rounded-lg ' +
    'border border-steel/20 text-chalk hover:bg-steel/8 transition-colors ' +
    'focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-gold/50 focus-visible:outline-offset-2';

  return (
    <div className="flex flex-col items-center justify-center py-12 px-6 text-center" role="status">
      <div className="w-12 h-12 rounded-full border border-steel/15 flex items-center justify-center mb-4 text-steel/40" aria-hidden="true">
        {icon ?? defaultIcon}
      </div>
      <h3 className="text-sm font-monument text-chalk mb-1">
        {title}
      </h3>
      {hint && (
        <p className="text-xs font-body text-steel max-w-xs mb-4">{hint}</p>
      )}
      {action && (
        action.href ? (
          <a href={action.href} className={btnClass}>
            {action.label}
          </a>
        ) : (
          <button type="button" onClick={action.onClick} className={btnClass}>
            {action.label}
          </button>
        )
      )}
    </div>
  );
}
