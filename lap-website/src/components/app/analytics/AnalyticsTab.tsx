'use client';

import { BACKEND_URL } from '@/lib/api-client';
import { GpsTrace, SpeedTraceZoom, GGExplorer } from '@/components/app/charts';
import { SectorPanel } from '@/components/shared/charts';
import { DeltaTimeChart } from '@/components/shared/charts/DeltaTimeChart';
import { LapSpeedOverlay } from './LapSpeedOverlay';
import { LapDistribution } from './LapDistribution';
import { LapProgressTracker } from './LapProgressTracker';
import { SessionComparison } from './SessionComparison';
import { DevelopmentDrills } from './DevelopmentDrills';

interface CornerData {
  corner_id: number;
  available: boolean;
  direction?: 'L' | 'R';
  coaching_hint?: string | null;
  time_loss_total_s?: number | null;
}

interface ScoreData {
  pace_score: number | null;
  pace_max: number | null;
  consistency_score: number | null;
  consistency_max: number | null;
  execution_score: number | null;
  execution_max: number | null;
  robustness_score: number | null;
  robustness_max: number | null;
  adaptation_score: number | null;
  strengths: string[];
  weaknesses: string[];
}

interface AnalyticsTabProps {
  sessionId: string;
  gpsLaps: number[];
  bestLap: number | null;
  scores: ScoreData | null;
  corners: CornerData[];
  trackName: string | null;
}

export function AnalyticsTab({
  sessionId,
  gpsLaps,
  bestLap,
  scores,
  corners,
  trackName,
}: AnalyticsTabProps) {
  const apiBase = BACKEND_URL;

  return (
    <div className="space-y-6">
      {/* ── Row 1: Track Map + Speed Trace + GG Diagram ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 lg:row-span-2">
          <div className="bg-concrete rounded-xl border border-steel/10 p-4">
            <h3 className="text-sm font-monument text-chalk mb-3">GPS Track Map</h3>
            <GpsTrace
              sessionId={sessionId}
              apiBase={apiBase}
              gpsLaps={gpsLaps}
              bestLap={bestLap}
              className="w-full"
            />
          </div>
        </div>
        <div className="lg:col-span-2">
          <div className="bg-concrete rounded-xl border border-steel/10 p-4">
            <h3 className="text-sm font-monument text-chalk mb-3">Speed Trace</h3>
            <SpeedTraceZoom
              sessionId={sessionId}
              apiBase={apiBase}
              gpsLaps={gpsLaps}
              bestLap={bestLap}
              className="w-full"
            />
          </div>
        </div>
        <div className="lg:col-span-2">
          <div className="bg-concrete rounded-xl border border-steel/10 p-4">
            <h3 className="text-sm font-monument text-chalk mb-3">G-G Diagram</h3>
            <GGExplorer
              sessionId={sessionId}
              apiBase={apiBase}
              gpsLaps={gpsLaps}
              bestLap={bestLap}
              className="w-full"
            />
          </div>
        </div>
      </div>

      {/* ── Row 2: Delta Time Chart ── */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-4">
        <h3 className="text-sm font-monument text-chalk mb-3">Time Delta</h3>
        <DeltaTimeChart
          sessionId={sessionId}
          gpsLaps={gpsLaps}
          bestLap={bestLap}
          className="w-full"
        />
      </div>

      {/* ── Row 3: Sector Analysis ── */}
      <SectorPanel sessionId={sessionId} className="bg-concrete rounded-xl border border-steel/10" />

      {/* ── Row 4: Lap Speed Overlay ── */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-4">
        <h3 className="text-sm font-monument text-chalk mb-3">Lap Speed Overlay</h3>
        <LapSpeedOverlay
          sessionId={sessionId}
          apiBase={apiBase}
          gpsLaps={gpsLaps}
          bestLap={bestLap}
        />
      </div>

      {/* ── Row 5: Distribution + Progress ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-concrete rounded-xl border border-steel/10 p-4">
          <h3 className="text-sm font-monument text-chalk mb-3">Lap Distribution</h3>
          <LapDistribution sessionId={sessionId} apiBase={apiBase} />
        </div>
        <div className="bg-concrete rounded-xl border border-steel/10 p-4">
          <h3 className="text-sm font-monument text-chalk mb-3">Lap Progress</h3>
          <LapProgressTracker sessionId={sessionId} apiBase={apiBase} />
        </div>
      </div>

      {/* ── Row 6: Session Comparison ── */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-4">
        <h3 className="text-sm font-monument text-chalk mb-3">Session Comparison</h3>
        <SessionComparison sessionId={sessionId} trackName={trackName} />
      </div>

      {/* ── Row 7: Development Drills ── */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-4">
        <h3 className="text-sm font-monument text-chalk mb-3">Development Drills</h3>
        <DevelopmentDrills scores={scores} corners={corners} />
      </div>
    </div>
  );
}
