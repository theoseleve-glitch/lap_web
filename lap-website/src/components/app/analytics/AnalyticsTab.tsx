'use client';

import { useState } from 'react';
import { BACKEND_URL } from '@/lib/api-client';
import { GpsTrace, SpeedTraceZoom, GGExplorer } from '@/components/app/charts';
import { SectorPanel, SpeedTraceMiniMap } from '@/components/shared/charts';
import { DeltaTimeChart } from '@/components/shared/charts/DeltaTimeChart';
import { PedalTraceChart } from '@/components/shared/charts/PedalTraceChart';
import { RPMGearChart } from '@/components/shared/charts/RPMGearChart';
import { LiveFrictionCircle } from '@/components/shared/charts/LiveFrictionCircle';
import { TireHeatmapChart } from '@/components/shared/charts/TireHeatmapChart';
import { WheelSlipChart } from '@/components/shared/charts/WheelSlipChart';
import { BrakeAnalysisChart } from '@/components/shared/charts/BrakeAnalysisChart';
import { FuelStrategyChart } from '@/components/shared/charts/FuelStrategyChart';
import { TheoreticalDeltaChart } from '@/components/shared/charts/TheoreticalDeltaChart';
import { CornerCoachingTable } from '@/components/shared/charts/CornerCoachingTable';
import { CornerCoachingV4 } from '@/components/shared/charts/CornerCoachingV4';
import { SurfaceProfileChart } from '@/components/shared/charts/SurfaceProfileChart';
import { useSessionChannels } from '@/hooks/useSessionChannels';
import { LapSpeedOverlay } from './LapSpeedOverlay';
import { LapDistribution } from './LapDistribution';
import { LapProgressTracker } from './LapProgressTracker';
import { SessionComparison } from './SessionComparison';
import { DevelopmentDrills } from './DevelopmentDrills';
import { ChartThemePicker } from '@/components/app/ChartThemePicker';
import { ChartAnnotations } from '@/components/app/ChartAnnotations';
import { ChartTooltip } from '@/components/ui/ChartTooltip';
import { ReferenceOverlayProvider, ReferenceFAB } from '@/components/app/reference';

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
  const [trackColorMode, setTrackColorMode] = useState<"speed" | "grip" | "ribbon">("speed");
  const { channels } = useSessionChannels(sessionId);

  const hasControls = channels.throttle || channels.brake;
  const hasRpmGear = channels.rpm || channels.gear;
  const hasTireTemps = channels.tire_temp;
  const hasWheelSlip = channels.wheel_slip;
  const hasBrakeTemps = channels.brake_temp;
  const hasFuel = channels.fuel;

  return (
    <ReferenceOverlayProvider sessionId={sessionId} primaryLap={bestLap}>
    <div className="space-y-6">
      {/* Header row: reference picker + theme selector */}
      <div className="flex justify-end items-center gap-3">
        <ReferenceFAB sessionId={sessionId} />
        <ChartThemePicker />
      </div>
      {/* ── Row 1: Track Map + Speed Trace + GG Diagram ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1">
          <div className="bg-concrete rounded-xl border border-steel/10 p-4 h-full flex flex-col">
            <div className="flex items-center gap-2 mb-3 shrink-0">
              <h3 className="text-sm font-monument text-chalk">GPS Track Map</h3>
              <ChartTooltip
                title="GPS Track Map"
                description="Shows the GPS trace of your laps on the track. The best lap is highlighted. Hover to sync with the speed trace."
                tips={['Click a point to see its distance on the speed trace', 'Use the lap dropdown to change which lap is displayed']}
              />
            </div>
            <div className="flex items-center gap-1 mb-2">
              <button
                onClick={() => setTrackColorMode("speed")}
                className={`px-2 py-0.5 text-xs font-telemetry rounded transition-colors ${
                  trackColorMode === "speed"
                    ? "text-chalk bg-steel/20"
                    : "text-steel hover:text-chalk"
                }`}
              >
                Speed
              </button>
              <button
                onClick={() => setTrackColorMode("grip")}
                className={`px-2 py-0.5 text-xs font-telemetry rounded transition-colors ${
                  trackColorMode === "grip"
                    ? "text-chalk bg-steel/20"
                    : "text-steel hover:text-chalk"
                }`}
              >
                Grip
              </button>
              <button
                onClick={() => setTrackColorMode("ribbon")}
                className={`px-2 py-0.5 text-xs font-telemetry rounded transition-colors ${
                  trackColorMode === "ribbon"
                    ? "text-chalk bg-steel/20"
                    : "text-steel hover:text-chalk"
                }`}
              >
                Surface
              </button>
            </div>
            <div className="chart-enter flex-1 min-h-0" role="img" aria-label="GPS track map showing the racing line for the selected lap">
              <GpsTrace
                sessionId={sessionId}
                apiBase={apiBase}
                gpsLaps={gpsLaps}
                bestLap={bestLap}
                className="w-full h-full"
                colorMode={trackColorMode}
              />
            </div>
          </div>
        </div>
        <div className="lg:col-span-2">
          <div className="bg-concrete rounded-xl border border-steel/10 p-4 relative">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-monument text-chalk">Speed Trace</h3>
                <ChartTooltip
                  title="Speed Trace"
                  description="Speed vs distance for the selected lap. The dashed gold line is the theoretical optimal. The dotted cyan line is your average pace across all laps."
                  tips={['Double-click to add an annotation', 'Hover to see speed at any distance point', 'Zoom with mouse wheel']}
                />
              </div>
              <ChartAnnotations sessionId={sessionId} canvasId="speed-chart" />
            </div>
            <SpeedTraceMiniMap sessionId={sessionId} bestLap={bestLap} size={90} />
            <div className="chart-enter" role="img" aria-label="Speed trace chart showing speed versus distance for the selected lap">
              <SpeedTraceZoom
                sessionId={sessionId}
                apiBase={apiBase}
                gpsLaps={gpsLaps}
                bestLap={bestLap}
                className="w-full"
                showPhysicsCeiling
              />
            </div>
          </div>
        </div>
        <div className="lg:col-span-2">
          <div className="bg-concrete rounded-xl border border-steel/10 p-4">
            <div className="flex items-center gap-2 mb-3">
              <h3 className="text-sm font-monument text-chalk">G-G Diagram</h3>
              <ChartTooltip
                title="G-G Diagram"
                description="Plots lateral vs longitudinal G-forces. The dashed circle is the friction limit. Points outside mean you exceeded grip. Use the play button to animate through the lap."
                tips={['Switch between All/Single/Compare modes', 'Click a point to highlight it on the map', 'Scroll to zoom in/out']}
              />
            </div>
            <div className="chart-enter" role="img" aria-label="G-G diagram plotting lateral versus longitudinal G-forces">
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
      </div>

      {/* ── Row 2: Delta Time Chart ── */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-4">
        <h3 className="text-sm font-monument text-chalk mb-3">Time Delta</h3>
        <div className="chart-enter" role="img" aria-label="Time delta chart showing cumulative time gained or lost versus the best lap">
        <DeltaTimeChart
          sessionId={sessionId}
          gpsLaps={gpsLaps}
          bestLap={bestLap}
          className="w-full"
        />
        </div>
      </div>

      {/* ── Row 2b: Aggregate Corner Coaching (multi-session proven envelope) ── */}
      <div>
        <CornerCoachingV4 sessionId={sessionId} className="w-full" />
      </div>

      {/* ── Row 2b2: Surface Profile (elevation, slope, camber, roughness) ── */}
      <div>
        <SurfaceProfileChart sessionId={sessionId} className="w-full" />
      </div>

      {/* ── Row 2c: Theoretical Delta + Corner Coaching (sim optimizer) ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-concrete rounded-xl border border-steel/10 p-4">
          <h3 className="text-sm font-monument text-chalk mb-3">Theoretical Delta</h3>
          <div className="chart-enter">
            <TheoreticalDeltaChart sessionId={sessionId} bestLap={bestLap} className="w-full" />
          </div>
        </div>
        <div>
          <CornerCoachingTable sessionId={sessionId} className="w-full" />
        </div>
      </div>

      {/* ── Row 3: Pedal Traces + RPM/Gear (if controls data available) ── */}
      {hasControls && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-concrete rounded-xl border border-steel/10 p-4">
            <h3 className="text-sm font-monument text-chalk mb-3">Pedal Traces</h3>
            <div className="chart-enter" role="img" aria-label="Pedal trace chart showing throttle and brake input versus distance">
              <PedalTraceChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} className="w-full" />
            </div>
          </div>
          {hasRpmGear ? (
            <div className="bg-concrete rounded-xl border border-steel/10 p-4">
              <h3 className="text-sm font-monument text-chalk mb-3">RPM &amp; Gear</h3>
              <div className="chart-enter" role="img" aria-label="RPM and gear selection chart versus distance for the selected lap">
                <RPMGearChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} className="w-full" />
              </div>
            </div>
          ) : (
            <div className="bg-concrete rounded-xl border border-steel/10 p-4">
              <h3 className="text-sm font-monument text-chalk mb-3">Live Friction Circle</h3>
              <div className="chart-enter" role="img" aria-label="Live friction circle showing real-time grip usage as the lap progresses">
                <LiveFrictionCircle sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} className="w-full" />
              </div>
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
          <div className="chart-enter" role="img" aria-label="Live friction circle showing real-time grip usage as the lap progresses">
            <LiveFrictionCircle sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} className="w-full" />
          </div>
        </div>
      )}

      {/* ── Row 3c: Tire Heatmap + Wheel Slip (if tire data available) ── */}
      {(hasTireTemps || hasWheelSlip) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {hasTireTemps && (
            <div className="bg-concrete rounded-xl border border-steel/10 p-4">
              <h3 className="text-sm font-monument text-chalk mb-3">Tire Temperatures</h3>
              <div className="chart-enter" role="img" aria-label="Tire temperature heatmap showing heat distribution across all four tires">
                <TireHeatmapChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} className="w-full" />
              </div>
            </div>
          )}
          {hasWheelSlip && (
            <div className="bg-concrete rounded-xl border border-steel/10 p-4">
              <h3 className="text-sm font-monument text-chalk mb-3">Wheel Slip</h3>
              <div className="chart-enter" role="img" aria-label="Wheel slip chart showing traction loss events across the lap">
                <WheelSlipChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} className="w-full" />
              </div>
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
              <div className="chart-enter" role="img" aria-label="Brake temperature and pressure analysis chart for the selected lap">
                <BrakeAnalysisChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} className="w-full" />
              </div>
            </div>
          )}
          {hasFuel && (
            <div className="bg-concrete rounded-xl border border-steel/10 p-4">
              <h3 className="text-sm font-monument text-chalk mb-3">Fuel Strategy</h3>
              <div className="chart-enter" role="img" aria-label="Fuel consumption and strategy chart showing fuel level over the session">
                <FuelStrategyChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} className="w-full" />
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Row 4: Sector Analysis ── */}
      <SectorPanel sessionId={sessionId} className="bg-concrete rounded-xl border border-steel/10" />

      {/* ── Row 4: Lap Speed Overlay ── */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-4">
        <h3 className="text-sm font-monument text-chalk mb-3">Lap Speed Overlay</h3>
        <div className="chart-enter" role="img" aria-label="Lap speed overlay comparing speed traces of multiple laps on one chart">
          <LapSpeedOverlay
            sessionId={sessionId}
            apiBase={apiBase}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
          />
        </div>
      </div>

      {/* ── Row 5: Distribution + Progress ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-concrete rounded-xl border border-steel/10 p-4">
          <h3 className="text-sm font-monument text-chalk mb-3">Lap Distribution</h3>
          <div className="chart-enter" role="img" aria-label="Lap time distribution histogram showing the spread of lap times in this session">
            <LapDistribution sessionId={sessionId} apiBase={apiBase} />
          </div>
        </div>
        <div className="chart-enter">
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
    </ReferenceOverlayProvider>
  );
}
