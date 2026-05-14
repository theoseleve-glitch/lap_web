'use client';

/**
 * Day-13 Phase C — ConditionRow visual showcase.
 *
 * Temporary dev page for visual verification before Phase D. Renders
 * the four canonical ConditionRow scenarios with synthetic data
 * (no backend needed):
 *   - OK_R4: greasy / user override / mu_scale 0.82
 *   - KCT_R1: dry / weather / mu_scale 0.92
 *   - SLK_FP: wet / weather / mu_scale 0.60
 *   - Pre-Day-11: conditions=null → row collapses entirely
 *
 * Delete after Phase F close-out (the real home for ConditionRow is
 * the session detail view at /app/sessions/[id], which requires a
 * running backend + analysis_json with conditions populated).
 */

import { ConditionRow } from '@/components/app/track-surface/TrackSurfacePanel';
import type { WeatherConditionBlock } from '@/components/app/track-surface/useTrackSurfaceData';

const OK_R4: WeatherConditionBlock = {
  label: 'greasy',
  mu_scale: 0.82,
  confidence: 1.0,
  dominant_factor: 'user_override',
  rationale:
    "User-supplied condition='greasy'; spec §2 user-override wins over weather. Per-segment μ-modifier uses the wet clamp range [0.6, 1.5] rather than dry's tighter [0.9, 1.1].",
  source: 'user',
  spatial_modifier: null,
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

export default function ConditionsShowcasePage() {
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
