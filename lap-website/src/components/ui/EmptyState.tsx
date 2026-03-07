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

export function EmptyState({ icon, title, hint, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4 text-center" role="status">
      {icon && (
        <div className="mb-4 text-steel/40" aria-hidden="true">
          {icon}
        </div>
      )}
      <h3 className="font-telemetry text-sm tracking-widest uppercase text-chalk mb-2">
        {title}
      </h3>
      {hint && (
        <p className="text-steel text-sm max-w-md mb-6">{hint}</p>
      )}
      {action && (
        action.href ? (
          <a
            href={action.href}
            className="inline-flex items-center justify-center min-h-[44px] px-6 py-2.5 border border-steel/40 text-chalk font-telemetry text-xs tracking-widest uppercase hover:border-chalk transition-colors focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--accent)] focus-visible:outline-offset-2"
          >
            {action.label}
          </a>
        ) : (
          <button
            type="button"
            onClick={action.onClick}
            className="inline-flex items-center justify-center min-h-[44px] px-6 py-2.5 border border-steel/40 text-chalk font-telemetry text-xs tracking-widest uppercase hover:border-chalk transition-colors focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--accent)] focus-visible:outline-offset-2"
          >
            {action.label}
          </button>
        )
      )}
    </div>
  );
}
