'use client';

import type { EntityDeleteResult } from '@/hooks/useEntityDelete';

/** Human-readable labels for cascade table names */
const IMPACT_LABELS: Record<string, string> = {
  sessions: 'sessions',
  laps: 'laps',
  score_details: 'scores',
  gps_traces: 'GPS traces',
  corner_metrics: 'corner analyses',
  development_plans: 'development plans',
  race_stints: 'stints',
  race_pit_stops: 'pit stops',
  race_drivers: 'driver assignments',
  race_windows: 'windows',
  race_sleep_windows: 'sleep windows',
  race_rivals: 'rivals',
  race_rival_events: 'rival events',
  track_sectors: 'sectors',
  track_records: 'records',
  weekend_sessions: 'weekend links',
  track_key_corners: 'key corners',
  corner_best_practices: 'corner best practices',
  driver_badges: 'badges',
  driver_profiles: 'driver profiles',
  user_corners: 'custom corners',
  plan_drill_sessions: 'drill sessions',
  session_weather_laps: 'weather lap data',
  race_messages: 'race messages',
  race_neutralizations: 'neutralizations',
  session_annotations: 'annotations',
  driving_style_features: 'driving style data',
  driver_progression: 'progression data',
  condition_phases: 'condition phases',
  condition_markers: 'condition markers',
  vehicle_setups: 'vehicle setups',
  what_if_scenarios: 'what-if scenarios',
  theoretical_data: 'theoretical data',
  reference_lines: 'reference lines',
  data_health: 'data health checks',
  stint_analysis: 'stint analyses',
  session_sectors: 'session sectors',
  session_tags: 'session tags',
  session_weather: 'weather data',
};

function formatImpactLabel(key: string): string {
  // Handle "(unlinked)" suffix
  const isUnlinked = key.endsWith(' (unlinked)');
  const baseKey = isUnlinked ? key.replace(' (unlinked)', '') : key;
  const label = IMPACT_LABELS[baseKey] || baseKey.replace(/_/g, ' ');
  return isUnlinked ? `${label} (unlinked)` : label;
}

interface DeleteConfirmPanelProps extends Pick<
  EntityDeleteResult,
  'showConfirm' | 'isPending' | 'error' | 'impact' | 'isLoadingImpact' | 'confirmDelete' | 'cancelDelete'
> {
  /** Name of entity being deleted, e.g. "Spa-Francorchamps" */
  entityName: string;
  /** Type of entity, e.g. "track" */
  entityType: string;
  /** 'full' for detail pages, 'compact' for list rows */
  variant?: 'full' | 'compact';
}

export function DeleteConfirmPanel({
  showConfirm,
  isPending,
  error,
  impact,
  isLoadingImpact,
  confirmDelete,
  cancelDelete,
  entityName,
  entityType,
  variant = 'full',
}: DeleteConfirmPanelProps) {
  if (!showConfirm) return null;

  // -- Compact variant for list pages -----------------------------------------
  if (variant === 'compact') {
    return (
      <span className="inline-flex items-center gap-2">
        <span className="text-safety-red text-xs font-body">Delete {entityName}?</span>
        <button
          type="button"
          onClick={confirmDelete}
          disabled={isPending}
          className="px-2 py-0.5 bg-safety-red text-white font-telemetry text-xs rounded hover:bg-safety-red/80 transition-colors disabled:opacity-50"
        >
          {isPending ? 'Deleting...' : 'Confirm'}
        </button>
        <button
          type="button"
          onClick={cancelDelete}
          className="px-2 py-0.5 text-steel font-telemetry text-xs hover:text-chalk transition-colors"
        >
          Cancel
        </button>
      </span>
    );
  }

  // -- Full variant for detail pages ------------------------------------------
  const nonZeroImpact = impact
    ? Object.entries(impact).filter(([, count]) => count > 0)
    : [];

  return (
    <div className="bg-safety-red/5 border border-safety-red/30 rounded-lg p-4 mb-6">
      <p className="text-chalk font-body text-sm mb-3">
        Are you sure you want to delete <strong>{entityName}</strong>?
      </p>

      {/* Impact summary */}
      {isLoadingImpact && (
        <div className="flex items-center gap-2 mb-3">
          <div className="w-3 h-3 border border-steel/40 border-t-pit-orange rounded-full animate-spin" />
          <span className="text-steel font-telemetry text-xs">Calculating impact...</span>
        </div>
      )}

      {!isLoadingImpact && nonZeroImpact.length > 0 && (
        <p className="text-safety-red font-body text-sm mb-3">
          This will permanently delete:{' '}
          {nonZeroImpact
            .map(([key, count]) => `${count} ${formatImpactLabel(key)}`)
            .join(', ')}
        </p>
      )}

      {/* Error message */}
      {error && (
        <p className="text-safety-red font-telemetry text-sm mb-2">{error}</p>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={confirmDelete}
          disabled={isPending}
          className="px-4 py-2 bg-safety-red text-white font-telemetry text-sm rounded hover:bg-safety-red/80 transition-colors disabled:opacity-50"
        >
          {isPending ? 'Deleting...' : 'Confirm Delete'}
        </button>
        <button
          type="button"
          onClick={cancelDelete}
          className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
