'use client';

import { useEffect, useRef, useCallback } from 'react';

type ToastSeverity = 'info' | 'success' | 'warning' | 'error';

interface ToastProps {
  message: string;
  severity?: ToastSeverity;
  duration?: number;
  action?: { label: string; onClick: () => void };
  onDismiss: () => void;
}

const SEVERITY_STYLES: Record<ToastSeverity, string> = {
  info: 'border-l-racing-purple',
  success: 'border-l-acid-green',
  warning: 'border-l-marshal-yellow',
  error: 'border-l-safety-red',
};

const DURATION_DEFAULTS: Record<ToastSeverity, number> = {
  info: 5000,
  success: 4000,
  warning: 6000,
  error: 8000,
};

export function Toast({ message, severity = 'info', duration, action, onDismiss }: ToastProps) {
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const actualDuration = duration ?? DURATION_DEFAULTS[severity];

  const dismiss = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    onDismiss();
  }, [onDismiss]);

  useEffect(() => {
    timerRef.current = setTimeout(dismiss, actualDuration);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [dismiss, actualDuration]);

  return (
    <div
      role="alert"
      aria-live="assertive"
      className={`
        fixed bottom-6 right-6 z-[100]
        max-w-sm w-full
        bg-concrete border border-steel/20 border-l-4 ${SEVERITY_STYLES[severity]}
        rounded-lg shadow-e3 p-4
        flex items-start gap-3
        animate-in slide-in-from-bottom-2
      `}
    >
      <p className="text-chalk text-sm flex-1">{message}</p>
      <div className="flex items-center gap-2 shrink-0">
        {action && (
          <button
            type="button"
            onClick={action.onClick}
            className="text-xs font-telemetry tracking-widest uppercase text-pit-orange hover:text-chalk transition-colors min-h-[44px] px-2"
          >
            {action.label}
          </button>
        )}
        <button
          type="button"
          onClick={dismiss}
          className="text-steel hover:text-chalk transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
          aria-label="Dismiss notification"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </div>
    </div>
  );
}
