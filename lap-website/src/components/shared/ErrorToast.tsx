'use client';

import { useState, useEffect, useCallback } from 'react';

interface ErrorToastProps {
  /** Error message to display */
  message: string;
  /** Backend request ID for support correlation */
  requestId?: string;
  /** Auto-dismiss after ms (0 = manual dismiss only). Default 8000. */
  duration?: number;
  /** Called when the toast is dismissed */
  onDismiss?: () => void;
}

/**
 * Minimal error toast that surfaces request_id for support.
 * Shows a copy button so users can paste it into support tickets.
 */
export function ErrorToast({
  message,
  requestId,
  duration = 8000,
  onDismiss,
}: ErrorToastProps) {
  const [visible, setVisible] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (duration <= 0) return;
    const timer = setTimeout(() => {
      setVisible(false);
      onDismiss?.();
    }, duration);
    return () => clearTimeout(timer);
  }, [duration, onDismiss]);

  const handleDismiss = useCallback(() => {
    setVisible(false);
    onDismiss?.();
  }, [onDismiss]);

  const handleCopy = useCallback(async () => {
    if (!requestId) return;
    try {
      await navigator.clipboard.writeText(requestId);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Fallback: select-all in a temporary input
      const input = document.createElement('input');
      input.value = requestId;
      document.body.appendChild(input);
      input.select();
      document.execCommand('copy');
      document.body.removeChild(input);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  }, [requestId]);

  if (!visible) return null;

  const displayId = requestId || 'unknown';

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="fixed bottom-4 right-4 z-50 max-w-sm w-full bg-concrete border border-red-500/30 rounded-lg shadow-xl p-4"
    >
      <div className="flex items-start gap-3">
        {/* Error icon */}
        <div className="shrink-0 mt-0.5" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="text-red-400">
            <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5" />
            <path d="M8 4.5v4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            <circle cx="8" cy="11.5" r="0.75" fill="currentColor" />
          </svg>
        </div>

        <div className="flex-1 min-w-0">
          <p className="text-chalk text-sm font-body leading-snug">{message}</p>

          {/* Request ID row */}
          <div className="mt-2 flex items-center gap-2">
            <span className="text-steel text-xs font-telemetry truncate">
              Request ID: {displayId}
            </span>
            <button
              type="button"
              onClick={handleCopy}
              className="shrink-0 text-xs text-steel hover:text-chalk transition-colors"
              aria-label={`Copy request ID ${displayId}`}
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>

        {/* Dismiss button */}
        <button
          type="button"
          onClick={handleDismiss}
          className="shrink-0 text-steel hover:text-chalk transition-colors"
          aria-label="Dismiss error"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </div>
    </div>
  );
}
