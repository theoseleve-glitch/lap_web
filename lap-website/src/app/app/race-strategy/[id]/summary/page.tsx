'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard } from '@/components/app';

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

interface DriverStat {
  name: string;
  total_drive_s: number;
  n_stints: number;
  longest_stint_s: number;
  shortest_stint_s: number;
}

interface SummaryData {
  race: RaceConfig;
  drivers: Driver[];
  stints: Stint[];
  pit_stops: PitStop[];
  windows: Array<Record<string, unknown>>;
  driver_stats: Record<number, DriverStat>;
  total_drive_s: number;
  total_pit_s: number;
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

function formatDurationShort(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h${m.toString().padStart(2, '0')}`;
  return `${m}m`;
}

function buildDriverColorMap(drivers: Driver[]): Record<number, string> {
  const fallback = ['#ef4444', '#3b82f6', '#22c55e', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316'];
  const map: Record<number, string> = {};
  drivers.forEach((d, i) => {
    map[d.id] = d.color_hex || fallback[i % fallback.length];
  });
  return map;
}

const stintStatusConfig: Record<string, { label: string; className: string }> = {
  planned: { label: 'PLANNED', className: 'text-steel bg-steel/10 border-steel/30' },
  active: { label: 'ACTIVE', className: 'text-acid-green bg-acid-green/10 border-acid-green/30' },
  completed: { label: 'DONE', className: 'text-chalk bg-chalk/10 border-chalk/30' },
  skipped: { label: 'SKIPPED', className: 'text-safety-red bg-safety-red/10 border-safety-red/30' },
};

/* ── StintTimeline ────────────────────────────────────────────────── */

function StintTimeline({
  stints,
  totalDuration,
  driverColors,
}: {
  stints: Stint[];
  totalDuration: number;
  driverColors: Record<number, string>;
}) {
  if (!stints.length || !totalDuration) return null;
  return (
    <div className="flex h-10 w-full overflow-hidden border border-steel/20 rounded">
      {stints.map((s) => {
        const dur = s.actual_duration_s || s.planned_duration_s || 0;
        const pct = (dur / totalDuration) * 100;
        const bg = driverColors[s.driver_id] || '#888';
        return (
          <div
            key={s.stint_id}
            className="flex items-center justify-center text-[10px] font-telemetry text-asphalt truncate border-r border-asphalt/30 last:border-r-0"
            style={{ width: `${pct}%`, backgroundColor: bg }}
            title={`${s.driver_name} \u2014 ${formatTime(dur)}`}
          >
            {pct > 8 ? s.driver_name : ''}
          </div>
        );
      })}
    </div>
  );
}

/* ── Summary Page ─────────────────────────────────────────────────── */

export default function SummaryPage() {
  const params = useParams();
  const router = useRouter();
  const qc = useQueryClient();
  const raceId = params.id as string;

  const { data, isLoading, error } = useQuery({
    queryKey: ['race-strategy', raceId, 'summary'],
    queryFn: () => api.get<SummaryData>(`/race-strategy/${raceId}/summary`),
  });

  const duplicateMut = useMutation({
    mutationFn: () => api.post<{ race_id: number }>(`/race-strategy/${raceId}/duplicate`),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['race-strategy'] });
      router.push(`/app/race-strategy/${res.race_id}`);
    },
  });

  /* ── loading / error ────────────────────────────────────────────── */

  if (isLoading) {
    return <div className="text-steel font-body p-8 text-center">Loading race summary...</div>;
  }

  if (error || !data) {
    return (
      <div className="text-safety-red font-body p-8 text-center">
        Failed to load summary.{' '}
        <button onClick={() => router.push('/app/race-strategy')} className="underline text-pit-orange">
          Back to list
        </button>
      </div>
    );
  }

  const { race, drivers, stints, pit_stops, driver_stats, total_drive_s, total_pit_s } = data;
  const driverColors = buildDriverColorMap(drivers);
  const completedStints = stints.filter((s) => s.status === 'completed');
  const uniqueDriverIds = new Set(stints.map((s) => s.driver_id));

  /* ── render ─────────────────────────────────────────────────────── */

  return (
    <div className="space-y-6">
      {/* Header */}
      <PageHeader
        title={race.race_name}
        subtitle={
          [race.track_name, race.team_name].filter(Boolean).join(' \u2014 ') +
          (race.track_name || race.team_name ? ' \u2014 ' : '') +
          'Race Summary'
        }
        actions={
          <span className="inline-flex px-2 py-0.5 text-[10px] font-telemetry tracking-[0.12em] uppercase border text-chalk bg-chalk/10 border-chalk/30">
            FINISHED
          </span>
        }
      />

      {/* Stats Strip */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <StatCard label="Race Duration" value={formatDurationShort(race.race_duration_s)} />
        <StatCard label="Drive Time" value={formatDurationShort(total_drive_s)} />
        <StatCard label="Pit Time" value={formatDurationShort(total_pit_s)} />
        <StatCard label="Stints" value={completedStints.length} />
        <StatCard label="Pit Stops" value={pit_stops.length} />
        <StatCard label="Drivers" value={uniqueDriverIds.size} />
      </div>

      {/* Stint Timeline */}
      <div className="space-y-2">
        <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Stint Timeline</h3>
        <StintTimeline stints={stints} totalDuration={race.race_duration_s} driverColors={driverColors} />
      </div>

      {/* Driver Stats */}
      <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden">
        <div className="px-4 py-3 border-b border-steel/20">
          <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Driver Statistics</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-steel/20">
                <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Driver</th>
                <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Total Drive</th>
                <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Stints</th>
                <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Longest</th>
                <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Shortest</th>
                <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">% of Race</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(driver_stats).map(([driverId, stat]) => {
                const numId = Number(driverId);
                const pctOfRace = total_drive_s > 0 ? ((stat.total_drive_s / total_drive_s) * 100).toFixed(1) : '0.0';
                return (
                  <tr key={driverId} className="border-b border-steel/10">
                    <td className="px-4 py-3 text-chalk font-body text-sm">
                      <div className="flex items-center gap-2">
                        <span
                          className="w-3 h-3 rounded-full shrink-0"
                          style={{ backgroundColor: driverColors[numId] }}
                        />
                        {stat.name}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">{formatTime(stat.total_drive_s)}</td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">{stat.n_stints}</td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">{formatTime(stat.longest_stint_s)}</td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">{formatTime(stat.shortest_stint_s)}</td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-2 bg-asphalt rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${pctOfRace}%`,
                              backgroundColor: driverColors[numId],
                            }}
                          />
                        </div>
                        <span>{pctOfRace}%</span>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {Object.keys(driver_stats).length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-steel font-body text-sm">
                    No driver statistics available.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Stint Log */}
      <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden">
        <div className="px-4 py-3 border-b border-steel/20">
          <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Stint Log</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-steel/20">
                <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">#</th>
                <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Driver</th>
                <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Planned</th>
                <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Actual</th>
                <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Delta</th>
                <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Status</th>
              </tr>
            </thead>
            <tbody>
              {stints.map((s) => {
                const planned = s.planned_duration_s;
                const actual = s.actual_duration_s;
                const delta = planned != null && actual != null ? actual - planned : null;
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
                    <td className="px-4 py-3 text-chalk font-body text-sm">{formatTime(planned)}</td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">{formatTime(actual)}</td>
                    <td className="px-4 py-3 font-telemetry text-sm">
                      {delta != null ? (
                        <span className={delta <= 0 ? 'text-acid-green' : 'text-safety-red'}>
                          {delta <= 0 ? '' : '+'}{formatTime(Math.abs(delta))}
                        </span>
                      ) : (
                        <span className="text-steel">{'\u2014'}</span>
                      )}
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
                  <td colSpan={6} className="px-4 py-6 text-center text-steel font-body text-sm">
                    No stints recorded.
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
                  <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">#</th>
                  <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Time</th>
                  <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Duration</th>
                  <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Driver Change</th>
                  <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Refueled</th>
                  <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Fuel Added</th>
                  <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Type</th>
                </tr>
              </thead>
              <tbody>
                {pit_stops.map((p, i) => (
                  <tr key={p.pit_id} className="border-b border-steel/10">
                    <td className="px-4 py-3 text-chalk font-body text-sm">{i + 1}</td>
                    <td className="px-4 py-3 text-chalk font-body text-sm">
                      {formatTime(p.actual_at_s ?? p.planned_at_s)}
                    </td>
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

      {/* Actions */}
      <div className="flex items-center gap-3 flex-wrap pt-2 border-t border-steel/20">
        <a
          href={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000'}/api/v1/race-strategy/${raceId}/export`}
          className="px-4 py-2 bg-pit-orange text-asphalt font-telemetry text-sm tracking-wider uppercase hover:bg-pit-orange/80 transition-colors"
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
        <Link
          href={`/app/race-strategy/${raceId}`}
          className="px-4 py-2 border border-steel/30 text-chalk font-telemetry text-sm tracking-wider uppercase hover:bg-concrete transition-colors"
        >
          View Config
        </Link>
        <Link
          href="/app/race-strategy"
          className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm tracking-wider uppercase hover:bg-concrete hover:text-chalk transition-colors ml-auto"
        >
          All Races
        </Link>
      </div>
    </div>
  );
}
