'use client';

/**
 * AnalyticsTab — telemetry analytics page, 5-tier layout.
 *
 * Information architecture:
 *   01 / LAP REVIEW          — what happened in the lap (Track + Speed + GG)
 *   02 / PACE & PROGRESSION  — how pace changed (Delta + Lap Progress/Distribution + Overlay)
 *   03 / VEHICLE DYNAMICS    — how the car was driven (Pedals, RPM, Tires, Brakes, Fuel, Friction)
 *   04 / ANALYSIS & COACHING — where time was lost and how to find it (Sectors, Corners, Drills)
 *   05 / CONTEXT             — reference data (Surface, cross-session)
 *
 * Every chart sits inside a chart-kit ChartCard with a ChartHeader.
 * No more bare bg-concrete wrappers, no more inconsistent titles.
 */

import { useEffect, useState } from 'react';
import { BACKEND_URL } from '@/lib/api-client';
import {
  ChartCard,
  ChartHeader,
  SectionHeader,
} from '@/components/shared/chart-kit';
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
import { LapSelector } from './LapSelector';
import { ChartThemePicker } from '@/components/app/ChartThemePicker';
import { ChartAnnotations } from '@/components/app/ChartAnnotations';
import { ReferenceOverlayProvider, ReferenceFAB } from '@/components/app/reference';

/* ── Types ──────────────────────────────────── */

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

/* ── Track-colour toggle (tier-01 speed-map control) ────────── */

interface TrackColorToggleProps {
  value: 'speed' | 'grip' | 'ribbon';
  onChange: (v: 'speed' | 'grip' | 'ribbon') => void;
}

function TrackColorToggle({ value, onChange }: TrackColorToggleProps) {
  const options: Array<{ key: TrackColorToggleProps['value']; label: string }> = [
    { key: 'speed', label: 'Speed' },
    { key: 'grip', label: 'Grip' },
    { key: 'ribbon', label: 'Surface' },
  ];
  return (
    <div className="flex items-center gap-0.5">
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          onClick={() => onChange(o.key)}
          className={`px-2 py-0.5 text-[10px] font-telemetry uppercase tracking-wider rounded transition-colors ${
            value === o.key
              ? 'text-chalk bg-steel/15'
              : 'text-steel hover:text-chalk'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* ── Component ──────────────────────────────── */

export function AnalyticsTab({
  sessionId,
  gpsLaps,
  bestLap,
  scores,
  corners,
  trackName,
}: AnalyticsTabProps) {
  const apiBase = BACKEND_URL;
  const [trackColorMode, setTrackColorMode] = useState<'speed' | 'grip' | 'ribbon'>('speed');

  // Session-level lap selection — drives every chart in the tab.
  // Primary defaults to the session best lap (from parent). Compare is opt-in.
  const [primaryLap, setPrimaryLap] = useState<number | null>(bestLap);
  const [compareLap, setCompareLap] = useState<number | null>(null);

  // Keep primaryLap in sync if bestLap resolves later (laps loaded after mount).
  useEffect(() => {
    if (primaryLap == null && bestLap != null) {
      setPrimaryLap(bestLap);
    }
  }, [bestLap, primaryLap]);

  const { channels } = useSessionChannels(sessionId);

  const hasControls = channels.throttle || channels.brake;
  const hasRpmGear = channels.rpm || channels.gear;
  const hasTireTemps = channels.tire_temp;
  const hasWheelSlip = channels.wheel_slip;
  const hasBrakeTemps = channels.brake_temp;
  const hasFuel = channels.fuel;

  const hasDynamics =
    hasControls || hasTireTemps || hasWheelSlip || hasBrakeTemps || hasFuel;
  const hasDynamicsPairTop = hasControls && hasRpmGear;
  const hasDynamicsPairMid = !!hasTireTemps || !!hasWheelSlip;
  const hasDynamicsPairBottom = !!hasBrakeTemps || !!hasFuel;

  return (
    <ReferenceOverlayProvider sessionId={sessionId} primaryLap={bestLap}>
      {/* ── Page controls strip (quiet, not a "tier") ── */}
      <div className="flex items-center justify-between gap-3 pb-2 flex-wrap">
        <LapSelector
          sessionId={sessionId}
          primaryLap={primaryLap}
          compareLap={compareLap}
          onPrimaryChange={(l) => {
            setPrimaryLap(l);
            // if user picks the same lap as compare, drop compare
            if (l != null && l === compareLap) setCompareLap(null);
          }}
          onCompareChange={setCompareLap}
        />
        <div className="flex items-center gap-3">
          <ReferenceFAB sessionId={sessionId} />
          <ChartThemePicker />
        </div>
      </div>

      <div className="space-y-12">
        {/* ════════════════════════════════════════════════════════════ */}
        {/* 01 / LAP REVIEW — the hero tier. Primary pace + spatial + grip */}
        {/* ════════════════════════════════════════════════════════════ */}
        <section className="space-y-5">
          <SectionHeader
            index="01"
            title="Lap Review"
            description="What happened in your fastest lap — speed, line, and grip usage."
          />

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 items-start">
            {/* Track map — left column (1/3 width), natural height */}
            <div className="lg:col-span-1">
              <ChartCard>
                <ChartHeader
                  title="Track Map"
                  info="GPS trace of the selected lap. Hover to sync with the speed trace."
                  actions={
                    <TrackColorToggle
                      value={trackColorMode}
                      onChange={setTrackColorMode}
                    />
                  }
                />
                <div
                  className="chart-enter w-full"
                  style={{ height: 420 }}
                  role="img"
                  aria-label="GPS track map showing the racing line"
                >
                  <GpsTrace
                    sessionId={sessionId}
                    apiBase={apiBase}
                    gpsLaps={gpsLaps}
                    bestLap={primaryLap}
                    compareLap={compareLap}
                    controlledLap
                    className="w-full h-full"
                    colorMode={trackColorMode}
                  />
                </div>
              </ChartCard>
            </div>

            {/* Speed trace + GG stacked, 2/3 width */}
            <div className="lg:col-span-2 flex flex-col gap-5">
              <ChartCard tone="primary">
                <ChartHeader
                  title="Speed Trace"
                  subtitle="km/h vs distance"
                  info="Speed across the lap. Dashed = theoretical optimal; dotted = your average pace; racing-purple dashed = cross-session reference."
                  actions={
                    <ChartAnnotations sessionId={sessionId} canvasId="speed-chart" />
                  }
                />
                <SpeedTraceMiniMap sessionId={sessionId} bestLap={primaryLap} size={80} />
                <div
                  className="chart-enter"
                  role="img"
                  aria-label="Speed trace chart showing speed versus distance"
                >
                  <SpeedTraceZoom
                    sessionId={sessionId}
                    apiBase={apiBase}
                    gpsLaps={gpsLaps}
                    bestLap={primaryLap}
                    compareLap={compareLap}
                    controlledLap
                    className="w-full"
                    showPhysicsCeiling
                  />
                </div>
              </ChartCard>

              <ChartCard>
                <ChartHeader
                  title="G-G Diagram"
                  subtitle="lat × long acceleration"
                  info="Grip usage envelope. Points outside the friction circle mean grip was exceeded."
                />
                <div
                  className="chart-enter"
                  role="img"
                  aria-label="G-G diagram showing lateral versus longitudinal acceleration"
                >
                  <GGExplorer
                    sessionId={sessionId}
                    apiBase={apiBase}
                    gpsLaps={gpsLaps}
                    bestLap={primaryLap}
                    controlledLap
                    className="w-full"
                  />
                </div>
              </ChartCard>
            </div>
          </div>
        </section>

        {/* ════════════════════════════════════════════════════════════ */}
        {/* 02 / PACE & PROGRESSION — cross-lap narrative                 */}
        {/* ════════════════════════════════════════════════════════════ */}
        <section className="space-y-5">
          <SectionHeader
            index="02"
            title="Pace & Progression"
            description="How pace shifted within the lap and across the session."
          />

          <ChartCard>
            <ChartHeader
              title="Time Delta"
              subtitle="cumulative time vs reference lap"
              info="Green where you gained time, red where you lost it. Purple dashed shows the cross-session reference delta."
            />
            <div
              className="chart-enter"
              role="img"
              aria-label="Cumulative time delta versus best lap"
            >
              <DeltaTimeChart
                sessionId={sessionId}
                gpsLaps={gpsLaps}
                bestLap={primaryLap}
                compareLap={compareLap}
                controlledLap
                className="w-full"
              />
            </div>
          </ChartCard>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {/* LapProgressTracker owns its own ChartCard — do not wrap */}
            <div className="chart-enter">
              <LapProgressTracker sessionId={sessionId} apiBase={apiBase} />
            </div>
            {/* LapDistribution owns its ChartCard — do not wrap */}
            <div className="chart-enter">
              <LapDistribution sessionId={sessionId} apiBase={apiBase} />
            </div>
          </div>

          <ChartCard>
            <ChartHeader
              title="Lap Speed Overlay"
              subtitle="every lap, one chart"
              info="All enabled laps drawn together, best lap emphasised. Use the legend to toggle individual laps."
            />
            <div
              className="chart-enter"
              role="img"
              aria-label="Overlay of multiple lap speed traces on one chart"
            >
              <LapSpeedOverlay
                sessionId={sessionId}
                apiBase={apiBase}
                gpsLaps={gpsLaps}
                bestLap={primaryLap}
              />
            </div>
          </ChartCard>
        </section>

        {/* ════════════════════════════════════════════════════════════ */}
        {/* 03 / VEHICLE DYNAMICS — conditional, quieter                  */}
        {/* ════════════════════════════════════════════════════════════ */}
        {hasDynamics ? (
          <section className="space-y-5">
            <SectionHeader
              index="03"
              title="Vehicle Dynamics"
              description="How the car was driven — inputs, rotations, tyre + brake behaviour."
            />

            {/* Pedals + RPM/Gear */}
            {hasControls && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                <ChartCard density="compact">
                  <ChartHeader
                    title="Pedal Traces"
                    subtitle="throttle × brake vs distance"
                  />
                  <div
                    className="chart-enter"
                    role="img"
                    aria-label="Pedal trace chart showing throttle and brake input"
                  >
                    <PedalTraceChart
                      sessionId={sessionId}
                      gpsLaps={gpsLaps}
                      bestLap={primaryLap}
                      controlledLap
                      className="w-full"
                    />
                  </div>
                </ChartCard>
                {hasRpmGear ? (
                  <ChartCard density="compact">
                    <ChartHeader title="RPM & Gear" subtitle="engine speed and gear selection" />
                    <div
                      className="chart-enter"
                      role="img"
                      aria-label="RPM and gear selection chart"
                    >
                      <RPMGearChart
                        sessionId={sessionId}
                        gpsLaps={gpsLaps}
                        bestLap={primaryLap}
                        controlledLap
                        className="w-full"
                      />
                    </div>
                  </ChartCard>
                ) : (
                  <ChartCard density="compact">
                    <ChartHeader
                      title="Friction Circle"
                      subtitle="real-time grip usage"
                    />
                    <div
                      className="chart-enter"
                      role="img"
                      aria-label="Live friction circle showing real-time grip usage"
                    >
                      <LiveFrictionCircle
                        sessionId={sessionId}
                        gpsLaps={gpsLaps}
                        bestLap={primaryLap}
                        controlledLap
                        className="w-full"
                      />
                    </div>
                  </ChartCard>
                )}
              </div>
            )}

            {/* Standalone friction circle when BOTH controls and RPM exist */}
            {hasDynamicsPairTop && (
              <ChartCard density="compact">
                <ChartHeader
                  title="Friction Circle"
                  subtitle="grip usage as the lap progresses"
                />
                <div
                  className="chart-enter"
                  role="img"
                  aria-label="Live friction circle"
                >
                  <LiveFrictionCircle
                    sessionId={sessionId}
                    gpsLaps={gpsLaps}
                    bestLap={primaryLap}
                    controlledLap
                    className="w-full"
                  />
                </div>
              </ChartCard>
            )}

            {/* Tires + wheel slip */}
            {hasDynamicsPairMid && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                {hasTireTemps && (
                  <ChartCard density="compact">
                    <ChartHeader
                      title="Tire Temperatures"
                      subtitle="all four corners"
                    />
                    <div
                      className="chart-enter"
                      role="img"
                      aria-label="Tire temperature heatmap"
                    >
                      <TireHeatmapChart
                        sessionId={sessionId}
                        gpsLaps={gpsLaps}
                        bestLap={primaryLap}
                        controlledLap
                        className="w-full"
                      />
                    </div>
                  </ChartCard>
                )}
                {hasWheelSlip && (
                  <ChartCard density="compact">
                    <ChartHeader
                      title="Wheel Slip"
                      subtitle="traction-loss events across the lap"
                    />
                    <div
                      className="chart-enter"
                      role="img"
                      aria-label="Wheel slip chart"
                    >
                      <WheelSlipChart
                        sessionId={sessionId}
                        gpsLaps={gpsLaps}
                        bestLap={primaryLap}
                        controlledLap
                        className="w-full"
                      />
                    </div>
                  </ChartCard>
                )}
              </div>
            )}

            {/* Brake analysis + fuel strategy */}
            {hasDynamicsPairBottom && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                {hasBrakeTemps && (
                  <ChartCard density="compact">
                    <ChartHeader
                      title="Brake Analysis"
                      subtitle="temperature and pressure"
                    />
                    <div
                      className="chart-enter"
                      role="img"
                      aria-label="Brake temperature and pressure analysis"
                    >
                      <BrakeAnalysisChart
                        sessionId={sessionId}
                        gpsLaps={gpsLaps}
                        bestLap={primaryLap}
                        controlledLap
                        className="w-full"
                      />
                    </div>
                  </ChartCard>
                )}
                {hasFuel && (
                  <ChartCard density="compact">
                    <ChartHeader
                      title="Fuel Strategy"
                      subtitle="consumption across the session"
                    />
                    <div
                      className="chart-enter"
                      role="img"
                      aria-label="Fuel consumption and strategy chart"
                    >
                      <FuelStrategyChart
                        sessionId={sessionId}
                        gpsLaps={gpsLaps}
                        bestLap={primaryLap}
                        controlledLap
                        className="w-full"
                      />
                    </div>
                  </ChartCard>
                )}
              </div>
            )}
          </section>
        ) : null}

        {/* ════════════════════════════════════════════════════════════ */}
        {/* 04 / ANALYSIS & COACHING — where time was lost, what to do   */}
        {/* ════════════════════════════════════════════════════════════ */}
        <section className="space-y-5">
          <SectionHeader
            index="04"
            title="Analysis & Coaching"
            description="Where time was lost and where to focus next."
          />

          <ChartCard>
            <ChartHeader title="Sector Analysis" subtitle="time split by sector" />
            <SectorPanel sessionId={sessionId} className="!bg-transparent !border-0 !rounded-none !p-0" />
          </ChartCard>

          <ChartCard>
            <ChartHeader
              title="Corner Coaching"
              subtitle="multi-session proven envelope"
              info="Corners where your inputs deviate from the aggregate proven line across all your sessions on this track."
            />
            <div className="chart-enter">
              <CornerCoachingV4 sessionId={sessionId} className="w-full" />
            </div>
          </ChartCard>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <ChartCard>
              <ChartHeader
                title="Theoretical Delta"
                subtitle="vs perfect-lap solver"
                info="Cumulative time loss compared to the sim-optimizer's theoretical perfect lap from identified physics."
              />
              <div className="chart-enter">
                <TheoreticalDeltaChart
                  sessionId={sessionId}
                  bestLap={primaryLap}
                  className="w-full"
                />
              </div>
            </ChartCard>
            <ChartCard>
              <ChartHeader
                title="Corner-by-Corner"
                subtitle="ranked by time loss"
              />
              <div className="chart-enter">
                <CornerCoachingTable sessionId={sessionId} className="w-full" />
              </div>
            </ChartCard>
          </div>

          <ChartCard>
            <ChartHeader
              title="Development Drills"
              subtitle="what to work on before the next session"
            />
            <div className="chart-enter">
              <DevelopmentDrills scores={scores} corners={corners} />
            </div>
          </ChartCard>
        </section>

        {/* ════════════════════════════════════════════════════════════ */}
        {/* 05 / CONTEXT — quiet references                              */}
        {/* ════════════════════════════════════════════════════════════ */}
        <section className="space-y-5">
          <SectionHeader
            index="05"
            title="Context"
            description="Track characteristics and cross-session comparisons."
          />

          <ChartCard density="compact">
            <ChartHeader
              title="Track Surface"
              subtitle="elevation, slope, camber, roughness"
            />
            <div className="chart-enter">
              <SurfaceProfileChart sessionId={sessionId} className="w-full" />
            </div>
          </ChartCard>

          <ChartCard density="compact">
            <ChartHeader
              title="Session Comparison"
              subtitle="this session against your history"
            />
            <div className="chart-enter">
              <SessionComparison sessionId={sessionId} trackName={trackName} />
            </div>
          </ChartCard>
        </section>

        {/* Empty-data advisory (tier 03 fallback) */}
        {!hasDynamics && (
          <p className="text-[11px] font-telemetry text-steel/60 italic">
            Vehicle dynamics require throttle / brake / RPM / tyre / fuel channels —
            available in iRacing, ACC, and MoTeC exports.
          </p>
        )}
      </div>
    </ReferenceOverlayProvider>
  );
}
