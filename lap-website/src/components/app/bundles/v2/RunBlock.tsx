'use client';

import type { RunPresentation } from '@/lib/api/bundles/types';
import { SupportTierBadge, RunLifecycleBadge } from './StatusBadge';

interface Props {
  run: RunPresentation | null;
  onAnalyze: () => void;
  onRetry: () => void;
  isAnalyzing: boolean;
  canAnalyze: boolean;
}

export function RunBlock({ run, onAnalyze, onRetry, isAnalyzing, canAnalyze }: Props) {
  // No run yet
  if (!run) {
    return (
      <div className="rounded-xl border border-steel/10 bg-concrete p-5">
        <p className="text-sm font-body text-steel mb-3">No analysis has been run yet.</p>
        {canAnalyze && (
          <button
            onClick={onAnalyze}
            disabled={isAnalyzing}
            className="bg-gold text-white font-telemetry text-sm px-4 py-2 rounded-lg hover:bg-gold/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isAnalyzing ? 'Starting...' : 'Analyze Session'}
          </button>
        )}
      </div>
    );
  }

  // Validating / analyzing
  if (run.lifecycle === 'validated') {
    return (
      <div className="rounded-xl border border-gold/20 bg-concrete p-5">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 rounded-full border-2 border-gold border-t-transparent animate-spin" />
          <span className="text-sm font-telemetry text-chalk">Analyzing session...</span>
        </div>
        <p className="text-xs font-body text-steel mt-2">This usually takes 30-60 seconds.</p>
      </div>
    );
  }

  // Failed
  if (run.lifecycle === 'failed') {
    return (
      <div className="rounded-xl border border-safety-red/30 bg-concrete p-5">
        <h3 className="text-sm font-monument text-safety-red mb-2">Analysis Error</h3>
        {run.errorMessage && (
          <p className="text-sm font-body text-steel mb-1">{run.errorMessage}</p>
        )}
        {run.errorCode && (
          <p className="text-xs font-telemetry text-steel/50 mb-3">Code: {run.errorCode}</p>
        )}
        <button
          onClick={onRetry}
          disabled={isAnalyzing}
          className="border border-safety-red/40 text-safety-red font-telemetry text-sm px-4 py-2 rounded-lg hover:bg-safety-red/10 disabled:opacity-50 transition-colors"
        >
          {isAnalyzing ? 'Retrying...' : 'Retry Analysis'}
        </button>
      </div>
    );
  }

  // Analyzed (succeeded)
  return (
    <div className="rounded-xl border border-steel/10 bg-concrete p-5 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-monument text-chalk">Analysis Result</h3>
        <div className="flex gap-2">
          <SupportTierBadge tier={run.supportTier} />
          <RunLifecycleBadge state={run.lifecycle} />
        </div>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        {run.releaseLabel && (
          <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-telemetry border-${run.releaseColor}/30 text-${run.releaseColor} bg-${run.releaseColor}/10`}>
            {run.releaseLabel}
          </span>
        )}
        {run.confidenceLabel && (
          <span className="text-xs font-telemetry text-steel">{run.confidenceLabel}</span>
        )}
      </div>

      {/* Warnings */}
      {run.warnings.length > 0 && (
        <div className="rounded-lg border border-marshal-yellow/20 bg-marshal-yellow/5 p-3">
          <p className="text-xs font-monument text-marshal-yellow mb-1">Warnings</p>
          <ul className="space-y-0.5">
            {run.warnings.map((w, i) => (
              <li key={i} className="text-xs font-body text-steel">{w.replace(/_/g, ' ')}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Planner modes */}
      <div className="space-y-1">
        {run.plannerModes.map((m) => (
          <div key={m.name} className="flex items-center justify-between text-sm">
            <span className={`font-body ${m.available ? 'text-chalk' : 'text-steel/40'}`}>
              {m.name}
            </span>
            <span className={`font-telemetry text-xs ${m.available ? 'text-acid-green' : 'text-steel/30'}`}>
              {m.available ? 'Available' : 'Locked'}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
