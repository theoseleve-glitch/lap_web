'use client';

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { PageIntro } from '@/components/ui/PageIntro';
import { StintTimeline } from '@/components/app/race-strategy/StintTimeline';
import { MessageLog } from '@/components/app/race-strategy/MessageLog';

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

interface LiveState {
  race: RaceConfig;
  drivers: Driver[];
  stints: Stint[];
  pit_stops: Array<Record<string, unknown>>;
  windows: Array<Record<string, unknown>>;
  messages: Array<Record<string, unknown>>;
  active_stint: Stint | null;
  next_stint: Stint | null;
  driver_cumulative: Record<number, number>;
  current_fuel_kg?: number;
  current_ballast?: Record<string, unknown>;
  fuel_model?: Record<string, unknown>;
  window_status?: Array<{
    window_id?: number;
    label?: string;
    status?: string;
    opens_at_s?: number;
    closes_at_s?: number;
    [key: string]: unknown;
  }>;
  is_neutralized?: boolean;
  sleep_windows?: Array<{
    id: number;
    driver_id: number;
    driver_name: string;
    start_s: number;
    end_s: number;
    label: string | null;
    actual_wake_s: number | null;
    status: 'planned' | 'active' | 'completed' | 'cancelled';
  }>;
  driver_sleep_status?: Record<number, {
    sleeping: boolean;
    until_s?: number;
    remaining_s?: number;
    window_id?: number;
    label?: string;
    next_sleep_s?: number;
  }>;
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

function formatTimeLarge(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`;
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
  active: { label: 'ACTIVE', className: 'text-acid-green bg-acid-green/10 border-acid-green/30 animate-pulse' },
  completed: { label: 'DONE', className: 'text-chalk bg-chalk/10 border-chalk/30' },
  skipped: { label: 'SKIPPED', className: 'text-safety-red bg-safety-red/10 border-safety-red/30' },
};

/* ── Live Dashboard ───────────────────────────────────────────────── */

export default function LiveDashboardPage() {
  const params = useParams();
  const router = useRouter();
  const qc = useQueryClient();
  const raceId = params.id as string;

  /* client-side clock for elapsed/remaining */
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, []);

  /* poll live state every 2s */
  const { data: state, isLoading, error } = useQuery({
    queryKey: ['race-strategy', raceId, 'state'],
    queryFn: () => api.get<LiveState>(`/race-strategy/${raceId}/state`),
    refetchInterval: 2000,
  });

  /* ── mutations ──────────────────────────────────────────────────── */

  const endStintMut = useMutation({
    mutationFn: () => api.post<unknown>(`/race-strategy/${raceId}/end-stint`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['race-strategy', raceId, 'state'] }),
  });

  const reoptimizeMut = useMutation({
    mutationFn: () => api.post<unknown>(`/race-strategy/${raceId}/reoptimize`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['race-strategy', raceId, 'state'] }),
  });

  const wakeDriverMut = useMutation({
    mutationFn: (driverId: number) =>
      api.post<unknown>(`/race-strategy/${raceId}/wake-driver`, { driver_id: driverId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['race-strategy', raceId, 'state'] }),
  });

  const finishMut = useMutation({
    mutationFn: () => api.post<unknown>(`/race-strategy/${raceId}/finish`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['race-strategy'] });
      router.push(`/app/race-strategy/${raceId}/summary`);
    },
  });

  const [showSleepWarning, setShowSleepWarning] = useState(false);

  /* ── loading / error ────────────────────────────────────────────── */

  if (isLoading) {
    return <div className="text-steel font-body p-8 text-center">Connecting to live race...</div>;
  }

  if (error || !state) {
    return (
      <div className="text-safety-red font-body p-8 text-center">
        Failed to load live state.{' '}
        <Link href={`/app/race-strategy/${raceId}`} className="underline text-pit-orange">
          Back to race
        </Link>
      </div>
    );
  }

  /* redirect if race isn't live */
  if (state.race.status === 'finished') {
    router.replace(`/app/race-strategy/${raceId}/summary`);
    return null;
  }
  if (state.race.status !== 'live') {
    router.replace(`/app/race-strategy/${raceId}`);
    return null;
  }

  const { race, drivers, stints } = state;
  const driverColors = buildDriverColorMap(drivers);

  /* timer computations */
  const raceStartMs = race.race_start_ts ? new Date(race.race_start_ts).getTime() : 0;
  const elapsed = raceStartMs ? Math.max(0, Math.floor((now - raceStartMs) / 1000)) : 0;
  const remaining = Math.max(0, race.race_duration_s - elapsed);
  const progress = race.race_duration_s ? Math.min(1, elapsed / race.race_duration_s) : 0;

  /* progress bar color */
  const progressColor =
    progress >= 0.9 ? 'bg-safety-red' : progress >= 0.75 ? 'bg-marshal-yellow' : 'bg-acid-green';

  /* fuel info */
  const fuelModel = state.fuel_model as
    | { burn_rate_kg_s?: number; estimated_autonomy_s?: number }
    | undefined;
  const fuelKg = state.current_fuel_kg;
  const burnRate = fuelModel?.burn_rate_kg_s;
  const fuelAutonomy = fuelModel?.estimated_autonomy_s;

  /* active / next stint info */
  const activeStint = state.active_stint;
  const nextStint = state.next_stint;

  /* ── render ─────────────────────────────────────────────────────── */

  return (
    <div className="space-y-6">
      {/* Header */}
      <PageIntro
        title={race.race_name}
        subtitle="Live Race Dashboard"
        actions={
          <div className="flex items-center gap-2">
            <span className="inline-flex px-2 py-0.5 text-[10px] font-telemetry tracking-[0.12em] uppercase border text-acid-green bg-acid-green/10 border-acid-green/30 animate-pulse">
              LIVE
            </span>
            {state.is_neutralized && (
              <span className="inline-flex px-2 py-0.5 text-[10px] font-telemetry tracking-[0.12em] uppercase border text-marshal-yellow bg-marshal-yellow/10 border-marshal-yellow/30 animate-pulse">
                NEUTRALIZED
              </span>
            )}
          </div>
        }
      />

      {/* Race Timer */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <p className="text-steel font-telemetry text-xs uppercase tracking-wider mb-1">Elapsed</p>
            <p className="font-monument text-4xl text-chalk tabular-nums">{formatTimeLarge(elapsed)}</p>
          </div>
          <div className="text-right">
            <p className="text-steel font-telemetry text-xs uppercase tracking-wider mb-1">Remaining</p>
            <p className={`font-monument text-4xl tabular-nums ${remaining <= 300 ? 'text-safety-red' : 'text-chalk'}`}>
              {formatTimeLarge(remaining)}
            </p>
          </div>
        </div>
        <div className="w-full h-3 bg-asphalt rounded-full overflow-hidden">
          <div
            className={`h-full ${progressColor} transition-all duration-1000 ease-linear`}
            style={{ width: `${(progress * 100).toFixed(2)}%` }}
          />
        </div>
        <div className="flex justify-between mt-1">
          <span className="text-steel font-telemetry text-[10px]">0:00</span>
          <span className="text-steel font-telemetry text-[10px]">{formatTime(race.race_duration_s)}</span>
        </div>
      </div>

      {/* Fuel + Current/Next Driver */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Fuel Gauge */}
        <div className="bg-concrete rounded-lg border border-steel/20 p-4 space-y-3">
          <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Fuel</h3>
          <div className="space-y-2 text-sm font-body">
            <div className="flex justify-between">
              <span className="text-steel">Current</span>
              <span className="text-chalk font-monument text-lg">
                {fuelKg != null ? `${fuelKg.toFixed(1)} kg` : '\u2014'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-steel">Burn Rate</span>
              <span className="text-chalk">
                {burnRate != null ? `${(burnRate * 60).toFixed(2)} kg/min` : '\u2014'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-steel">Est. Autonomy</span>
              <span className={`${fuelAutonomy != null && fuelAutonomy < 300 ? 'text-safety-red' : 'text-chalk'}`}>
                {formatTime(fuelAutonomy != null ? Math.round(fuelAutonomy) : null)}
              </span>
            </div>
          </div>
        </div>

        {/* Current Driver */}
        <div
          className={`bg-concrete rounded-lg border-2 p-4 space-y-3${activeStint && state?.driver_sleep_status?.[activeStint.driver_id]?.sleeping ? ' opacity-50' : ''}`}
          style={{ borderColor: activeStint ? (driverColors[activeStint.driver_id] || '#888') : 'rgba(128,128,128,0.2)' }}
        >
          <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Current Driver</h3>
          {activeStint ? (
            <>
              <div className="flex items-center gap-3">
                <span
                  className="w-5 h-5 rounded-full shrink-0"
                  style={{ backgroundColor: driverColors[activeStint.driver_id] }}
                />
                <span className="font-monument text-2xl text-chalk">{activeStint.driver_name}</span>
              </div>
              {(() => {
                const driverObj = drivers.find((d) => d.id === activeStint.driver_id);
                return driverObj?.com_channel ? (
                  <span className="inline-flex px-2 py-0.5 text-[10px] font-telemetry tracking-wider uppercase border border-steel/30 text-steel">
                    COM {driverObj.com_channel}
                  </span>
                ) : null;
              })()}
              {(() => {
                const sleepStatus = state?.driver_sleep_status?.[activeStint.driver_id];
                if (!sleepStatus?.sleeping) return null;
                return (
                  <div className="flex items-center gap-2 mt-2 bg-asphalt/40 rounded-lg px-3 py-2">
                    <span className="text-lg">&#x1F319;</span>
                    <div className="flex-1">
                      <span className="text-sm text-steel">
                        Sleeping until {formatTime(sleepStatus.until_s)}
                      </span>
                      {sleepStatus.remaining_s != null && (
                        <span className="text-chalk text-sm ml-1">
                          ({formatTime(sleepStatus.remaining_s)} left)
                        </span>
                      )}
                    </div>
                    <button
                      onClick={() => wakeDriverMut.mutate(activeStint.driver_id)}
                      disabled={wakeDriverMut.isPending}
                      className="text-xs bg-acid-green/20 text-acid-green border border-acid-green/30 rounded px-2 py-1 hover:bg-acid-green/30 disabled:opacity-50"
                    >
                      Wake
                    </button>
                  </div>
                );
              })()}
              {/* stint progress */}
              {activeStint.planned_duration_s && activeStint.actual_start_s != null && (
                <div>
                  <div className="w-full h-2 bg-asphalt rounded-full overflow-hidden">
                    <div
                      className="h-full bg-acid-green transition-all duration-1000"
                      style={{
                        width: `${Math.min(100, ((elapsed - activeStint.actual_start_s) / activeStint.planned_duration_s) * 100).toFixed(1)}%`,
                      }}
                    />
                  </div>
                  <div className="flex justify-between mt-1 text-steel font-telemetry text-[10px]">
                    <span>{formatTime(Math.max(0, elapsed - activeStint.actual_start_s))}</span>
                    <span>{formatTime(activeStint.planned_duration_s)}</span>
                  </div>
                </div>
              )}
            </>
          ) : (
            <p className="text-steel font-body text-sm">No active stint</p>
          )}
        </div>

        {/* Next Driver */}
        <div className={`bg-concrete rounded-lg border border-steel/20 p-4 space-y-3${nextStint && state?.driver_sleep_status?.[nextStint.driver_id]?.sleeping ? ' opacity-50' : ''}`}>
          <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Next Driver</h3>
          {nextStint ? (
            <>
              <div className="flex items-center gap-3">
                <span
                  className="w-4 h-4 rounded-full shrink-0"
                  style={{ backgroundColor: driverColors[nextStint.driver_id] }}
                />
                <span className="font-monument text-lg text-chalk">{nextStint.driver_name}</span>
              </div>
              <div className="text-sm font-body text-steel">
                Planned: {formatTime(nextStint.planned_duration_s)}
              </div>
              {(() => {
                const sleepStatus = state?.driver_sleep_status?.[nextStint.driver_id];
                if (!sleepStatus?.sleeping) return null;
                return (
                  <div className="flex items-center gap-2 mt-2 bg-asphalt/40 rounded-lg px-3 py-2">
                    <span className="text-lg">&#x1F319;</span>
                    <div className="flex-1">
                      <span className="text-sm text-steel">
                        Sleeping until {formatTime(sleepStatus.until_s)}
                      </span>
                      {sleepStatus.remaining_s != null && (
                        <span className="text-chalk text-sm ml-1">
                          ({formatTime(sleepStatus.remaining_s)} left)
                        </span>
                      )}
                    </div>
                    <button
                      onClick={() => wakeDriverMut.mutate(nextStint.driver_id)}
                      disabled={wakeDriverMut.isPending}
                      className="text-xs bg-acid-green/20 text-acid-green border border-acid-green/30 rounded px-2 py-1 hover:bg-acid-green/30 disabled:opacity-50"
                    >
                      Wake
                    </button>
                  </div>
                );
              })()}
            </>
          ) : (
            <p className="text-steel font-body text-sm">No upcoming stint</p>
          )}
        </div>
      </div>

      {/* Stint Timeline */}
      <div className="space-y-2">
        <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Stint Timeline</h3>
        <StintTimeline
          stints={stints}
          totalDuration={race.race_duration_s}
          driverColors={driverColors}
          activeStintId={activeStint?.stint_id}
        />
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
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">#</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Driver</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Planned</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Actual</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Delta</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Status</th>
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
            </tbody>
          </table>
        </div>
      </div>

      {/* Pit Window Status */}
      {state.window_status && state.window_status.length > 0 && (
        <div className="space-y-2">
          <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Pit Windows</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
            {state.window_status.map((w, i) => {
              const wStatus = (w.status as string) || 'unknown';
              const statusClass =
                wStatus === 'open'
                  ? 'border-acid-green text-acid-green'
                  : wStatus === 'closed'
                    ? 'border-safety-red text-safety-red'
                    : 'border-marshal-yellow text-marshal-yellow';
              return (
                <div key={w.window_id ?? i} className={`bg-concrete rounded-lg border-2 p-4 ${statusClass}`}>
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-telemetry text-xs uppercase tracking-wider">
                      {w.label || `Window ${i + 1}`}
                    </span>
                    <span className="font-telemetry text-[10px] uppercase tracking-wider">
                      {wStatus.toUpperCase()}
                    </span>
                  </div>
                  <div className="text-steel font-body text-sm">
                    {formatTime(w.opens_at_s as number | null)} {'\u2014'} {formatTime(w.closes_at_s as number | null)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Team Messages ──────────────────────────────── */}
      {state.messages && state.messages.length > 0 && (
        <div className="bg-concrete/50 border border-steel/20 rounded-lg p-4">
          <h3 className="text-sm font-telemetry text-steel mb-3">TEAM MESSAGES</h3>
          <MessageLog messages={state.messages as Array<{ msg_id: number; author: string; message: string; category: string; created_at: string }>} />
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex items-center gap-3 flex-wrap pt-2 border-t border-steel/20">
        <button
          onClick={() => {
            if (state?.next_stint && state?.driver_sleep_status) {
              const nextDriverId = state.next_stint.driver_id;
              const sleepStatus = state.driver_sleep_status[nextDriverId];
              if (sleepStatus?.sleeping) {
                setShowSleepWarning(true);
                return;
              }
            }
            endStintMut.mutate();
          }}
          disabled={endStintMut.isPending || !activeStint}
          className="px-5 py-2.5 bg-pit-orange text-asphalt font-telemetry text-sm tracking-wider uppercase hover:bg-pit-orange/80 transition-colors disabled:opacity-50"
        >
          {endStintMut.isPending ? 'Ending Stint...' : 'End Stint'}
        </button>
        <button
          onClick={() => reoptimizeMut.mutate()}
          disabled={reoptimizeMut.isPending}
          className="px-4 py-2 bg-gold text-asphalt font-telemetry text-sm tracking-wider uppercase hover:bg-gold/80 transition-colors disabled:opacity-50"
        >
          {reoptimizeMut.isPending ? 'Re-Optimizing...' : 'Re-Optimize'}
        </button>
        <button
          onClick={() => {
            if (window.confirm('Finish the race? This will end the live session.')) {
              finishMut.mutate();
            }
          }}
          disabled={finishMut.isPending}
          className="px-4 py-2 border border-safety-red/40 text-safety-red font-telemetry text-sm tracking-wider uppercase hover:bg-safety-red/10 transition-colors disabled:opacity-50"
        >
          {finishMut.isPending ? 'Finishing...' : 'Finish Race'}
        </button>
        <Link
          href={`/app/race-strategy/${raceId}`}
          className="px-4 py-2 border border-steel/30 text-chalk font-telemetry text-sm tracking-wider uppercase hover:bg-concrete transition-colors ml-auto"
        >
          View Config
        </Link>
      </div>

      {/* Sleep Warning Dialog */}
      {showSleepWarning && state?.next_stint && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-graphite border border-steel/30 rounded-xl p-6 max-w-md mx-4">
            <h3 className="text-chalk text-lg font-semibold mb-2">Driver is sleeping</h3>
            <p className="text-steel text-sm mb-4">
              {state.next_stint.driver_name} is currently in a sleep window
              until {formatTime(state.driver_sleep_status?.[state.next_stint.driver_id]?.until_s)}.
              {' '}Are you sure you want to assign them to the next stint?
            </p>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setShowSleepWarning(false)}
                className="px-4 py-2 text-sm text-steel border border-steel/30 rounded-lg hover:bg-steel/10">
                Cancel
              </button>
              <button onClick={() => { setShowSleepWarning(false); endStintMut.mutate(); }}
                className="px-4 py-2 text-sm bg-safety-red/20 text-safety-red border border-safety-red/30 rounded-lg hover:bg-safety-red/30">
                Assign Anyway
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
