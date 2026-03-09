/**
 * ScoringWeightsEditor.tsx — Lets users adjust scoring dimension weights.
 *
 * Shows 4 sliders (Pace, Consistency, Execution, Robustness) and a
 * weighted total preview. Persists to localStorage via Zustand store.
 */
'use client';

import { useScoringWeights, computeWeightedTotal, type ScoringWeights } from '@/lib/scoring-weights';

const DIMENSIONS: { key: keyof ScoringWeights; label: string; color: string }[] = [
  { key: 'pace', label: 'Pace', color: 'accent-acid-green' },
  { key: 'consistency', label: 'Consistency', color: 'accent-marshal-yellow' },
  { key: 'execution', label: 'Execution', color: 'accent-blue-400' },
  { key: 'robustness', label: 'Robustness', color: 'accent-purple-400' },
];

interface Props {
  scores?: {
    pace_score: number | null;
    pace_max: number | null;
    consistency_score: number | null;
    consistency_max: number | null;
    execution_score: number | null;
    execution_max: number | null;
    robustness_score: number | null;
    robustness_max: number | null;
  } | null;
}

export function ScoringWeightsEditor({ scores }: Props) {
  const { pace, consistency, execution, robustness, setWeight, reset } = useScoringWeights();
  const weights: ScoringWeights = { pace, consistency, execution, robustness };
  const sum = pace + consistency + execution + robustness;

  const weightedTotal = scores ? computeWeightedTotal(scores, weights) : null;
  const isDefault = pace === 25 && consistency === 25 && execution === 25 && robustness === 25;

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-xs font-monument text-chalk">Scoring Weights</h4>
        {!isDefault && (
          <button
            type="button"
            onClick={reset}
            className="text-[10px] font-telemetry text-steel hover:text-chalk transition-colors"
          >
            Reset
          </button>
        )}
      </div>

      <div className="space-y-3">
        {DIMENSIONS.map(({ key, label }) => (
          <div key={key}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-body text-steel">{label}</span>
              <span className="text-xs font-telemetry text-chalk">{weights[key]}</span>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={weights[key]}
              onChange={(e) => setWeight(key, parseInt(e.target.value, 10))}
              className="w-full h-1.5 bg-steel/20 rounded-lg appearance-none cursor-pointer
                [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3
                [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-chalk"
              aria-label={`${label} weight`}
            />
          </div>
        ))}
      </div>

      <div className="mt-3 pt-3 border-t border-steel/10 flex items-center justify-between">
        <span className="text-[10px] font-telemetry text-steel uppercase">
          Total weight: {sum}
        </span>
        {weightedTotal != null && (
          <span className="text-sm font-monument text-chalk">
            Weighted: {weightedTotal.toFixed(1)}/100
          </span>
        )}
      </div>
    </div>
  );
}
