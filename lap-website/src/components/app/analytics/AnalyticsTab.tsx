'use client';

import { BACKEND_URL } from '@/lib/api-client';
import { GpsTrace, SpeedTraceZoom, GGExplorer } from '@/components/app/charts';
import { SectorPanel } from '@/components/shared/charts';
import { DeltaTimeChart } from '@/components/shared/charts/DeltaTimeChart';
import { PedalTraceChart } from '@/components/shared/charts/PedalTraceChart';
import { RPMGearChart } from '@/components/shared/charts/RPMGearChart';
import { LiveFrictionCircle } from '@/components/shared/charts/LiveFrictionCircle';
import { TireHeatmapChart } from '@/components/shared/charts/TireHeatmapChart';
import { WheelSlipChart } from '@/components/shared/charts/WheelSlipChart';
import { BrakeAnalysisChart } from '@/components/shared/charts/BrakeAnalysisChart';
import { FuelStrategyChart } from '@/components/shared/charts/FuelStrategyChart';
import { useSessionChannels } from '@/hooks/useSessionChannels';
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
  const { channels } = useSessionChannels(sessionId);

  const hasControls = channels.throttle || channels.brake;
  const hasRpmGear = channels.rpm || channels.gear;
  const hasTireTemps = channels.tire_temp;
  const hasWheelSlip = channels.wheel_slip;
  const hasBrakeTemps = channels.brake_temp;
  const hasFuel = channels.fuel;

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

      {/* ── Row 3: Pedal Traces + RPM/Gear (if controls data available) ── */}
      {hasControls && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-concrete rounded-xl border border-steel/10 p-4">
            <h3 className="text-sm font-monument text-chalk mb-3">Pedal Traces</h3>
            <PedalTraceChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} className="w-full" />
          </div>
          {hasRpmGear ? (
            <div className="bg-concrete rounded-xl border border-steel/10 p-4">
              <h3 className="text-sm font-monument text-chalk mb-3">RPM &amp; Gear</h3>
              <RPMGearChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} className="w-full" />
            </div>
          ) : (
            <div className="bg-concrete rounded-xl border border-steel/10 p-4">
              <h3 className="text-sm font-monument text-chalk mb-3">Live Friction Circle</h3>
              <LiveFrictionCircle sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} className="w-full" />
            </div>
          )}
        </div>
      )}
      {!hasControls && (
        <div className="text-steel/60 text-sm text-center p-6 border border-dashed border-steel/20 rounded-lg">
          <p className="font-telemetry text-chalk mb-1">Pedal Traces &amp; RPM</p>
          <p>Requires throttle, brake, RPM data — available in iRacing, ACC, and MoTeC formats</p>
        </div>
      )}

      {/* ── Row 3b: Live Friction Circle (if both controls + RPM available) ── */}
      {hasControls && hasRpmGear && (
        <div className="bg-concrete rounded-xl border border-steel/10 p-4">
          <h3 className="text-sm font-monument text-chalk mb-3">Live Friction Circle</h3>
          <LiveFrictionCircle sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} className="w-full" />
        </div>
      )}

      {/* ── Row 3c: Tire Heatmap + Wheel Slip (if tire data available) ── */}
      {(hasTireTemps || hasWheelSlip) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {hasTireTemps && (
            <div className="bg-concrete rounded-xl border border-steel/10 p-4">
              <h3 className="text-sm font-monument text-chalk mb-3">Tire Temperatures</h3>
              <TireHeatmapChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} className="w-full" />
            </div>
          )}
          {hasWheelSlip && (
            <div className="bg-concrete rounded-xl border border-steel/10 p-4">
              <h3 className="text-sm font-monument text-chalk mb-3">Wheel Slip</h3>
              <WheelSlipChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} className="w-full" />
            </div>
          )}
        </div>
      )}

      {/* ── Row 3d: Brake Analysis + Fuel Strategy ── */}
      {(hasBrakeTemps || hasFuel) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {hasBrakeTemps && (
            <div className="bg-concrete rounded-xl border border-steel/10 p-4">
              <h3 className="text-sm font-monument text-chalk mb-3">Brake Analysis</h3>
              <BrakeAnalysisChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} className="w-full" />
            </div>
          )}
          {hasFuel && (
            <div className="bg-concrete rounded-xl border border-steel/10 p-4">
              <h3 className="text-sm font-monument text-chalk mb-3">Fuel Strategy</h3>
              <FuelStrategyChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} className="w-full" />
            </div>
          )}
        </div>
      )}

      {/* ── Row 4: Sector Analysis ── */}
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
