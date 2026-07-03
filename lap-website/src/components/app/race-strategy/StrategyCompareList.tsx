'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api-client';

interface StrategyMetrics {
  pits_in_rain: number;
  pits_in_dry: number;
  rain_drive_s: number;
  dry_drive_s: number;
  driver_transitions: number;
  min_stint_s: number;
  max_stint_s: number;
  flexibility_score: number;
  risk_score: number;
  total_pit_s: number;
}

interface StintPlan {
  stint_order: number;
  driver_id: number;
  driver_name: string;
  start_s: number;
  duration_s: number;
}

interface RankedStrategy {
  name: string;
  description: string;
  approach: string;
  score: number;
  stints: StintPlan[];
  metrics: StrategyMetrics;
}

interface StrategyCompareListProps {
  raceId: number;
}

/** Surfaces optimizer.multi_strategy.generate_strategies() (up to 3 ranked
 * plans) at the pre-race planning stage — draft/ready races, not just the
 * live-race rain-scenario modal that already calls this same endpoint. */
export function StrategyCompareList({ raceId }: StrategyCompareListProps) {
  const qc = useQueryClient();
  const [strategies, setStrategies] = useState<RankedStrategy[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const generateMut = useMutation({
    mutationFn: () => api.post<{ strategies: RankedStrategy[] }>(`/race-strategy/${raceId}/strategies`, {}),
    onSuccess: (data) => {
      setError(null);
      const list = data.strategies ?? [];
      if (list.length === 0) {
        setError('No viable strategies found for the current race configuration.');
        setStrategies(null);
      } else {
        setStrategies(list);
      }
    },
    onError: (err: Error) => {
      setError(err.message || 'Strategy generation failed');
      setStrategies(null);
    },
  });

  const applyMut = useMutation({
    mutationFn: (stints: StintPlan[]) =>
      api.post(`/race-strategy/${raceId}/apply-strategy`, { stints }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['race-strategy', String(raceId)] });
      setStrategies(null);
    },
  });

  if (!strategies) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/20 p-4">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Compare Strategies</h3>
            <p className="text-steel font-body text-xs mt-1">
              Generate up to 3 ranked stint plans before going live.
            </p>
          </div>
          <button
            type="button"
            onClick={() => generateMut.mutate()}
            disabled={generateMut.isPending}
            className="px-4 py-2 bg-gold text-white font-telemetry text-xs uppercase tracking-wider rounded hover:bg-gold/80 transition-colors disabled:opacity-50 shrink-0"
          >
            {generateMut.isPending ? 'Comparing...' : 'Compare Strategies'}
          </button>
        </div>
        {error && (
          <p className="text-safety-red font-body text-xs mt-3">{error}</p>
        )}
      </div>
    );
  }

  return (
    <div className="bg-concrete rounded-lg border border-steel/20 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">
          {strategies.length} Strategies Generated — Ranked by Score
        </h3>
        <button type="button" onClick={() => setStrategies(null)} className="text-steel text-xs hover:text-chalk transition-colors">
          Clear
        </button>
      </div>
      {strategies.map((s, idx) => {
        const risk = s.metrics.risk_score;
        const riskLevel = risk < 0.3 ? 'low' : risk < 0.6 ? 'medium' : 'high';
        const borderColor =
          riskLevel === 'low' ? 'border-acid-green/30 bg-acid-green/5'
          : riskLevel === 'medium' ? 'border-marshal-yellow/30 bg-marshal-yellow/5'
          : 'border-safety-red/30 bg-safety-red/5';
        const badgeColor =
          riskLevel === 'low' ? 'text-acid-green bg-acid-green/10 border-acid-green/30'
          : riskLevel === 'medium' ? 'text-marshal-yellow bg-marshal-yellow/10 border-marshal-yellow/30'
          : 'text-safety-red bg-safety-red/10 border-safety-red/30';

        return (
          <div key={`${s.approach}-${idx}`} className={`border rounded-lg p-4 ${borderColor}`}>
            <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <span className="text-chalk font-telemetry text-sm">{s.name}</span>
                <span className="text-steel font-telemetry text-xs">Score: {s.score}</span>
              </div>
              <span className={`inline-flex px-2 py-0.5 text-[10px] font-telemetry tracking-[0.12em] uppercase border ${badgeColor}`}>
                {riskLevel} risk ({Math.round(risk * 100)}%)
              </span>
            </div>
            <p className="text-steel font-body text-xs mb-3">{s.description}</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3 text-xs font-telemetry">
              <div><span className="text-steel/60 block">Stints</span><span className="text-chalk">{s.stints.length}</span></div>
              <div><span className="text-steel/60 block">Driver Changes</span><span className="text-chalk">{s.metrics.driver_transitions}</span></div>
              <div><span className="text-steel/60 block">Total Pit Time</span><span className="text-chalk">{Math.round(s.metrics.total_pit_s)}s</span></div>
              <div><span className="text-steel/60 block">Flexibility</span><span className="text-chalk">{Math.round(s.metrics.flexibility_score * 100)}%</span></div>
            </div>
            <button
              type="button"
              onClick={() => applyMut.mutate(s.stints)}
              disabled={applyMut.isPending}
              className="px-3 py-1.5 bg-gold text-white font-telemetry text-xs uppercase tracking-wider rounded hover:bg-gold/80 transition-colors disabled:opacity-50"
            >
              {applyMut.isPending ? 'Applying...' : 'Apply This Strategy'}
            </button>
          </div>
        );
      })}
      {applyMut.error && (
        <p className="text-safety-red font-body text-xs">
          {(applyMut.error as Error).message || 'Failed to apply strategy'}
        </p>
      )}
    </div>
  );
}
