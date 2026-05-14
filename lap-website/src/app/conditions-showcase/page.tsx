'use client';

/**
 * Day-13 Phase C-E — ConditionRow + SpatialDiagnosticsPanel visual showcase.
 *
 * Temporary dev page for visual verification before Phase F. Renders
 * the four canonical ConditionRow scenarios + the interactive
 * SpatialDiagnosticsPanel + a stub 5-segment mesh preview that updates
 * when factors are toggled (the "embedded in the 3D mesh" insight from
 * Phase E review).
 *
 * Delete after Phase F close-out — the real home is /app/sessions/[id]
 * with a backend serving conditions blobs.
 */

import { useState } from 'react';
import {
  ConditionRow,
  SpatialDiagnosticsPanel,
} from '@/components/app/track-surface/TrackSurfacePanel';
import type { SpatialFactor } from '@/components/app/track-surface/TrackSurface3D';
import type {
  SpatialMuModifierBlock,
  WeatherConditionBlock,
} from '@/components/app/track-surface/useTrackSurfaceData';

/** 5-segment synthetic spatial modifier anchored on OK_R4 Day-12 Phase H
 *  numbers: factor_values 0.736..1.457 (1.979× spread), drainage
 *  [0.85, 1.30], sun uniform 0.95, wind [0.85, 1.10] @ 179°/26 km/h. */
const OK_R4_SPATIAL: SpatialMuModifierBlock = {
  arclength_samples: [0.0, 200.0, 400.0, 600.0, 800.0],
  factor_values: [1.457, 1.039, 0.736, 1.039, 1.457],
  drainage_components: [1.3, 1.05, 0.85, 1.05, 1.3],
  sun_components: [0.95, 0.95, 0.95, 0.95, 0.95],
  wind_components: [1.1, 0.98, 0.85, 0.98, 1.1],
  sun_altitude_deg: 23.5,
  sun_azimuth_deg: 157.5,
  wind_direction_deg: 179.0,
  wind_speed_kmh: 26.0,
  mesh_source: 'hand_traced',
  spatial_version: 'spatial-v1.0',
};

const OK_R4: WeatherConditionBlock = {
  label: 'greasy',
  mu_scale: 0.82,
  confidence: 1.0,
  dominant_factor: 'user_override',
  rationale:
    "User-supplied condition='greasy'; spec §2 user-override wins over weather. Per-segment μ-modifier uses the wet clamp range [0.6, 1.5] rather than dry's tighter [0.9, 1.1].",
  source: 'user',
  spatial_modifier: OK_R4_SPATIAL,
  classifier_version: 'weather-v1.0+spatial-v1.0',
};

const KCT_R1: WeatherConditionBlock = {
  label: 'dry',
  mu_scale: 0.92,
  confidence: 0.87,
  track_temp_estimate_c: 24.5,
  hours_since_rain: 72,
  days_since_significant_rain: 5,
  dominant_factor: 'low_humidity_warm_track',
  rationale:
    '72 h since last rain, track temperature estimate 24.5 °C, low relative humidity. Spec §5 baseline-dry rule applies; mu_scale anchored at 0.92 for warm dry asphalt.',
  source: 'weather',
  spatial_modifier: null,
  classifier_version: 'weather-v1.0+spatial-v1.0',
};

const SLK_FP: WeatherConditionBlock = {
  label: 'wet',
  mu_scale: 0.6,
  confidence: 0.93,
  track_temp_estimate_c: 14.2,
  water_film_estimate: 'thin',
  hours_since_rain: 0.5,
  drying_rate_estimate: 0.4,
  dominant_factor: 'recent_rain_thin_film',
  rationale:
    'Open-Meteo: ~30 minutes since last precipitation event, 14.2 °C track. Spec §5 wet-with-water-film classification; thin film + cool surface → mu_scale 0.60 (water-flag conditions).',
  source: 'weather',
  spatial_modifier: null,
  classifier_version: 'weather-v1.0+spatial-v1.0',
};

const SAMPLES: { id: string; description: string; data: WeatherConditionBlock | null }[] = [
  {
    id: 'OK_R4',
    description:
      'user-overridden greasy session. Source pill "User override", chip gold/orange, mu_scale bar ~58 % filled.',
    data: OK_R4,
  },
  {
    id: 'KCT_R1',
    description:
      'weather-classified dry session. Source pill "Weather data", chip acid-green, mu_scale bar ~76 % filled.',
    data: KCT_R1,
  },
  {
    id: 'SLK_FP',
    description:
      'weather-classified wet session. Source pill "Weather data", chip chart-blue, mu_scale bar ~18 % filled.',
    data: SLK_FP,
  },
  {
    id: 'pre-Day-11',
    description:
      'pre-Day-11 session: conditions=null → ConditionRow returns null, no row rendered, no placeholder, no layout shift. The grey "row absent" border below this label is what an older session would render.',
    data: null,
  },
];

/* ── Mesh preview helpers ───────────────────────────────── */

/** Linear interpolation between safety-red (#FF2A2A) and acid-green
 *  (#22C55E) for a t ∈ [0, 1]. Mirrors the THREE.Color.lerp the real
 *  3D mesh uses; the showcase doesn't load Three.js so we do it here in
 *  plain CSS RGB. */
function lerpHotCold(t: number): string {
  const u = Math.max(0, Math.min(1, t));
  const r = Math.round(0xff + (0x22 - 0xff) * u);
  const g = Math.round(0x2a + (0xc5 - 0x2a) * u);
  const b = Math.round(0x2a + (0x5e - 0x2a) * u);
  return `rgb(${r},${g},${b})`;
}

const SPATIAL_GRIP_COLOR_MIN = 0.5;
const SPATIAL_GRIP_COLOR_MAX = 1.0;
const INDIVIDUAL_FACTOR_MIN = 0.85;
const INDIVIDUAL_FACTOR_MAX = 1.3;

function meshColorsForFactor(
  factor: SpatialFactor,
  sm: SpatialMuModifierBlock,
  muScale: number,
): string[] {
  if (factor === 'combined') {
    // effective_mu = grip_mu × mu_scale × factor_values; assume grip_mu ≈ 1
    // for the preview (we don't have real bins here).
    return sm.factor_values.map((fv) => {
      const effectiveMu = muScale * fv;
      const t = (effectiveMu - SPATIAL_GRIP_COLOR_MIN) /
        (SPATIAL_GRIP_COLOR_MAX - SPATIAL_GRIP_COLOR_MIN);
      return lerpHotCold(t);
    });
  }
  const arr =
    factor === 'drainage' ? sm.drainage_components
    : factor === 'sun' ? sm.sun_components
    : sm.wind_components;
  return arr.map((v) => {
    const t = (v - INDIVIDUAL_FACTOR_MIN) /
      (INDIVIDUAL_FACTOR_MAX - INDIVIDUAL_FACTOR_MIN);
    // Iso-factor: HIGH value (wetter) → red. Invert.
    return lerpHotCold(1 - t);
  });
}

function MeshPreview({
  factor,
  sm,
  muScale,
}: {
  factor: SpatialFactor;
  sm: SpatialMuModifierBlock;
  muScale: number;
}) {
  const colors = meshColorsForFactor(factor, sm, muScale);
  return (
    <div className="space-y-1">
      <div className="font-telemetry text-[10px] text-steel/60 uppercase tracking-wide">
        Stub 5-segment ribbon · factor: <span className="text-chalk">{factor}</span>
      </div>
      <div className="flex gap-px rounded overflow-hidden h-8 border border-steel/20">
        {colors.map((color, i) => (
          <div
            key={i}
            style={{ background: color }}
            className="flex-1"
            title={`segment ${i} · ${color}`}
          />
        ))}
      </div>
      <div className="flex justify-between font-telemetry text-[10px] text-steel/70 tabular-nums">
        <span>start of lap</span>
        <span>end of lap</span>
      </div>
    </div>
  );
}

/* ── Page ───────────────────────────────────────────────── */

export default function ConditionsShowcasePage() {
  const [activeFactor, setActiveFactor] = useState<SpatialFactor>('combined');
  return (
    <div className="min-h-screen bg-asphalt p-6 sm:p-10">
      <div className="max-w-5xl mx-auto space-y-6">
        <header className="space-y-2">
          <h1 className="font-monument text-h3 text-chalk uppercase tracking-wide">
            Day-13 Phase C · ConditionRow showcase
          </h1>
          <p className="font-body text-sm text-steel max-w-prose">
            Synthetic OK_R4 / KCT_R1 / SLK_FP / pre-Day-11 scenarios.
            The row renders inside TrackSurfacePanel between the legend
            bar and the Day-10.5 Sensor Quality row in the real session
            view. This page exists for visual sanity-check before Phase D.
          </p>
        </header>

        <div className="space-y-4">
          {SAMPLES.map((s) => (
            <section
              key={s.id}
              className="bg-concrete border border-steel/20 rounded-lg overflow-hidden"
            >
              <div className="flex items-center justify-between px-4 py-2 border-b border-steel/10">
                <span className="font-telemetry text-xs text-chalk uppercase tracking-wide">
                  {s.id}
                </span>
                <span className="font-body text-[11px] text-steel max-w-prose text-right">
                  {s.description}
                </span>
              </div>
              <ConditionRow conditions={s.data} />
              {s.data === null && (
                <div className="px-4 py-3 font-telemetry text-[10px] text-steel/50 uppercase tracking-wide border-t border-dashed border-steel/10">
                  (ConditionRow rendered null — no extra row)
                </div>
              )}
            </section>
          ))}
        </div>

        {/* ── Phase E — Spatial diagnostics + iso-factor mesh demo ── */}
        <header className="pt-8 space-y-2">
          <h2 className="font-monument text-h4 text-chalk uppercase tracking-wide">
            Day-13 Phase E · Iso-factor diagnostics
          </h2>
          <p className="font-body text-sm text-steel max-w-prose">
            Per-factor breakdown of the Day-12 producer output, with each
            row now a button that <span className="text-chalk">isolates that factor on the 3D mesh</span> in
            the real session view. The dimensionless 0.85 → 1.30 numbers
            become a legend for what the ribbon is showing. Click the
            rows below — the stub preview ribbon updates the way the real
            3D mesh would. Synthetic OK_R4 data (5 segments) anchored on
            Day-12 Phase H numbers.
          </p>
        </header>

        <section className="bg-concrete border border-steel/20 rounded-lg overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2 border-b border-steel/10">
            <span className="font-telemetry text-xs text-chalk uppercase tracking-wide">
              OK_R4 · click factor rows to isolate
            </span>
            <span className="font-body text-[11px] text-steel max-w-prose text-right">
              clicking an active factor reverts to Combined
            </span>
          </div>

          {/* Mesh preview row — updates when activeFactor changes */}
          <div className="px-4 py-3 border-b border-steel/10">
            <MeshPreview
              factor={activeFactor}
              sm={OK_R4_SPATIAL}
              muScale={OK_R4.mu_scale}
            />
          </div>

          <SpatialDiagnosticsPanel
            conditions={OK_R4}
            visible
            defaultOpen
            activeFactor={activeFactor}
            onFactorChange={setActiveFactor}
          />
        </section>

        <footer className="pt-4 font-body text-[11px] text-steel/70 max-w-prose">
          Color tokens used: <code className="text-acid-green">acid-green</code> (dry) ·{' '}
          <code className="text-marshal-yellow">marshal-yellow</code> (damp; not shown above
          since no real session has classified damp yet) ·{' '}
          <code className="text-[color:var(--chart-series-2)]">chart-series-2</code> (wet, blue) ·{' '}
          <code className="text-gold">gold</code> (greasy).
        </footer>
      </div>
    </div>
  );
}
