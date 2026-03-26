'use client';

/**
 * ImportErrorPanel — renders structured import failures with recovery guidance.
 *
 * Consumes the import_error object from the backend API/SSE and shows:
 * - Error title and explanation
 * - Detected format/source if available
 * - Failed stage
 * - Next steps (actionable recovery)
 * - Support reference
 * - Action buttons (retry, help, support)
 */

import Link from 'next/link';

/* ── Types ──────────────────────────────────── */

export interface ImportError {
  code: string;
  title: string;
  message: string;
  next_steps: string[];
  stage: string;
  severity: string;
  recoverable_by_user: boolean;
  retryable: boolean;
  support_ref: string;
  detected_format?: string;
  extra_context?: Record<string, unknown>;
}

interface ImportErrorPanelProps {
  error: ImportError;
  /** Callback when user clicks "Try another file" */
  onRetry?: () => void;
  /** Callback when user clicks "Try again" (re-upload same file) */
  onReupload?: () => void;
  /** Optional: the filename that failed */
  fileName?: string;
}

/* ── Stage labels ───────────────────────────── */

const STAGE_LABELS: Record<string, string> = {
  preflight: 'File Validation',
  upload: 'Upload',
  dispatch: 'Processing Queue',
  analysis: 'Analysis Pipeline',
  unknown: 'Processing',
};

/* ── Severity icons ─────────────────────────── */

function BlockingIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="text-safety-red flex-shrink-0">
      <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="1.5" />
      <path d="M10 6v5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="10" cy="14" r="1" fill="currentColor" />
    </svg>
  );
}

function WarningIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="text-marshal-yellow flex-shrink-0">
      <path d="M10 3L18 17H2L10 3z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M10 8v4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="10" cy="14.5" r="0.75" fill="currentColor" />
    </svg>
  );
}

/* ── Format help links ──────────────────────── */

const FORMAT_HELP_LINKS: Record<string, { label: string; href: string }> = {
  iRacing: { label: 'iRacing export guide', href: '/app/help/formats/iracing' },
  RaceChrono: { label: 'RaceChrono export guide', href: '/app/help/formats/racechrono' },
  RaceBox: { label: 'RaceBox export guide', href: '/app/help/formats/racebox' },
  MoTeC: { label: 'MoTeC export guide', href: '/app/help/formats/motec' },
  VBOX: { label: 'VBOX export guide', href: '/app/help/formats/vbox' },
  AiM: { label: 'AiM export guide', href: '/app/help/formats/aim' },
};

/* ── Component ──────────────────────────────── */

export function ImportErrorPanel({ error, onRetry, onReupload, fileName }: ImportErrorPanelProps) {
  const isBlocking = error.severity === 'blocking';
  const isUserFixable = error.recoverable_by_user;
  const stageLabel = STAGE_LABELS[error.stage] || error.stage;
  const formatHelp = error.detected_format ? FORMAT_HELP_LINKS[error.detected_format] : null;

  return (
    <div
      className={`rounded-lg border p-5 ${
        isBlocking
          ? 'bg-safety-red/5 border-safety-red/20'
          : 'bg-marshal-yellow/5 border-marshal-yellow/20'
      }`}
      role="alert"
    >
      {/* ── Header ──────────────────────────────── */}
      <div className="flex items-start gap-3 mb-3">
        {isBlocking ? <BlockingIcon /> : <WarningIcon />}
        <div className="min-w-0">
          <h3 className={`font-monument text-sm ${isBlocking ? 'text-safety-red' : 'text-marshal-yellow'}`}>
            {error.title}
          </h3>
          {error.detected_format && (
            <span className="inline-block mt-1 px-2 py-0.5 text-[10px] font-telemetry uppercase tracking-wider rounded bg-steel/10 text-steel border border-steel/20">
              Detected: {error.detected_format}
            </span>
          )}
        </div>
      </div>

      {/* ── Message ─────────────────────────────── */}
      <p className="text-sm font-body text-chalk/90 mb-4 ml-8">
        {error.message}
      </p>

      {/* ── Failed stage ────────────────────────── */}
      <div className="ml-8 mb-4 flex items-center gap-2 text-xs font-telemetry text-steel">
        <span className="uppercase tracking-wider">Failed at:</span>
        <span className="text-chalk/70">{stageLabel}</span>
      </div>

      {/* ── Next steps ──────────────────────────── */}
      {error.next_steps.length > 0 && (
        <div className="ml-8 mb-4">
          <p className="text-xs font-telemetry text-steel uppercase tracking-wider mb-2">
            {isUserFixable ? 'How to fix this' : 'What to do'}
          </p>
          <ul className="space-y-1.5">
            {error.next_steps.map((step, i) => (
              <li key={i} className="flex items-start gap-2 text-sm font-body text-chalk/80">
                <span className="text-steel/50 font-telemetry text-xs mt-0.5 flex-shrink-0">{i + 1}.</span>
                {step}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ── Format-specific help link ───────────── */}
      {formatHelp && (
        <div className="ml-8 mb-4">
          <Link
            href={formatHelp.href}
            className="inline-flex items-center gap-1.5 text-xs font-telemetry text-gold hover:text-gold/80 transition-colors"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="flex-shrink-0">
              <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5" />
              <path d="M6 6.5a2 2 0 013.5 1.5c0 1-1.5 1-1.5 2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              <circle cx="8" cy="12" r="0.75" fill="currentColor" />
            </svg>
            {formatHelp.label}
          </Link>
        </div>
      )}

      {/* ── Support reference ───────────────────── */}
      <div className="ml-8 mb-4 flex items-center gap-2">
        <span className="text-[10px] font-telemetry text-steel/40 uppercase tracking-wider">
          Ref: {error.support_ref}
        </span>
      </div>

      {/* ── Actions ─────────────────────────────── */}
      <div className="ml-8 flex flex-wrap items-center gap-3">
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="px-4 py-2 bg-gold text-white font-telemetry text-xs rounded-lg hover:bg-gold/90 transition-colors"
          >
            Try another file
          </button>
        )}

        {error.retryable && onReupload && (
          <button
            type="button"
            onClick={onReupload}
            className="px-4 py-2 border border-steel/30 text-chalk font-telemetry text-xs rounded-lg hover:bg-concrete transition-colors"
          >
            Try again
          </button>
        )}

        <Link
          href="/app/help/formats"
          className="px-4 py-2 text-steel hover:text-chalk font-telemetry text-xs transition-colors"
        >
          Supported formats
        </Link>

        {!isUserFixable && (
          <a
            href={`mailto:support@lap-coach.racing?subject=Import error ${error.support_ref}&body=Error code: ${error.code}%0ARef: ${error.support_ref}%0AFile: ${fileName || 'unknown'}`}
            className="px-4 py-2 text-steel hover:text-chalk font-telemetry text-xs transition-colors"
          >
            Contact support
          </a>
        )}
      </div>
    </div>
  );
}
