'use client';

import { useEffect, useState } from 'react';
import {
  TrackSurface3D,
  type HeatmapMode,
  type SpatialFactor,
} from './TrackSurface3D';
import {
  useTrackSurfaceData,
  type SensorQualityBlock,
  type WeatherConditionBlock,
} from './useTrackSurfaceData';
import { useSpatialFlag } from '@/hooks/useSpatialFlag';

/* ── Types ────────────────────────────────────────────── */

interface TrackSurfacePanelProps {
  sessionId: string;
  className?: string;
}

/* ── Mode config ──────────────────────────────────────── */

const MODES: { key: HeatmapMode; label: string }[] = [
  { key: 'grip', label: 'Grip' },
  { key: 'spatial-grip', label: 'Spatial Grip' },
  { key: 'elevation', label: 'Elevation' },
  { key: 'line-delta', label: 'Line Delta' },
];

/* ── Legend color stops (matching WebGL palette) ──────── */

const LEGEND: Record<
  HeatmapMode,
  { lowLabel: string; highLabel: string; lowHex: string; highHex: string }
> = {
  grip: { lowLabel: 'Low', highLabel: 'High', lowHex: '#FF2A2A', highHex: '#22C55E' },
  elevation: { lowLabel: 'Low', highLabel: 'High', lowHex: '#3B82F6', highHex: '#F0EDE5' },
  'line-delta': { lowLabel: 'Off-line', highLabel: 'On-line', lowHex: '#FF2A2A', highHex: '#22C55E' },
  // Day-13 Phase D: effective μ range fixed at [0.5, 1.0] — see
  // SPATIAL_GRIP_COLOR_MIN/MAX in TrackSurface3D.tsx. The dashed tick at
  // 40 % marks the spec's 0.7 driver-feedback threshold.
  'spatial-grip': { lowLabel: 'μ 0.5', highLabel: 'μ 1.0+', lowHex: '#FF2A2A', highHex: '#22C55E' },
};

/** Day-13 Phase E: per-factor legend labels under iso-factor mode.
 *  All four sub-modes share the red→green palette but the iso-factor
 *  versions invert (high factor → red = wetter), so the LEFT-side label
 *  describes the wetter end and the RIGHT-side label describes the
 *  drier end. */
const SPATIAL_FACTOR_LEGEND: Record<
  Exclude<SpatialFactor, 'combined'>,
  { lowLabel: string; highLabel: string }
> = {
  drainage: { lowLabel: 'Pooling (1.30)', highLabel: 'Drains (0.85)' },
  sun: { lowLabel: 'Shaded (1.20)', highLabel: 'Sunny (0.85)' },
  wind: { lowLabel: 'Leeward (1.15)', highLabel: 'Windward (0.85)' },
};

/* 0.7 effective μ is the spec's "track feels slippery" driver threshold;
 * it maps to (0.7 − 0.5) / (1.0 − 0.5) = 40 % along the legend gradient. */
const SPATIAL_GRIP_THRESHOLD_PCT = 40;

/* ── Component ────────────────────────────────────────── */

export default function TrackSurfacePanel({ sessionId, className }: TrackSurfacePanelProps) {
  const [mode, setMode] = useState<HeatmapMode>('grip');
  const [spatialFactor, setSpatialFactor] = useState<SpatialFactor>('combined');
  const [showOptimal, setShowOptimal] = useState(true);
  const [showActual, setShowActual] = useState(false);
  const { surface, isLoading } = useTrackSurfaceData(sessionId);

  // Day-13 Phase 7.5: conditions UI (ConditionRow + Spatial Grip mode +
  // SpatialDiagnosticsPanel) is gated behind ?debug=spatial until bug-4
  // (09a2 Distance(m) cascade) is fixed in Day-14.
  const spatialEnabled = useSpatialFlag();
  const visibleModes = spatialEnabled
    ? MODES
    : MODES.filter((m) => m.key !== 'spatial-grip');

  // Defensive: if the flag flips off (URL changed) while spatial-grip is
  // active, fall back to the default grip mode so the panel can't render
  // a hidden mode.
  useEffect(() => {
    if (!spatialEnabled && mode === 'spatial-grip') {
      setMode('grip');
    }
  }, [spatialEnabled, mode]);

  const qualityTier = surface?.quality_tier ?? null;

  // Day-13 Phase D: spatial-grip mode requires a spatial_modifier on the
  // conditions blob; pre-Day-12 sessions (or safe-dry fallback runs) keep
  // the button visible but disabled with an explanatory tooltip.
  const spatialDisabled = !surface?.conditions?.spatial_modifier;
  const spatialLowConfidence =
    mode === 'spatial-grip' &&
    typeof surface?.conditions?.confidence === 'number' &&
    surface.conditions.confidence < 0.5;

  // Day-13 Phase E: when the user switches away from spatial-grip, reset
  // the factor selector so re-entering the mode starts at the combined
  // view (the default state).
  useEffect(() => {
    if (mode !== 'spatial-grip') setSpatialFactor('combined');
  }, [mode]);

  // Day-13 Phase E: legend labels follow the active sub-factor when
  // isolating a single component on the mesh.
  const legend =
    mode === 'spatial-grip' && spatialFactor !== 'combined'
      ? {
          ...LEGEND['spatial-grip'],
          ...SPATIAL_FACTOR_LEGEND[spatialFactor],
        }
      : LEGEND[mode];

  return (
    <div className={`bg-concrete border border-steel/20 rounded-lg overflow-hidden ${className ?? ''}`}>
      {/* Header row */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-steel/10">
        <h3 className="font-monument text-chalk text-sm tracking-wide uppercase">
          Track Surface
        </h3>

        {qualityTier && (
          <span className="font-telemetry text-xs text-steel bg-steel/10 border border-steel/30 rounded px-2 py-0.5">
            {qualityTier}
          </span>
        )}
      </div>

      {/* Mode selector */}
      <div className="flex items-center gap-1 px-4 py-2 border-b border-steel/10">
        {visibleModes.map(({ key, label }) => {
          const disabled = key === 'spatial-grip' && spatialDisabled;
          const titleAttr = disabled
            ? 'Spatial μ requires Day-12+ analysis (session uploaded before this feature, or weather lookup unavailable).'
            : undefined;
          return (
            <button
              key={key}
              type="button"
              onClick={() => !disabled && setMode(key)}
              disabled={disabled}
              title={titleAttr}
              className={`font-telemetry text-xs px-3 py-1.5 rounded transition-colors ${
                disabled
                  ? 'text-steel/40 cursor-not-allowed'
                  : mode === key
                    ? 'text-gold'
                    : 'text-steel hover:text-chalk'
              }`}
            >
              {label}
            </button>
          );
        })}

        <div className="ml-auto flex items-center gap-3">
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={showOptimal}
              onChange={(e) => setShowOptimal(e.target.checked)}
              className="sr-only peer"
            />
            <span className="block w-3 h-3 rounded-sm border border-steel/40 peer-checked:bg-gold peer-checked:border-gold transition-colors" />
            <span className="font-telemetry text-xs text-steel">Optimal</span>
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={showActual}
              onChange={(e) => setShowActual(e.target.checked)}
              className="sr-only peer"
            />
            <span className="block w-3 h-3 rounded-sm border border-steel/40 peer-checked:bg-chalk peer-checked:border-chalk transition-colors" />
            <span className="font-telemetry text-xs text-steel">Actual</span>
          </label>
        </div>
      </div>

      {/* 3D canvas */}
      <TrackSurface3D
        sessionId={sessionId}
        mode={mode}
        spatialFactor={spatialFactor}
        showOptimalLine={showOptimal}
        showActualLine={showActual}
        className="w-full aspect-[16/9]"
      />

      {/* Legend bar */}
      {!isLoading && (
        <div className="flex flex-col gap-1 px-4 py-2 border-t border-steel/10">
          <div className="flex items-center gap-2">
            <span className="font-telemetry text-xs text-steel">{legend.lowLabel}</span>
            <div className="relative flex-1 h-2">
              <div
                className="absolute inset-0 rounded-full"
                style={{
                  background: `linear-gradient(to right, ${legend.lowHex}, ${legend.highHex})`,
                }}
              />
              {mode === 'spatial-grip' && (
                <div
                  className="absolute top-0 bottom-0 w-px bg-chalk/70"
                  style={{ left: `${SPATIAL_GRIP_THRESHOLD_PCT}%` }}
                  title="μ = 0.7 — driver feedback threshold"
                  aria-label="μ = 0.7 driver feedback threshold"
                />
              )}
            </div>
            <span className="font-telemetry text-xs text-steel">{legend.highLabel}</span>
          </div>
          {mode === 'spatial-grip' && (
            <div className="flex items-center justify-between font-telemetry text-[10px] text-steel/70">
              <span>
                Effective μ = mu_data × mu_scale × spatial_factor
                {surface?.conditions?.spatial_modifier?.tile_grid_shape && (
                  <span className="ml-2 text-gold" title="Per-tile 2D fields rendered across the cross-section (banking-driven). Adjacent-terrain shadowing + shielding unlock in V1.5.">
                    · 2D per-tile
                  </span>
                )}
              </span>
              <span title="0.7 effective μ ≈ track feels slippery">μ = 0.7 threshold</span>
            </div>
          )}
          {spatialLowConfidence && surface?.conditions && (
            <div className="font-telemetry text-[10px] text-marshal-yellow">
              ⚠ Low classifier confidence
              ({Math.round(surface.conditions.confidence * 100)}%) —
              spatial grip rendering uses reduced opacity; data may be unreliable
            </div>
          )}
        </div>
      )}

      {/* Conditions (Day-11/12). Renders nothing on pre-Day-11 sessions
          per Day-13 Phase C lock — empty slot is the honest UI.
          Phase 7.5: gated behind ?debug=spatial until bug-4 resolved. */}
      {spatialEnabled && <ConditionRow conditions={surface?.conditions ?? null} />}

      {/* Spatial diagnostics (Day-13 Phase E). Per-factor breakdown
          of the Day-12 producer output AND the iso-factor selector that
          isolates a single component on the 3D mesh. Collapsible,
          default-collapsed. Renders only in spatial-grip mode when
          spatial data is present.
          Phase 7.5: gated behind ?debug=spatial until bug-4 resolved. */}
      {spatialEnabled && (
        <SpatialDiagnosticsPanel
          conditions={surface?.conditions ?? null}
          visible={mode === 'spatial-grip'}
          activeFactor={spatialFactor}
          onFactorChange={setSpatialFactor}
        />
      )}

      {/* Sensor Quality (RC6) */}
      <SensorQualityRow sq={surface?.sensor_quality ?? null} isLoading={isLoading} />
    </div>
  );
}

/* ── Sensor Quality sub-panel ─────────────────────────── */

function median(arr: number[]): number {
  if (!arr.length) return 0;
  const sorted = [...arr].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 === 0
    ? (sorted[mid - 1]! + sorted[mid]!) / 2
    : sorted[mid]!;
}

function maxAbs(arr: number[]): number {
  if (!arr.length) return 0;
  return arr.reduce((acc, v) => Math.max(acc, Math.abs(v)), 0);
}

interface MetricTileProps {
  label: string;
  value: string;
  state: 'ok' | 'warn' | 'low';
  hint?: string;
}

function MetricTile({ label, value, state, hint }: MetricTileProps) {
  // Token-driven colours per CLAUDE.md.
  // ok    → text-chalk on bg-chalk/5
  // warn  → text-marshal-yellow on bg-marshal-yellow/10
  // low   → text-steel on bg-steel/10 (low-confidence grey state — RC6)
  const stateClasses = {
    ok: 'text-chalk bg-chalk/5 border-chalk/10',
    warn: 'text-marshal-yellow bg-marshal-yellow/10 border-marshal-yellow/30',
    low: 'text-steel bg-steel/10 border-steel/30',
  }[state];
  return (
    <div className={`flex-1 rounded border px-2 py-1.5 ${stateClasses}`}>
      <div className="font-telemetry text-[10px] uppercase tracking-wide opacity-80">
        {label}
      </div>
      <div className="font-telemetry text-sm tabular-nums">{value}</div>
      {hint && (
        <div className="font-telemetry text-[9px] opacity-60">{hint}</div>
      )}
    </div>
  );
}

function SensorQualityRow({
  sq,
  isLoading,
}: { sq: SensorQualityBlock | null; isLoading: boolean }) {
  if (isLoading) {
    // Match the resting grey state — avoid flicker while the API resolves.
    return (
      <div className="flex gap-2 px-4 py-2 border-t border-steel/10">
        <MetricTile label="Confidence"  value="--" state="low" />
        <MetricTile label="Calibration" value="--" state="low" />
        <MetricTile label="Bank est."   value="--" state="low" />
        <MetricTile label="Excited"     value="--" state="low" />
      </div>
    );
  }

  if (sq === null || sq === undefined) {
    return (
      <div className="flex gap-2 px-4 py-2 border-t border-steel/10">
        <MetricTile label="Sensor quality" value="Low confidence"
          state="low" hint="No IMU diagnostics for this session" />
      </div>
    );
  }

  // sq IS present — derive the 4 single-number summaries the panel shows.
  const med_conf = median(sq.orientation_quality ?? []);
  const med_cal = median((sq.curvature_agreement ?? []).filter((v) => v !== 0));
  const max_bank = maxAbs(sq.bank_sensitivity_deg ?? []);
  const excited = sq.map_confidence?.excited_sample_frac ?? 0;

  // State thresholds match the producer's saturation points: confidence ≥
  // 0.5 means we cleared count + excitation thresholds. Calibration ratio
  // within ±0.2 of 1.0 is acceptable; further off → warn.
  const conf_state: MetricTileProps['state'] =
    med_conf >= 0.5 ? 'ok' : med_conf >= 0.2 ? 'warn' : 'low';
  const cal_state: MetricTileProps['state'] =
    med_cal === 0 ? 'low' : Math.abs(med_cal - 1.0) <= 0.2 ? 'ok' : 'warn';
  const bank_state: MetricTileProps['state'] =
    max_bank === 0 ? 'low' : max_bank <= 3.0 ? 'ok' : 'warn';
  const exc_state: MetricTileProps['state'] =
    excited >= 0.3 ? 'ok' : excited >= 0.1 ? 'warn' : 'low';

  return (
    <div className="flex gap-2 px-4 py-2 border-t border-steel/10">
      <MetricTile
        label="Confidence"
        value={`${(med_conf * 100).toFixed(0)}%`}
        state={conf_state}
        hint="median per-bin"
      />
      <MetricTile
        label="Calibration"
        value={med_cal === 0 ? '--' : med_cal.toFixed(2)}
        state={cal_state}
        hint="|a_lat| / v²·κ"
      />
      <MetricTile
        label="Bank est."
        value={max_bank === 0 ? '--' : `±${max_bank.toFixed(1)}°`}
        state={bank_state}
        hint="peak |bank|"
      />
      <MetricTile
        label="Excited"
        value={`${(excited * 100).toFixed(0)}%`}
        state={exc_state}
        hint="near-limit samples"
      />
    </div>
  );
}

/* ── Conditions sub-row (Day-13 Phase C) ──────────────────────────── */

/** Label-chip palette. Tokens follow CLAUDE.md conventions:
 *  - dry / damp / greasy → semantic tokens
 *  - wet → chart-series-2 (#3B82F6) via CSS var. tokens.css exposes
 *    --color-info → racing-purple, but motorsport convention pairs wet
 *    with blue (water flag). chart-series-2 is the existing in-codebase
 *    blue used by the elevation legend; reusing it here keeps the
 *    palette internally consistent without introducing a raw hex. */
const LABEL_CHIP_STYLES: Record<
  WeatherConditionBlock['label'],
  string
> = {
  dry: 'text-acid-green bg-acid-green/10 border-acid-green/30',
  damp: 'text-marshal-yellow bg-marshal-yellow/10 border-marshal-yellow/30',
  wet: 'text-[color:var(--chart-series-2)] bg-[color:var(--chart-series-2)]/10 border-[color:var(--chart-series-2)]/30',
  greasy: 'text-gold bg-gold/10 border-gold/30',
};

const SOURCE_LABEL: Record<WeatherConditionBlock['source'], string> = {
  weather: 'Weather data',
  user: 'User override',
  ml_fallback: 'ML fallback',
};

export function ConditionRow({
  conditions,
}: {
  conditions: WeatherConditionBlock | null;
}) {
  if (!conditions) return null;

  const { label, mu_scale, confidence, dominant_factor, rationale, source } =
    conditions;

  // mu_scale bar — spec §6 lookup range is [0.55 greasy_cold, 1.00 dry];
  // pad both ends slightly to keep the indicator off the edges.
  const bar_min = 0.5;
  const bar_max = 1.05;
  const pct = Math.max(
    0,
    Math.min(1, (mu_scale - bar_min) / (bar_max - bar_min)),
  );

  // dominant_factor strings from the producer use snake_case (e.g.
  // "user_override", "rain_recent_dripping"). Format as small-caps tag
  // with the label appended.
  const factor_caption = `${dominant_factor.replace(/_/g, ' ')} · ${label}`;

  return (
    <div className="flex flex-col gap-2 px-4 py-3 border-t border-steel/10">
      {/* Row 1 — chip + bar + source pill */}
      <div className="flex items-center gap-3">
        <span
          className={`font-telemetry text-[10px] uppercase tracking-wide px-2 py-0.5 rounded border ${LABEL_CHIP_STYLES[label]}`}
        >
          {label}
        </span>

        <div className="flex-1 flex items-center gap-2 max-w-[240px]">
          <div className="flex-1 h-1.5 bg-steel/20 rounded-full overflow-hidden">
            <div
              className="h-full bg-chalk rounded-full"
              style={{ width: `${pct * 100}%` }}
            />
          </div>
          <span className="font-telemetry text-xs text-chalk tabular-nums w-10 text-right">
            {mu_scale.toFixed(2)}
          </span>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <span className="font-telemetry text-[10px] text-steel bg-steel/10 border border-steel/30 rounded px-2 py-0.5">
            {SOURCE_LABEL[source]}
          </span>
          <span className="font-telemetry text-[10px] text-steel">
            {Math.round(confidence * 100)}% conf
          </span>
        </div>
      </div>

      {/* Row 2 — dominant-factor caption */}
      <div className="font-telemetry text-[10px] uppercase tracking-wide text-steel">
        {factor_caption}
      </div>

      {/* Row 3 — rationale body text */}
      <div className="font-body text-xs text-steel/90 leading-relaxed max-w-prose">
        {rationale}
      </div>
    </div>
  );
}

/* ── Spatial diagnostics panel (Day-13 Phase E) ───────── */

/** Variance across a per-segment factor array, expressed as
 *  (max − min) / max — bounded to [0, 1], 0 means "uniform". This is
 *  the contribution to the combined spatial spread; sun_components on
 *  flat tracks come out 0 because every segment_normal ≈ (0, 0, 1) and
 *  the solar angle of incidence is therefore constant. That zero is
 *  load-bearing UX information (V1.5 ray-tracing unlocks variation on
 *  hilly tracks), so the panel surfaces it explicitly rather than
 *  hiding it behind a one-decimal rounding. */
function factorSpread(arr: readonly number[]): {
  min: number;
  max: number;
  spreadPct: number;
} {
  if (arr.length === 0) return { min: 0, max: 0, spreadPct: 0 };
  let min = Infinity;
  let max = -Infinity;
  for (const v of arr) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (!isFinite(min) || !isFinite(max) || max <= 0) {
    return { min: 0, max: 0, spreadPct: 0 };
  }
  return { min, max, spreadPct: ((max - min) / max) * 100 };
}

export function SpatialDiagnosticsPanel({
  conditions,
  visible,
  activeFactor = 'combined',
  onFactorChange,
  defaultOpen = false,
}: {
  conditions: WeatherConditionBlock | null;
  visible: boolean;
  activeFactor?: SpatialFactor;
  onFactorChange?: (factor: SpatialFactor) => void;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (!visible) return null;
  const sm = conditions?.spatial_modifier;
  if (!sm) return null;

  const drainage = factorSpread(sm.drainage_components);
  const sun = factorSpread(sm.sun_components);
  const wind = factorSpread(sm.wind_components);
  const combined = factorSpread(sm.factor_values);
  const spreadRatio =
    combined.min > 0 ? combined.max / combined.min : 1;

  const select = (f: SpatialFactor) => {
    onFactorChange?.(f);
    // Toggling the same factor twice falls back to combined view.
    if (activeFactor === f && f !== 'combined') onFactorChange?.('combined');
  };

  return (
    <div className="border-t border-steel/10">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full px-4 py-2 font-telemetry text-xs text-steel uppercase tracking-wide flex items-center justify-between hover:bg-steel/5 transition-colors"
      >
        <span>
          Spatial diagnostics ·{' '}
          <span className="text-chalk normal-case tabular-nums">
            {spreadRatio.toFixed(2)}× combined spread
          </span>
          {activeFactor !== 'combined' && (
            <span className="text-gold normal-case ml-2">
              (isolating {activeFactor})
            </span>
          )}
        </span>
        <span className="text-[10px]">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="px-4 py-3 space-y-3 border-t border-steel/10">
          {/* Iso-factor selector — clickable row tells the 3D mesh which
              component to isolate. Active factor highlighted in gold. */}
          <div className="font-body text-[10px] text-steel/60 leading-relaxed">
            Click a factor below to isolate it on the track ribbon —
            the colors then show where THAT component is wettest (red)
            vs driest (green). Click an active factor again to revert
            to the combined view.
          </div>

          <FactorBreakdown
            factorKey="combined"
            label="Combined"
            spreadPct={
              combined.spreadPct
            }
            min={combined.min}
            max={combined.max}
            active={activeFactor === 'combined'}
            onSelect={select}
            hint="effective μ = grip_mu × mu_scale × factor_values"
          />
          <FactorBreakdown
            factorKey="drainage"
            label="Drainage"
            spreadPct={drainage.spreadPct}
            min={drainage.min}
            max={drainage.max}
            active={activeFactor === 'drainage'}
            onSelect={select}
            hint="2D field on the mesh — inside-pools / outside-drains variation across banked sections. Magnitude scales with banking present in the track."
          />
          <FactorBreakdown
            factorKey="sun"
            label="Sun"
            spreadPct={sun.spreadPct}
            min={sun.min}
            max={sun.max}
            active={activeFactor === 'sun'}
            onSelect={select}
            hint="2D field on the mesh — per-tile angle-of-incidence variation from banking. Adjacent-terrain shadowing (treelines, grandstands, buildings) unlocks in V1.5 with a terrain data pipeline."
            extra={`solar pos: ${sm.sun_altitude_deg.toFixed(1)}° altitude · ${sm.sun_azimuth_deg.toFixed(0)}° azimuth`}
          />
          <FactorBreakdown
            factorKey="wind"
            label="Wind"
            spreadPct={wind.spreadPct}
            min={wind.min}
            max={wind.max}
            active={activeFactor === 'wind'}
            onSelect={select}
            hint="2D field on the mesh — windward / lee variation across banked surfaces. Adjacent-terrain shielding (diffraction past treelines + structures) unlocks in V1.5."
            extra={`wind: ${sm.wind_direction_deg.toFixed(0)}° · ${sm.wind_speed_kmh.toFixed(0)} km/h`}
          />

          {/* Mesh source provenance */}
          <div className="font-telemetry text-[10px] text-steel/60 pt-2 border-t border-steel/10">
            Mesh: <span className="text-steel">{sm.mesh_source}</span> ·{' '}
            Spec version: <span className="text-steel">{sm.spatial_version}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function FactorBreakdown({
  factorKey,
  label,
  spreadPct,
  min,
  max,
  active,
  onSelect,
  hint,
  extra,
}: {
  factorKey: SpatialFactor;
  label: string;
  spreadPct: number;
  min: number;
  max: number;
  active: boolean;
  onSelect: (factor: SpatialFactor) => void;
  hint?: string;
  extra?: string;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(factorKey)}
      aria-pressed={active}
      className={`w-full text-left space-y-0.5 px-2 py-1.5 rounded transition-colors border ${
        active
          ? 'border-gold/40 bg-gold/5'
          : 'border-transparent hover:bg-steel/5 hover:border-steel/20'
      }`}
    >
      <div className="flex items-baseline gap-3 font-telemetry text-xs flex-wrap">
        <span
          className={`uppercase tracking-wide w-20 shrink-0 ${active ? 'text-gold' : 'text-chalk'}`}
        >
          {label}
        </span>
        <span className="text-chalk tabular-nums">
          {spreadPct.toFixed(0)}% spread
        </span>
        <span className="text-steel/50">·</span>
        <span className="text-steel tabular-nums">
          {spreadPct === 0
            ? `uniform ${min.toFixed(3)}`
            : `${min.toFixed(3)} → ${max.toFixed(3)}`}
        </span>
      </div>
      {hint && (
        <div className="font-body text-[10px] text-steel/70 leading-relaxed ml-[5.25rem]">
          {hint}
        </div>
      )}
      {extra && (
        <div className="font-telemetry text-[10px] text-steel ml-[5.25rem]">
          {extra}
        </div>
      )}
    </button>
  );
}
