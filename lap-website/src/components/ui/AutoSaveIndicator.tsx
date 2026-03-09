'use client';

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

interface AutoSaveIndicatorProps {
  status: SaveStatus;
  className?: string;
}

const STATUS_CONFIG: Record<SaveStatus, { text: string; color: string }> = {
  idle: { text: '', color: '' },
  saving: { text: 'Saving...', color: 'text-marshal-yellow' },
  saved: { text: 'Saved', color: 'text-acid-green' },
  error: { text: 'Save failed', color: 'text-safety-red' },
};

export function AutoSaveIndicator({ status, className = '' }: AutoSaveIndicatorProps) {
  if (status === 'idle') return null;

  const { text, color } = STATUS_CONFIG[status];

  return (
    <span className={`inline-flex items-center gap-1.5 text-[10px] font-telemetry uppercase tracking-wider ${color} ${className}`}>
      {status === 'saving' && (
        <svg className="animate-spin h-3 w-3" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" opacity="0.25" />
          <path d="M8 2a6 6 0 014.9 9.4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      )}
      {status === 'saved' && <span aria-hidden="true">&#10003;</span>}
      {status === 'error' && <span aria-hidden="true">&#10007;</span>}
      {text}
    </span>
  );
}
