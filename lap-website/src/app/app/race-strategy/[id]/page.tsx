'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { api, BACKEND_URL } from '@/lib/api-client';
import { PageHeader, SkeletonBox, SkeletonTableRows } from '@/components/app';
import { StintTimeline } from '@/components/app/race-strategy/StintTimeline';

/* ── shared types ─────────────────────────────────────────────────── */

interface RaceConfig {
  race_id: number;
  race_name: string;
  track_name: string | null;
  team_name: string | null;
  race_duration_s: number;
  desired_stints: number;
  fuel_autonomy_s: number | null;
  min_pit_stop_s: number;
  empty_kart_kg: number | null;
  full_tank_kg: number | null;
  min_total_kart_kg: number | null;
  reference_weight_kg: number | null;
  status: 'draft' | 'ready' | 'live' | 'finished';
  race_start_ts: string | null;
  created_at: string;
}

interface Driver {
  id: number;
  driver_name: string;
  driver_order: number;
  weight_kg: number | null;
  com_channel: string | null;
  color_hex: string | null;
  min_stint_s: number | null;
  max_stint_s: number | null;
}

interface Stint {
  stint_id: number;
  stint_order: number;
  driver_id: number;
  driver_name: string;
  planned_start_s: number | null;
  planned_end_s: number | null;
  planned_duration_s: number | null;
  actual_start_s: number | null;
  actual_end_s: number | null;
  actual_duration_s: number | null;
  fuel_at_start: number | null;
  fuel_at_end: number | null;
  ballast_kg: number | null;
  status: 'planned' | 'active' | 'completed' | 'skipped';
}

interface PitStop {
  pit_id: number;
  planned_at_s: number | null;
  actual_at_s: number | null;
  duration_s: number | null;
  driver_change: number;
  refueled: number;
  fuel_added_kg: number | null;
  pit_type: string;
}

interface RaceDetail {
  race: RaceConfig;
  drivers: Driver[];
  stints: Stint[];
  pit_stops: PitStop[];
  windows: Array<Record<string, unknown>>;
}

/* ── helpers ──────────────────────────────────────────────────────── */

function formatTime(s: number | null | undefined): string {
  if (s == null) return '\u2014';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`;
  return `${m}:${sec.toString().padStart(2, '0')}`;
}

const statusConfig: Record<string, { label: string; className: string }> = {
  draft: { label: 'DRAFT', className: 'text-steel bg-steel/10 border-steel/30' },
  ready: { label: 'READY', className: 'text-marshal-yellow bg-marshal-yellow/10 border-marshal-yellow/30' },
  live: { label: 'LIVE', className: 'text-acid-green bg-acid-green/10 border-acid-green/30 animate-pulse' },
  finished: { label: 'FINISHED', className: 'text-chalk bg-chalk/10 border-chalk/30' },
};

const stintStatusConfig: Record<string, { label: string; className: string }> = {
  planned: { label: 'PLANNED', className: 'text-steel bg-steel/10 border-steel/30' },
  active: { label: 'ACTIVE', className: 'text-acid-green bg-acid-green/10 border-acid-green/30 animate-pulse' },
  completed: { label: 'DONE', className: 'text-chalk bg-chalk/10 border-chalk/30' },
  skipped: { label: 'SKIPPED', className: 'text-safety-red bg-safety-red/10 border-safety-red/30' },
};

function buildDriverColorMap(drivers: Driver[]): Record<number, string> {
  const fallback = ['#ef4444', '#3b82f6', '#22c55e', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316'];
  const map: Record<number, string> = {};
  drivers.forEach((d, i) => {
    map[d.id] = d.color_hex || fallback[i % fallback.length];
  });
  return map;
}

/* ── Detail Page ──────────────────────────────────────────────────── */

export default function RaceDetailPage() {
  const params = useParams();
  const router = useRouter();
  const qc = useQueryClient();
  const raceId = params.id as string;

  const { data, isLoading, error } = useQuery({
    queryKey: ['race-strategy', raceId],
    queryFn: () => api.get<RaceDetail>(`/race-strategy/${raceId}`),
  });

  /* ── mutations ──────────────────────────────────────────────────── */

  const optimizeMut = useMutation({
    mutationFn: () => api.post<unknown>(`/race-strategy/${raceId}/optimize`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['race-strategy', raceId] }),
  });

  const goLiveMut = useMutation({
    mutationFn: () => api.post<unknown>(`/race-strategy/${raceId}/go-live`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['race-strategy', raceId] });
      router.push(`/app/race-strategy/${raceId}/live`);
    },
  });

  const duplicateMut = useMutation({
    mutationFn: () => api.post<{ race_id: number }>(`/race-strategy/${raceId}/duplicate`),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['race-strategy'] });
      router.push(`/app/race-strategy/${res.race_id}`);
    },
  });

  const deleteMut = useMutation({
    mutationFn: () => api.delete<unknown>(`/race-strategy/${raceId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['race-strategy'] });
      router.push('/app/race-strategy');
    },
  });

  /* ── loading / error ────────────────────────────────────────────── */

  if (isLoading) {
    return (
      <div>
        <div className="mb-4">
          <SkeletonBox className="h-6 w-48 mb-2" />
          <SkeletonBox className="h-3 w-32" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="bg-concrete rounded-lg border border-steel/20 p-4">
              <SkeletonBox className="h-3 w-16 mb-3" />
              <SkeletonBox className="h-4 w-24 mb-2" />
              <SkeletonBox className="h-4 w-20 mb-2" />
              <SkeletonBox className="h-4 w-28" />
            </div>
          ))}
        </div>
        <SkeletonTableRows rows={4} cols={6} />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="bg-concrete rounded-lg border border-safety-red/20 p-8 text-center">
        <div className="text-safety-red font-telemetry text-3xl mb-3" aria-hidden="true">!</div>
        <p className="text-chalk font-body text-sm mb-1">Failed to load race</p>
        <p className="text-steel font-body text-xs mb-4">The race may have been deleted or there was a network error.</p>
        <Link href="/app/race-strategy" className="text-pit-orange font-telemetry text-xs hover:underline">
          ← Back to all races
        </Link>
      </div>
    );
  }

  const { race, drivers, stints, pit_stops } = data;
  const driverColors = buildDriverColorMap(drivers);
  const cfg = statusConfig[race.status] || statusConfig.draft;
  const editable = race.status === 'draft' || race.status === 'ready';

  /* ── render ─────────────────────────────────────────────────────── */

  return (
    <div className="space-y-6">
      {/* Header */}
      <PageHeader
        title={race.race_name}
        subtitle={[race.track_name, race.team_name].filter(Boolean).join(' \u2014 ') || undefined}
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            <Link
              href="/app/race-strategy"
              className="px-3 py-1.5 border border-steel/30 text-steel font-telemetry text-xs rounded hover:text-chalk hover:border-steel/60 transition-colors"
            >
              ← All Races
            </Link>
            <span
              className={`inline-flex px-2 py-0.5 text-[10px] font-telemetry tracking-[0.12em] uppercase border ${cfg.className}`}
            >
              {cfg.label}
            </span>
          </div>
        }
      />

      {/* Action Buttons */}
      <div className="flex items-center gap-3 flex-wrap">
        {editable && (
          <button
            onClick={() => optimizeMut.mutate()}
            disabled={optimizeMut.isPending}
            className="px-4 py-2 bg-acid-green text-asphalt font-telemetry text-sm tracking-wider uppercase hover:bg-acid-green/80 transition-colors disabled:opacity-50"
          >
            {optimizeMut.isPending ? 'Optimizing...' : 'Optimize'}
          </button>
        )}
        {race.status === 'ready' && (
          <button
            onClick={() => {
              if (window.confirm('Start the race? This will set the timer running.')) {
                goLiveMut.mutate();
              }
            }}
            disabled={goLiveMut.isPending}
            className="px-4 py-2 bg-pit-orange text-asphalt font-telemetry text-sm tracking-wider uppercase hover:bg-pit-orange/80 transition-colors disabled:opacity-50"
          >
            {goLiveMut.isPending ? 'Going Live...' : 'Go Live'}
          </button>
        )}
        {editable && (
          <Link
            href={`/app/race-strategy/${raceId}/edit`}
            className="px-4 py-2 border border-steel/30 text-chalk font-telemetry text-sm tracking-wider uppercase hover:bg-concrete transition-colors"
          >
            Edit
          </Link>
        )}
        <a
          href={`${BACKEND_URL}/api/v1/race-strategy/${raceId}/export`}
          className="px-4 py-2 border border-steel/30 text-chalk font-telemetry text-sm tracking-wider uppercase hover:bg-concrete transition-colors"
          download
        >
          Export
        </a>
        <button
          onClick={() => duplicateMut.mutate()}
          disabled={duplicateMut.isPending}
          className="px-4 py-2 border border-steel/30 text-chalk font-telemetry text-sm tracking-wider uppercase hover:bg-concrete transition-colors disabled:opacity-50"
        >
          {duplicateMut.isPending ? 'Duplicating...' : 'Duplicate'}
        </button>
        <button
          onClick={() => {
            if (window.confirm('Delete this race? This cannot be undone.')) {
              deleteMut.mutate();
            }
          }}
          disabled={deleteMut.isPending}
          className="px-4 py-2 border border-safety-red/40 text-safety-red font-telemetry text-sm tracking-wider uppercase hover:bg-safety-red/10 transition-colors disabled:opacity-50"
        >
          {deleteMut.isPending ? 'Deleting...' : 'Delete'}
        </button>
      </div>

      {/* Config Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Race */}
        <div className="bg-concrete rounded-lg border border-steel/20 p-4 space-y-3">
          <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Race</h3>
          <div className="space-y-2 text-sm font-body">
            <div className="flex justify-between">
              <span className="text-steel">Duration</span>
              <span className="text-chalk">{formatTime(race.race_duration_s)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-steel">Stints</span>
              <span className="text-chalk">{race.desired_stints}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-steel">Min Pit Stop</span>
              <span className="text-chalk">{formatTime(race.min_pit_stop_s)}</span>
            </div>
          </div>
        </div>
        {/* Weight */}
        <div className="bg-concrete rounded-lg border border-steel/20 p-4 space-y-3">
          <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Weight</h3>
          <div className="space-y-2 text-sm font-body">
            <div className="flex justify-between">
              <span className="text-steel">Empty Kart</span>
              <span className="text-chalk">{race.empty_kart_kg != null ? `${race.empty_kart_kg} kg` : '\u2014'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-steel">Full Tank</span>
              <span className="text-chalk">{race.full_tank_kg != null ? `${race.full_tank_kg} kg` : '\u2014'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-steel">Min Total</span>
              <span className="text-chalk">{race.min_total_kart_kg != null ? `${race.min_total_kart_kg} kg` : '\u2014'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-steel">Reference</span>
              <span className="text-chalk">{race.reference_weight_kg != null ? `${race.reference_weight_kg} kg` : '\u2014'}</span>
            </div>
          </div>
        </div>
        {/* Fuel */}
        <div className="bg-concrete rounded-lg border border-steel/20 p-4 space-y-3">
          <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Fuel</h3>
          <div className="space-y-2 text-sm font-body">
            <div className="flex justify-between">
              <span className="text-steel">Autonomy</span>
              <span className="text-chalk">{formatTime(race.fuel_autonomy_s)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-steel">Min Pit Stop</span>
              <span className="text-chalk">{formatTime(race.min_pit_stop_s)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Driver Roster */}
      <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden">
        <div className="px-4 py-3 border-b border-steel/20">
          <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Drivers</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-steel/20">
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">#</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Driver</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Weight</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">COM</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Min Stint</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Max Stint</th>
              </tr>
            </thead>
            <tbody>
              {drivers.map((d) => (
                <tr key={d.id} className="border-b border-steel/10">
                  <td className="px-4 py-3 text-chalk font-body text-sm">{d.driver_order}</td>
                  <td className="px-4 py-3 text-chalk font-body text-sm">
                    <div className="flex items-center gap-2">
                      <span
                        className="w-3 h-3 rounded-full shrink-0"
                        style={{ backgroundColor: driverColors[d.id] }}
                      />
                      {d.driver_name}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-chalk font-body text-sm">
                    {d.weight_kg != null ? `${d.weight_kg} kg` : '\u2014'}
                  </td>
                  <td className="px-4 py-3 text-chalk font-body text-sm">{d.com_channel || '\u2014'}</td>
                  <td className="px-4 py-3 text-chalk font-body text-sm">{formatTime(d.min_stint_s)}</td>
                  <td className="px-4 py-3 text-chalk font-body text-sm">{formatTime(d.max_stint_s)}</td>
                </tr>
              ))}
              {drivers.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-steel font-body text-sm">
                    No drivers added yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Stint Timeline */}
      <div className="space-y-2">
        <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Stint Timeline</h3>
        <StintTimeline stints={stints} totalDuration={race.race_duration_s} driverColors={driverColors} />
      </div>

      {/* Stint Table */}
      <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden">
        <div className="px-4 py-3 border-b border-steel/20">
          <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Stints</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-steel/20">
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">#</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Driver</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Start</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">End</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Duration</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Fuel Start</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Fuel End</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Ballast</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Status</th>
              </tr>
            </thead>
            <tbody>
              {stints.map((s) => {
                const sCfg = stintStatusConfig[s.status] || stintStatusConfig.planned;
                return (
                  <tr key={s.stint_id} className="border-b border-steel/10">
                    <td className="px-4 py-3 text-chalk font-body text-sm">{s.stint_order}</td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">
                      <div className="flex items-center gap-2">
                        <span
                          className="w-3 h-3 rounded-full shrink-0"
                          style={{ backgroundColor: driverColors[s.driver_id] }}
                        />
                        {s.driver_name}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">
                      {formatTime(s.actual_start_s ?? s.planned_start_s)}
                    </td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">
                      {formatTime(s.actual_end_s ?? s.planned_end_s)}
                    </td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">
                      {formatTime(s.actual_duration_s ?? s.planned_duration_s)}
                    </td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">
                      {s.fuel_at_start != null ? `${s.fuel_at_start.toFixed(1)} kg` : '\u2014'}
                    </td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">
                      {s.fuel_at_end != null ? `${s.fuel_at_end.toFixed(1)} kg` : '\u2014'}
                    </td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">
                      {s.ballast_kg != null ? `${s.ballast_kg} kg` : '\u2014'}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex px-2 py-0.5 text-[10px] font-telemetry tracking-[0.12em] uppercase border ${sCfg.className}`}
                      >
                        {sCfg.label}
                      </span>
                    </td>
                  </tr>
                );
              })}
              {stints.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-6 text-center text-steel font-body text-sm">
                    No stints planned yet. Run Optimize to generate a plan.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pit Stops */}
      {pit_stops.length > 0 && (
        <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden">
          <div className="px-4 py-3 border-b border-steel/20">
            <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Pit Stops</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-steel/20">
                  <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">#</th>
                  <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Planned</th>
                  <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Actual</th>
                  <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Duration</th>
                  <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Driver Change</th>
                  <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Refueled</th>
                  <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Fuel Added</th>
                  <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Type</th>
                </tr>
              </thead>
              <tbody>
                {pit_stops.map((p, i) => (
                  <tr key={p.pit_id} className="border-b border-steel/10">
                    <td className="px-4 py-3 text-chalk font-body text-sm">{i + 1}</td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">{formatTime(p.planned_at_s)}</td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">{formatTime(p.actual_at_s)}</td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">{formatTime(p.duration_s)}</td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">{p.driver_change ? 'Yes' : 'No'}</td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">{p.refueled ? 'Yes' : 'No'}</td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">
                      {p.fuel_added_kg != null ? `${p.fuel_added_kg.toFixed(1)} kg` : '\u2014'}
                    </td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">{p.pit_type || '\u2014'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
