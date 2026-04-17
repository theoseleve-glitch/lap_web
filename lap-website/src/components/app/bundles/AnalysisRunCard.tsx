'use client';

import type { RunDisplayState } from '@/types/bundles';
import { CONFIDENCE_LABELS, RELEASE_LABELS } from '@/lib/bundle-vocabulary';
import { SupportLevelBadge } from './SupportLevelBadge';

interface Props {
  displayState: RunDisplayState;
  onAnalyze: () => void;
  onRetry: () => void;
  isAnalyzing: boolean;
}

export function AnalysisRunCard({ displayState, onAnalyze, onRetry, isAnalyzing }: Props) {
  if (displayState.phase === 'no-run') {
    return (
      <div className="rounded-xl border border-steel/10 bg-concrete p-5">
        <p className="text-sm font-body text-steel mb-3">No analysis has been run yet.</p>
        <button
          onClick={onAnalyze}
          disabled={isAnalyzing}
          className="bg-gold text-white font-telemetry text-sm px-4 py-2 rounded-lg hover:bg-gold/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isAnalyzing ? 'Starting...' : 'Analyze Session'}
        </button>
      </div>
    );
  }

  if (displayState.phase === 'queued' || displayState.phase === 'running') {
    return (
      <div className="rounded-xl border border-gold/20 bg-concrete p-5">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 rounded-full border-2 border-gold border-t-transparent animate-spin" />
          <span className="text-sm font-telemetry text-chalk">
            {displayState.phase === 'queued' ? 'Queued...' : 'Analyzing session...'}
          </span>
        </div>
        <p className="text-xs font-body text-steel mt-2">
          This usually takes 30-60 seconds.
        </p>
      </div>
    );
  }

  if (displayState.phase === 'failed') {
    return (
      <div className="rounded-xl border border-safety-red/30 bg-concrete p-5">
        <h3 className="text-sm font-monument text-safety-red mb-2">Analysis Error</h3>
        <p className="text-sm font-body text-steel mb-3">{displayState.errorMessage}</p>
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

  // succeeded
  const { tier, run } = displayState;
  const release = run.release_decision ? RELEASE_LABELS[run.release_decision] : null;
  const confidence = run.confidence_level ? CONFIDENCE_LABELS[run.confidence_level] : null;

  return (
    <div className="rounded-xl border border-steel/10 bg-concrete p-5 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-monument text-chalk">Analysis Result</h3>
        <SupportLevelBadge tier={run.support_tier} size="md" />
      </div>
      <div className="flex items-center gap-3 flex-wrap">
        {release && (
          <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-telemetry border-${release.color}/30 text-${release.color} bg-${release.color}/10`}>
            {release.label}
          </span>
        )}
        {confidence && (
          <span className="text-xs font-telemetry text-steel">{confidence}</span>
        )}
      </div>
      <p className="text-xs font-body text-steel">{tier.description}</p>
    </div>
  );
}
