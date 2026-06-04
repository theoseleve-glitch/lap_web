'use client';

import { lazy, Suspense } from 'react';

const TrackMap = lazy(() => import('@/components/shared/charts').then(m => ({ default: m.TrackMap })));

/**
 * Handling Balance card for the session overview tab.
 * Shows: tendency, track map with numbered corners, driving tips (default), setup advice (on request).
 */

interface HandlingBalanceSummary {
  n_corners: number;
  n_events: number;
  n_understeer: number;
  n_oversteer: number;
  n_conflicts: number;
  avg_confidence: number;
  max_confidence: number;
  overall_direction: number;
  tendency: 'understeer' | 'oversteer' | 'balanced';
}

interface SetupRecommendation {
  priority: number;
  change: string;
  reason: string;
  affected_corners: number[];
}

interface FocusCorner {
  corner_number: number;
  score: number;
  n_events: number;
  avg_confidence: number;
  peak_g: number;
  tendency: string;
  dominant_zone: string;
}

interface BestLapMistake {
  corner_number: number;
  zone: string;
  type: string;
  direction: number;
  confidence: number;
  duration_s: number;
  impact: number;
  top_detector: string | null;
  conflict: boolean;
}

interface DrivingTip {
  corner_number: number;
  tip: string;
  type: string;
  zone: string;
}

interface CornerPosition {
  corner_number: number;
  lat: number;
  lon: number;
}

interface HandlingBalanceCardProps {
  sessionId?: string;
  bestLap?: number | null;
  summary: HandlingBalanceSummary | null;
  focusCorners?: FocusCorner[] | null;
  bestLapMistakes?: BestLapMistake[] | null;
  drivingTips?: DrivingTip[] | null;
  cornerPositions?: CornerPosition[] | null;
  recommendations?: {
    primary_issue: string;
    summary: string;
    recommendations: SetupRecommendation[];
  } | null;
}

const TENDENCY_STYLES = {
  understeer: { bg: 'bg-safety-red/10', border: 'border-safety-red/30', text: 'text-safety-red', label: 'UNDERSTEER' },
  oversteer: { bg: 'bg-racing-purple/10', border: 'border-racing-purple/30', text: 'text-racing-purple', label: 'OVERSTEER' },
  balanced: { bg: 'bg-acid-green/10', border: 'border-acid-green/30', text: 'text-acid-green', label: 'BALANCED' },
};

export function HandlingBalanceCard({
  sessionId, bestLap, summary, focusCorners, bestLapMistakes, drivingTips, cornerPositions,
}: HandlingBalanceCardProps) {
  if (!summary || summary.n_corners === 0) return null;

  const style = TENDENCY_STYLES[summary.tendency] || TENDENCY_STYLES.balanced;
  const visibleMistakes = bestLapMistakes?.filter(m => m.confidence >= 0.60) ?? [];

  return (
    <div className="bg-concrete rounded-lg border border-steel/20 p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-monument text-sm text-chalk">Handling Balance</h3>
        <span className={`text-[10px] font-telemetry font-semibold px-2.5 py-1 rounded border ${style.bg} ${style.border} ${style.text}`}>
          {style.label}
        </span>
      </div>

      {/* Stats + mini track map side by side */}
      <div className="flex gap-4 mb-4">
        {/* Stats */}
        <div className="flex-1">
          <div className="grid grid-cols-3 gap-3 mb-3">
            <div>
              <p className="text-[10px] font-telemetry text-steel">Corners</p>
              <p className="text-lg font-telemetry text-chalk">{summary.n_corners}</p>
            </div>
            <div>
              <p className="text-[10px] font-telemetry text-safety-red">Understeer</p>
              <p className="text-lg font-telemetry text-safety-red">{summary.n_understeer}</p>
            </div>
            <div>
              <p className="text-[10px] font-telemetry text-racing-purple">Oversteer</p>
              <p className="text-lg font-telemetry text-racing-purple">{summary.n_oversteer}</p>
            </div>
          </div>
          {/* Direction bar */}
          <div>
            <div className="flex justify-between text-[9px] font-telemetry text-steel mb-1">
              <span>OS</span>
              <span>Balanced</span>
              <span>US</span>
            </div>
            <div className="h-2 bg-steel/10 rounded-full relative">
              <div className="absolute w-px h-full bg-steel/40 left-1/2" />
              <div
                className={`absolute h-full rounded-full ${summary.overall_direction > 0 ? 'bg-safety-red' : 'bg-racing-purple'}`}
                style={{
                  width: `${Math.min(Math.abs(summary.overall_direction) * 50, 50)}%`,
                  left: summary.overall_direction > 0
                    ? '50%'
                    : `${50 - Math.abs(summary.overall_direction) * 50}%`,
                }}
              />
            </div>
          </div>
        </div>

        {/* Track map with numbered corners — uses the same renderer as analytics */}
        {sessionId && cornerPositions && cornerPositions.length > 1 && (
          <div className="shrink-0 w-[240px] h-[200px] rounded overflow-hidden">
            <Suspense fallback={<div className="w-full h-full bg-asphalt/50 rounded" />}>
              <TrackMap
                sessionId={sessionId}
                lap={bestLap ?? undefined}
                corners={cornerPositions.map(cp => ({
                  corner_id: cp.corner_number,
                  lat: cp.lat,
                  lon: cp.lon,
                  label: `T${cp.corner_number}`,
                }))}
                className="w-full h-full"
              />
            </Suspense>
          </div>
        )}
      </div>

      {/* Driving tips — primary actionable */}
      {drivingTips && drivingTips.length > 0 && (
        <div className="border-t border-steel/15 pt-3 mt-1">
          <p className="text-[10px] font-telemetry text-gold mb-2 uppercase tracking-wider">
            What to change
          </p>
          <div className="space-y-2.5">
            {drivingTips.map((dt, i) => (
              <div key={i} className="flex items-start gap-2.5">
                <span className={`text-[10px] font-telemetry font-bold shrink-0 w-6 h-6 rounded-full flex items-center justify-center ${
                  dt.type === 'understeer' ? 'bg-safety-red/20 text-safety-red' : 'bg-racing-purple/20 text-racing-purple'
                }`}>
                  {dt.corner_number}
                </span>
                <p className="text-[12px] font-body text-chalk/90 leading-relaxed">{dt.tip}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Best lap mistakes — compact list */}
      {visibleMistakes.length > 0 && (
        <div className="border-t border-steel/15 pt-3 mt-3">
          <p className="text-[10px] font-telemetry text-steel mb-1.5 uppercase tracking-wider">
            Best lap issues
          </p>
          <div className="flex flex-wrap gap-1.5">
            {visibleMistakes.map((m, i) => (
              <span key={i} className={`text-[10px] font-telemetry px-2 py-0.5 rounded ${
                m.type === 'understeer' ? 'bg-safety-red/10 text-safety-red' : 'bg-racing-purple/10 text-racing-purple'
              }`}>
                T{m.corner_number} {m.type === 'understeer' ? 'US' : 'OS'} {m.zone}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


