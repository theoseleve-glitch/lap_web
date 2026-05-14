'use client';

import { useState } from 'react';
import { TrackSurface3D, type HeatmapMode } from './TrackSurface3D';
import {
  useTrackSurfaceData,
  type SensorQualityBlock,
  type WeatherConditionBlock,
} from './useTrackSurfaceData';

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

/* 0.7 effective μ is the spec's "track feels slippery" driver threshold;
 * it maps to (0.7 − 0.5) / (1.0 − 0.5) = 40 % along the legend gradient. */
const SPATIAL_GRIP_THRESHOLD_PCT = 40;

/* ── Component ────────────────────────────────────────── */

export default function TrackSurfacePanel({ sessionId, className }: TrackSurfacePanelProps) {
  const [mode, setMode] = useState<HeatmapMode>('grip');
  const [showOptimal, setShowOptimal] = useState(true);
  const [showActual, setShowActual] = useState(false);
  const { surface, isLoading } = useTrackSurfaceData(sessionId);

  const legend = LEGEND[mode];
  const qualityTier = surface?.quality_tier ?? null;

  // Day-13 Phase D: spatial-grip mode requires a spatial_modifier on the
  // conditions blob; pre-Day-12 sessions (or safe-dry fallback runs) keep
  // the button visible but disabled with an explanatory tooltip.
  const spatialDisabled = !surface?.conditions?.spatial_modifier;
  const spatialLowConfidence =
    mode === 'spatial-grip' &&
    typeof surface?.conditions?.confidence === 'number' &&
    surface.conditions.confidence < 0.5;

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
        {MODES.map(({ key, label }) => {
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
              <span>Effective μ = mu_data × mu_scale × spatial_factor</span>
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
          per Day-13 Phase C lock — empty slot is the honest UI. */}
      <ConditionRow conditions={surface?.conditions ?? null} />

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
