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
  paused_at_ts: string | null;
  total_paused_s: number;
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
  min_cumulative_s: number | null;
  max_cumulative_s: number | null;
  avg_lap_time_s: number | null;
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
  actual_laps: number | null;
  status: 'planned' | 'active' | 'completed' | 'skipped';
}

interface Penalty {
  id: number;
  stint_order: number | null;
  elapsed_s: number;
  penalty_type: string;
  laps_deducted: number;
  passage_duration_s: number | null;
  reason: string | null;
  cleared: boolean;
  cleared_at_s: number | null;
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
  in_pit: boolean;
  pit_elapsed_s: number;
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
  penalties?: Penalty[];
  active_passage?: { id: number; passage_duration_s: number } | null;
  total_penalty_laps?: number;
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

  /* poll live state every 2s */
  const { data: state, isLoading, error } = useQuery({
    queryKey: ['race-strategy', raceId, 'state'],
    queryFn: () => api.get<LiveState>(`/race-strategy/${raceId}/state`),
    refetchInterval: 2000,
  });

  /* ── mutations ──────────────────────────────────────────────────── */

  const pitInMut = useMutation({
    mutationFn: (vars?: { actual_laps?: number }) => api.post<unknown>(`/race-strategy/${raceId}/pit-in`, vars ?? {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['race-strategy', raceId, 'state'] }),
  });

  const pitOutMut = useMutation({
    mutationFn: (vars?: { kart_number?: string }) => api.post<unknown>(`/race-strategy/${raceId}/pit-out`, vars ?? {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['race-strategy', raceId, 'state'] }),
  });

  const reoptimizeMut = useMutation({
    mutationFn: (vars?: { wet_lap_time_s?: number; rain_duration_min?: number }) =>
      api.post<unknown>(`/race-strategy/${raceId}/reoptimize`, vars ?? {}),
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

  const pauseMut = useMutation({
    mutationFn: () => api.post<unknown>(`/race-strategy/${raceId}/pause`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['race-strategy', raceId, 'state'] }),
  });

  const resumeMut = useMutation({
    mutationFn: () => api.post<unknown>(`/race-strategy/${raceId}/resume`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['race-strategy', raceId, 'state'] }),
  });

  const setConditionMut = useMutation({
    mutationFn: (condition: string) => api.post<unknown>(`/race-strategy/${raceId}/condition`, { condition }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['race-strategy', raceId, 'state'] }),
  });

  /* ── tech stop mutations ─────────────────────────────────────────── */

  const techStopInMut = useMutation({
    mutationFn: () => api.post<unknown>(`/race-strategy/${raceId}/tech-stop-in`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['race-strategy', raceId, 'state'] }),
  });

  const techStopOutMut = useMutation({
    mutationFn: () => api.post<unknown>(`/race-strategy/${raceId}/tech-stop-out`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['race-strategy', raceId, 'state'] }),
  });

  /* ── penalty mutations ───────────────────────────────────────────── */

  const addPenaltyMut = useMutation({
    mutationFn: (vars: { penalty_type: string; laps_deducted: number; reason: string; passage_duration_s?: number }) =>
      api.post<unknown>(`/race-strategy/${raceId}/penalty`, vars),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['race-strategy', raceId, 'state'] }),
  });

  const clearPenaltyMut = useMutation({
    mutationFn: (penaltyId: number) =>
      api.post<unknown>(`/race-strategy/${raceId}/penalty/${penaltyId}/clear`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['race-strategy', raceId, 'state'] }),
  });

  const [applyingStrategy, setApplyingStrategy] = useState<string | null>(null);

  /* client-side clock — stops ticking when paused */
  const [now, setNow] = useState(Date.now());
  const paused = !!(state?.race?.paused_at_ts);
  useEffect(() => {
    if (paused) return;
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [paused]);

  const [showConditionMenu, setShowConditionMenu] = useState(false);
  // Rain scenario input
  const [rainInput, setRainInput] = useState<{ wetLapTime: string; durationMin: string } | null>(null);
  const [rainScenarios, setRainScenarios] = useState<Array<{
    name: string; description: string; approach: string; score: number;
    stints: Array<{ stint_order: number; driver_id: number; driver_name: string; start_s: number; duration_s: number }>;
    metrics: {
      pits_in_rain: number; pits_in_dry: number; rain_drive_s: number; dry_drive_s: number;
      driver_transitions: number; min_stint_s: number; max_stint_s: number;
      flexibility_score: number; risk_score: number; total_pit_s: number;
    };
  }> | null>(null);
  const [loadingStrategies, setLoadingStrategies] = useState(false);
  const [strategyError, setStrategyError] = useState<string | null>(null);
  const [showSleepWarning, setShowSleepWarning] = useState(false);
  const [showPitInForm, setShowPitInForm] = useState(false);
  const [pitInLaps, setPitInLaps] = useState('');
  const [showFinishConfirm, setShowFinishConfirm] = useState(false);

  // Tech stop local tracking
  const [isTechStop, setIsTechStop] = useState(false);

  // Quick change kart number
  const [kartNumber, setKartNumber] = useState('');

  // Penalty form
  const [showPenaltyForm, setShowPenaltyForm] = useState(false);
  const [penaltyType, setPenaltyType] = useState('lap_deduction');
  const [penaltyReason, setPenaltyReason] = useState('');
  const [penaltyLaps, setPenaltyLaps] = useState('1');
  const [penaltyPassageDuration, setPenaltyPassageDuration] = useState('150');

  // Collapsible sections
  const [showKartHistory, setShowKartHistory] = useState(false);
  const [showPenaltyLog, setShowPenaltyLog] = useState(false);

  /* ── loading / error ────────────────────────────────────────────── */

  if (isLoading) {
    return <div className="text-steel font-body p-8 text-center">Connecting to live race...</div>;
  }

  if (error || !state) {
    return (
      <div className="text-safety-red font-body p-8 text-center">
        Failed to load live state.{' '}
        <Link href={`/app/race-strategy/${raceId}`} className="underline text-gold">
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
  const totalPausedS = race.total_paused_s || 0;
  const isPaused = !!race.paused_at_ts;
  const elapsed = (() => {
    if (!raceStartMs) return 0;
    if (isPaused && race.paused_at_ts) {
      const pausedAtMs = new Date(race.paused_at_ts).getTime();
      return Math.max(0, Math.floor((pausedAtMs - raceStartMs) / 1000) - totalPausedS);
    }
    return Math.max(0, Math.floor((now - raceStartMs) / 1000) - totalPausedS);
  })();
  const remaining = Math.max(0, race.race_duration_s - elapsed);

  // Helper: estimate laps for a stint based on driver avg lap time
  function estLaps(s: Stint): number | null {
    if (s.actual_laps != null) return s.actual_laps;
    const d = drivers.find((dr) => dr.id === s.driver_id);
    const avg = d?.avg_lap_time_s;
    if (!avg || avg <= 0) return null;
    const dur = s.actual_duration_s ?? s.planned_duration_s ?? 0;
    return Math.floor(dur / avg);
  }

  // Cumulative actual laps up to (and including) a stint order
  function cumulativeLaps(upTo: number): number {
    return stints
      .filter((s) => s.stint_order <= upTo)
      .reduce((sum, s) => sum + (estLaps(s) ?? 0), 0);
  }
  const progress = race.race_duration_s ? Math.min(1, elapsed / race.race_duration_s) : 0;

  /* blackout window detection */
  const blackoutStartS = (race as Record<string, unknown>).blackout_start_min ? Number((race as Record<string, unknown>).blackout_start_min) * 60 : 0;
  const blackoutEndS = (race as Record<string, unknown>).blackout_end_min ? Number((race as Record<string, unknown>).blackout_end_min) * 60 : 0;
  const inBlackoutStart = blackoutStartS > 0 && elapsed < blackoutStartS;
  const inBlackoutEnd = blackoutEndS > 0 && elapsed > (race.race_duration_s - blackoutEndS);
  const inBlackout = inBlackoutStart || inBlackoutEnd;

  /* quick change enabled */
  const quickChangeEnabled = !!(race as Record<string, unknown>).quick_change_enabled;

  /* progress bar color */
  const progressColor =
    progress >= 0.9 ? 'bg-safety-red' : progress >= 0.75 ? 'bg-marshal-yellow' : 'bg-acid-green';

  /* fuel info */
  const fuelModel = state.fuel_model as
    | { burn_rate_kgs?: number; fuel_autonomy_s?: number; full_tank_kg?: number }
    | undefined;
  const fuelKg = state.current_fuel_kg;
  const burnRate = fuelModel?.burn_rate_kgs;
  const fuelAutonomy = fuelModel?.fuel_autonomy_s;

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
            {race.paused_at_ts && (
              <span className="inline-flex px-2 py-0.5 text-[10px] font-telemetry tracking-[0.12em] uppercase border text-marshal-yellow bg-marshal-yellow/10 border-marshal-yellow/30 animate-pulse">
                PAUSED
              </span>
            )}
            {/* Weather badge — hidden for V2 redesign */}
          </div>
        }
      />

      {/* Blackout Warning */}
      {inBlackout && (
        <div className="bg-safety-red/10 border border-safety-red/30 rounded-lg px-4 py-2 text-safety-red font-telemetry text-xs uppercase tracking-wider animate-pulse">
          Blackout period — 20-lap penalty if you pit now
          {inBlackoutStart && ` (${formatTime(blackoutStartS - elapsed)} until open)`}
          {inBlackoutEnd && ` (race ends in ${formatTime(race.race_duration_s - elapsed)})`}
        </div>
      )}

      {/* Active Penalty Passage Banner */}
      {state.active_passage && (
        <div className="bg-safety-red/10 border-2 border-safety-red/30 rounded-lg px-4 py-3 animate-pulse">
          <div className="flex items-center justify-between">
            <span className="text-safety-red font-telemetry text-sm uppercase">
              PENALTY: {state.active_passage.passage_duration_s}s passage required
            </span>
            <button
              type="button"
              onClick={() => clearPenaltyMut.mutate(state.active_passage!.id)}
              disabled={clearPenaltyMut.isPending}
              className="px-3 py-1 bg-safety-red/20 text-safety-red border border-safety-red/30 text-xs font-telemetry uppercase hover:bg-safety-red/30 transition-colors disabled:opacity-50"
            >
              Mark Served
            </button>
          </div>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex items-center gap-3 flex-wrap">
        <Link
          href={`/app/race-strategy/${raceId}`}
          className="px-4 py-2 border border-steel/30 text-chalk font-telemetry text-sm tracking-wider uppercase hover:bg-concrete transition-colors"
        >
          View Config
        </Link>
        {state.in_pit ? (
          isTechStop ? (
            <div className="flex items-center gap-3 bg-marshal-yellow/10 border border-marshal-yellow/30 rounded-lg px-4 py-3">
              <div className="flex-1">
                <p className="text-marshal-yellow font-telemetry text-sm uppercase tracking-wider">Tech Stop</p>
                <p className="text-steel font-body text-xs mt-0.5">No driver change. No refueling.</p>
                <p className="text-chalk font-monument text-2xl tabular-nums mt-1">{formatTimeLarge(state.pit_elapsed_s)}</p>
              </div>
              <button
                type="button"
                onClick={() => { techStopOutMut.mutate(); setIsTechStop(false); }}
                disabled={techStopOutMut.isPending}
                className="px-5 py-2.5 bg-gold text-white font-telemetry text-sm tracking-wider uppercase hover:bg-gold/80 transition-colors disabled:opacity-50"
              >
                {techStopOutMut.isPending ? 'Resuming...' : 'Resume'}
              </button>
            </div>
          ) : quickChangeEnabled ? (
            <div className="flex items-center gap-2 bg-acid-green/10 border border-acid-green/30 rounded-lg px-4 py-2">
              <span className="text-chalk font-body text-sm">Kart #:</span>
              <input
                type="text"
                value={kartNumber}
                onChange={(e) => setKartNumber(e.target.value)}
                placeholder="e.g. 42"
                className="w-20 bg-asphalt border border-steel/20 rounded px-2 py-1 text-chalk text-sm font-telemetry"
              />
              <button
                type="button"
                onClick={() => { pitOutMut.mutate(kartNumber ? { kart_number: kartNumber } : undefined); setKartNumber(''); }}
                disabled={pitOutMut.isPending}
                className="px-5 py-2.5 bg-acid-green text-asphalt font-telemetry text-sm tracking-wider uppercase hover:bg-acid-green/80 transition-colors disabled:opacity-50 animate-pulse"
              >
                {pitOutMut.isPending ? 'Sending Out...' : 'Pit Out'}
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => pitOutMut.mutate()}
              disabled={pitOutMut.isPending}
              className="px-5 py-2.5 bg-acid-green text-asphalt font-telemetry text-sm tracking-wider uppercase hover:bg-acid-green/80 transition-colors disabled:opacity-50 animate-pulse"
            >
              {pitOutMut.isPending ? 'Sending Out...' : 'Pit Out'}
            </button>
          )
        ) : showPitInForm ? (
          <div className="flex items-center gap-2 bg-gold/10 border border-gold/30 rounded-lg px-4 py-2">
            <span className="text-chalk font-body text-sm">Total laps:</span>
            <input
              type="number"
              value={pitInLaps}
              onChange={(e) => setPitInLaps(e.target.value)}
              placeholder="e.g. 32"
              className="w-20 bg-asphalt border border-steel/20 rounded px-2 py-1 text-chalk text-sm font-telemetry"
              autoFocus
            />
            <button
              type="button"
              onClick={() => {
                const laps = pitInLaps.trim() ? parseInt(pitInLaps.trim(), 10) : undefined;
                pitInMut.mutate(laps != null && !isNaN(laps) ? { actual_laps: laps } : undefined);
                setShowPitInForm(false);
                setPitInLaps('');
              }}
              disabled={pitInMut.isPending}
              className="px-3 py-1 bg-gold text-white font-telemetry text-xs uppercase hover:bg-gold/80 transition-colors disabled:opacity-50"
            >
              {pitInMut.isPending ? 'Pitting...' : 'Confirm Pit In'}
            </button>
            <button type="button" onClick={() => { setShowPitInForm(false); setPitInLaps(''); }} className="px-3 py-1 border border-steel/30 text-steel font-telemetry text-xs uppercase hover:text-chalk transition-colors">
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setShowPitInForm(true)}
            disabled={pitInMut.isPending || !activeStint}
            className="px-5 py-2.5 bg-gold text-white font-telemetry text-sm tracking-wider uppercase hover:bg-gold/80 transition-colors disabled:opacity-50"
          >
            Pit In
          </button>
        )}
        <button
          type="button"
          onClick={() => reoptimizeMut.mutate()}
          disabled={reoptimizeMut.isPending}
          className="px-4 py-2 bg-gold text-white font-telemetry text-sm tracking-wider uppercase hover:bg-gold/80 transition-colors disabled:opacity-50"
        >
          {reoptimizeMut.isPending ? 'Re-Optimizing...' : 'Re-Optimize'}
        </button>
        {race.paused_at_ts ? (
          <button
            type="button"
            onClick={() => resumeMut.mutate()}
            disabled={resumeMut.isPending}
            className="px-4 py-2 bg-acid-green text-asphalt font-telemetry text-sm tracking-wider uppercase hover:bg-acid-green/80 transition-colors disabled:opacity-50 animate-pulse"
          >
            {resumeMut.isPending ? 'Resuming...' : 'Resume'}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => pauseMut.mutate()}
            disabled={pauseMut.isPending}
            className="px-4 py-2 bg-gold text-white font-telemetry text-sm tracking-wider uppercase hover:bg-gold/80 transition-colors disabled:opacity-50"
          >
            {pauseMut.isPending ? 'Pausing...' : 'Pause'}
          </button>
        )}
        {/* Track Condition — moved to weather panel below */}
        {/* Tech Stop Button */}
        {!state.in_pit && (race as Record<string, unknown>).tech_stop_enabled && (
          <button
            type="button"
            onClick={() => { techStopInMut.mutate(); setIsTechStop(true); }}
            disabled={techStopInMut.isPending}
            className="px-4 py-2 bg-gold text-white font-telemetry text-sm tracking-wider uppercase hover:bg-gold/80 transition-colors disabled:opacity-50"
          >
            {techStopInMut.isPending ? 'Stopping...' : 'Tech Stop'}
          </button>
        )}
        {/* Penalty Button / Form */}
        {showPenaltyForm ? (
          <div className="flex items-center gap-2 bg-safety-red/10 border border-safety-red/30 rounded-lg px-4 py-2 flex-wrap">
            <select
              value={penaltyType}
              onChange={(e) => setPenaltyType(e.target.value)}
              className="bg-asphalt border border-steel/20 rounded px-2 py-1 text-chalk text-xs font-telemetry"
            >
              <option value="lap_deduction">Lap deduction</option>
              <option value="pit_passage">Pit passage</option>
              <option value="driver_exclusion">Driver exclusion</option>
            </select>
            <input
              type="text"
              value={penaltyReason}
              onChange={(e) => setPenaltyReason(e.target.value)}
              placeholder="Reason"
              className="w-32 bg-asphalt border border-steel/20 rounded px-2 py-1 text-chalk text-xs font-telemetry"
            />
            <input
              type="number"
              value={penaltyLaps}
              onChange={(e) => setPenaltyLaps(e.target.value)}
              placeholder="Laps"
              className="w-16 bg-asphalt border border-steel/20 rounded px-2 py-1 text-chalk text-xs font-telemetry"
              min="0"
            />
            {penaltyType === 'pit_passage' && (
              <input
                type="number"
                value={penaltyPassageDuration}
                onChange={(e) => setPenaltyPassageDuration(e.target.value)}
                placeholder="Duration (s)"
                className="w-24 bg-asphalt border border-steel/20 rounded px-2 py-1 text-chalk text-xs font-telemetry"
                min="0"
              />
            )}
            <button
              type="button"
              onClick={() => {
                addPenaltyMut.mutate({
                  penalty_type: penaltyType,
                  laps_deducted: parseInt(penaltyLaps) || 0,
                  reason: penaltyReason,
                  ...(penaltyType === 'pit_passage' ? { passage_duration_s: parseInt(penaltyPassageDuration) || 150 } : {}),
                });
                setShowPenaltyForm(false);
                setPenaltyReason('');
                setPenaltyLaps('1');
              }}
              disabled={addPenaltyMut.isPending}
              className="px-3 py-1 bg-safety-red text-white font-telemetry text-xs uppercase hover:bg-safety-red/80 transition-colors disabled:opacity-50"
            >
              {addPenaltyMut.isPending ? 'Adding...' : 'Confirm'}
            </button>
            <button
              type="button"
              onClick={() => setShowPenaltyForm(false)}
              className="px-3 py-1 border border-steel/30 text-steel font-telemetry text-xs uppercase hover:text-chalk transition-colors"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setShowPenaltyForm(true)}
            className="px-4 py-2 border border-safety-red/40 text-safety-red font-telemetry text-sm tracking-wider uppercase hover:bg-safety-red/10 transition-colors"
          >
            Penalty
          </button>
        )}
        {showFinishConfirm ? (
          <div className="flex items-center gap-2 bg-safety-red/10 border border-safety-red/30 rounded-lg px-4 py-2">
            <span className="text-chalk font-body text-sm">End the race?</span>
            <button type="button" onClick={() => { finishMut.mutate(); setShowFinishConfirm(false); }} disabled={finishMut.isPending} className="px-3 py-1 bg-safety-red text-white font-telemetry text-xs uppercase hover:bg-safety-red/80 transition-colors disabled:opacity-50">
              {finishMut.isPending ? 'Finishing...' : 'Confirm'}
            </button>
            <button type="button" onClick={() => setShowFinishConfirm(false)} className="px-3 py-1 border border-steel/30 text-steel font-telemetry text-xs uppercase hover:text-chalk transition-colors">
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setShowFinishConfirm(true)}
            disabled={finishMut.isPending}
            className="px-4 py-2 border border-safety-red/40 text-safety-red font-telemetry text-sm tracking-wider uppercase hover:bg-safety-red/10 transition-colors disabled:opacity-50"
          >
            Finish Race
          </button>
        )}
      </div>

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

        {/* In Pit Panel */}
        {state.in_pit && nextStint && (
          <div className="bg-concrete rounded-lg border-2 border-gold p-4 space-y-4 col-span-full">
            <div className="flex items-center gap-3">
              <h3 className="font-telemetry text-xs text-gold uppercase tracking-wider animate-pulse">In Pit</h3>
              <span className="font-monument text-3xl text-gold tabular-nums">{formatTimeLarge(state.pit_elapsed_s)}</span>
            </div>
            {(() => {
              const nextDriver = drivers.find((d) => d.id === nextStint.driver_id);
              return (
                <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm font-body">
                  <div className="text-steel">Next Driver</div>
                  <div className="text-chalk font-telemetry font-medium">{nextStint.driver_name}</div>
                  <div className="text-steel">Weight</div>
                  <div className="text-chalk font-telemetry">{nextDriver?.weight_kg ?? '\u2014'} kg</div>
                  <div className="text-steel">Ballast</div>
                  <div className="text-marshal-yellow font-telemetry">{nextStint.ballast_kg ?? 0} kg</div>
                  <div className="text-steel">Planned Stint</div>
                  <div className="text-chalk font-telemetry">{formatTime(nextStint.planned_duration_s)}</div>
                </div>
              );
            })()}
          </div>
        )}

        {/* Current Driver */}
        <div
          className={`bg-concrete rounded-lg border-2 p-4 space-y-4${activeStint && state?.driver_sleep_status?.[activeStint.driver_id]?.sleeping ? ' opacity-50' : ''}`}
          style={{ borderColor: activeStint ? (driverColors[activeStint.driver_id] || '#888') : 'rgba(128,128,128,0.2)' }}
        >
          <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Current Driver</h3>
          {activeStint ? (
            (() => {
              const driverObj = drivers.find((d) => d.id === activeStint.driver_id);
              const stintElapsed = activeStint.actual_start_s != null ? Math.max(0, elapsed - activeStint.actual_start_s) : 0;
              const stintRemaining = Math.max(0, (activeStint.planned_duration_s ?? 0) - stintElapsed);
              const stintEndEst = new Date(Date.now() + stintRemaining * 1000);
              const driverTotalDrive = stints
                .filter((s) => s.driver_id === activeStint.driver_id)
                .reduce((sum, s) => {
                  if (s.status === 'completed') return sum + (s.actual_duration_s ?? 0);
                  if (s.status === 'active' && s.actual_start_s != null) return sum + Math.max(0, elapsed - s.actual_start_s);
                  return sum;
                }, 0);
              const avg = driverObj?.avg_lap_time_s;
              let pitLap: number | null = null;
              if (avg && avg > 0 && activeStint.planned_duration_s) {
                const prevLaps = stints
                  .filter((s) => s.stint_order < activeStint.stint_order)
                  .reduce((sum, s) => {
                    const dr = drivers.find((dd) => dd.id === s.driver_id);
                    return sum + (dr?.avg_lap_time_s ? Math.floor((s.actual_duration_s ?? s.planned_duration_s ?? 0) / dr.avg_lap_time_s) : 0);
                  }, 0);
                pitLap = prevLaps + Math.floor(activeStint.planned_duration_s / avg);
              }
              return (
                <>
                  <div className="flex items-center gap-3">
                    <span className="w-5 h-5 rounded-full shrink-0" style={{ backgroundColor: driverColors[activeStint.driver_id] }} />
                    <span className="font-monument text-2xl text-chalk">{activeStint.driver_name}</span>
                    {driverObj?.com_channel && (
                      <span className="inline-flex px-2 py-0.5 text-[10px] font-telemetry tracking-[0.12em] uppercase border border-steel/30 text-steel">
                        COM {driverObj.com_channel}
                      </span>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm font-body">
                    <div className="text-steel">Weight</div>
                    <div className="text-chalk font-telemetry">{driverObj?.weight_kg ?? '\u2014'} kg</div>
                    <div className="text-steel">Ballast</div>
                    <div className="text-marshal-yellow font-telemetry">{activeStint.ballast_kg ?? 0} kg</div>
                    <div className="text-steel">Stint Elapsed</div>
                    <div className="text-chalk font-telemetry">{formatTime(stintElapsed)}</div>
                    <div className="text-steel">Stint Remaining</div>
                    <div className="text-chalk font-telemetry">{formatTime(stintRemaining)}</div>
                    <div className="text-steel">Est. Stint End</div>
                    <div className="text-chalk font-telemetry">{stintEndEst.toLocaleTimeString()}</div>
                    <div className="text-steel">Driver Total</div>
                    <div className="text-chalk font-telemetry">{formatTime(Math.round(driverTotalDrive))}</div>
                    {pitLap != null && (<>
                      <div className="text-steel">Expected Pit Lap</div>
                      <div className="text-gold font-telemetry">{pitLap}</div>
                    </>)}
                  </div>
                  {/* stint progress bar */}
                  {activeStint.planned_duration_s && activeStint.actual_start_s != null && (
                    <div>
                      <div className="w-full h-2 bg-asphalt rounded-full overflow-hidden">
                        <div
                          className="h-full bg-acid-green transition-all duration-1000"
                          style={{ width: `${Math.min(100, (stintElapsed / activeStint.planned_duration_s) * 100).toFixed(1)}%` }}
                        />
                      </div>
                      <div className="flex justify-between mt-1 text-steel font-telemetry text-[10px]">
                        <span>{formatTime(stintElapsed)}</span>
                        <span>{formatTime(activeStint.planned_duration_s)}</span>
                      </div>
                    </div>
                  )}
                </>
              );
            })()
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
              {(() => {
                const driverObj = drivers.find((d) => d.id === nextStint.driver_id);
                const pitIdx = stints.findIndex((s) => s.stint_id === nextStint.stint_id);
                const ps = pitIdx > 0 ? (state.pit_stops as Array<Record<string, unknown>>)?.[pitIdx - 1] : null;
                const refueled = ps?.refueled;
                return (
                  <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm font-body">
                    <div className="text-steel">Planned</div>
                    <div className="text-chalk font-telemetry">{formatTime(nextStint.planned_duration_s)}</div>
                    <div className="text-steel">Weight</div>
                    <div className="text-chalk font-telemetry">{driverObj?.weight_kg ?? '\u2014'} kg</div>
                    <div className="text-steel">Ballast</div>
                    <div className="text-marshal-yellow font-telemetry">{nextStint.ballast_kg ?? 0} kg</div>
                    <div className="text-steel">Refuel</div>
                    <div className={`font-telemetry ${refueled ? 'text-acid-green' : 'text-steel'}`}>{refueled ? 'Yes' : 'No'}</div>
                  </div>
                );
              })()}
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
                      type="button"
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

      {/* Weather Panel — hidden for V2 redesign */}
      {false && (() => {
        const weatherWindows = (state.weather_windows ?? []) as Array<{
          start_s: number; end_s: number; condition: string; confidence_pct: number;
        }>;
        const currentCondition = (race as any).current_condition || 'dry';
        const hasWeather = weatherWindows.length > 0 || currentCondition !== 'dry';

        // Always show weather panel

        // Find next weather transition
        const nextTransition = weatherWindows.find(w => w.start_s > elapsed);
        const currentForecast = weatherWindows.find(w => w.start_s <= elapsed && w.end_s > elapsed);
        const forecastCondition = currentForecast?.condition || 'dry';
        const conditionMismatch = currentCondition !== forecastCondition && currentForecast;

        // Best driver for wet conditions (by wet_confidence)
        const bestForNext = [...drivers].sort((a, b) => (b.wet_confidence || 0) - (a.wet_confidence || 0))[0];

        const conditionColors: Record<string, string> = {
          dry: 'bg-steel/30',
          damp: 'bg-marshal-yellow/40',
          wet: 'bg-marshal-yellow/70',
        };

        return (
          <div className="bg-concrete rounded-lg border border-steel/20 p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Weather</h3>
              <div className="flex items-center gap-2">
                {['dry', 'damp', 'wet'].map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setConditionMut.mutate(c)}
                    className={`px-3 py-1 rounded text-xs font-telemetry uppercase transition-colors ${
                      currentCondition === c
                        ? 'bg-gold text-white'
                        : 'text-steel border border-steel/20 hover:text-chalk'
                    }`}
                  >{c}</button>
                ))}
              </div>
            </div>

            {/* Weather Timeline */}
            {weatherWindows.length > 0 && (
              <div className="relative">
                <div className="w-full h-6 bg-asphalt rounded-full overflow-hidden flex">
                  {/* Dry segments fill gaps */}
                  {(() => {
                    const segments: Array<{ start: number; end: number; condition: string; confidence: number }> = [];
                    let cursor = 0;
                    for (const w of weatherWindows.sort((a, b) => a.start_s - b.start_s)) {
                      if (w.start_s > cursor) {
                        segments.push({ start: cursor, end: w.start_s, condition: 'dry', confidence: 100 });
                      }
                      segments.push({ start: w.start_s, end: w.end_s, condition: w.condition, confidence: w.confidence_pct });
                      cursor = w.end_s;
                    }
                    if (cursor < race.race_duration_s) {
                      segments.push({ start: cursor, end: race.race_duration_s, condition: 'dry', confidence: 100 });
                    }
                    return segments.map((seg, idx) => {
                      const pct = ((seg.end - seg.start) / race.race_duration_s) * 100;
                      return (
                        <div
                          key={idx}
                          className={`h-full ${conditionColors[seg.condition] || 'bg-steel/30'} border-r border-asphalt/50`}
                          style={{ width: `${pct}%`, opacity: seg.confidence / 100 }}
                          title={`${seg.condition} (${seg.confidence}%) — ${formatTime(seg.start)}→${formatTime(seg.end)}`}
                        />
                      );
                    });
                  })()}
                </div>
                {/* Current position marker */}
                <div
                  className="absolute top-0 w-0.5 h-6 bg-acid-green"
                  style={{ left: `${Math.min(100, (elapsed / race.race_duration_s) * 100)}%` }}
                />
              </div>
            )}

            {/* Condition mismatch warning */}
            {conditionMismatch && (
              <div className="flex items-center gap-3 bg-marshal-yellow/10 border border-marshal-yellow/30 rounded-lg px-4 py-2">
                <span className="text-marshal-yellow font-telemetry text-xs uppercase">
                  Forecast: {forecastCondition} — Actual: {currentCondition}
                </span>
                <button
                  type="button"
                  onClick={() => reoptimizeMut.mutate()}
                  disabled={reoptimizeMut.isPending}
                  className="px-3 py-1 bg-gold text-white font-telemetry text-xs uppercase rounded hover:bg-gold/80 transition-colors disabled:opacity-50 ml-auto"
                >
                  Re-optimize
                </button>
              </div>
            )}

            {/* Info row: next change + recommended driver */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1">
                <p className="text-steel font-telemetry text-[10px] uppercase tracking-wider">Next Forecast Change</p>
                {nextTransition ? (
                  <>
                    <p className="text-chalk font-telemetry text-sm">
                      {nextTransition.condition.toUpperCase()} in {formatTime(nextTransition.start_s - elapsed)}
                    </p>
                    <p className="text-steel font-body text-xs">{nextTransition.confidence_pct}% confidence</p>
                  </>
                ) : (
                  <p className="text-steel font-body text-xs">No change expected</p>
                )}
              </div>
              <div className="space-y-1">
                <p className="text-steel font-telemetry text-[10px] uppercase tracking-wider">Best Wet Driver</p>
                {bestForNext && (
                  <div className="flex items-center gap-2">
                    <span className="w-3 h-3 rounded-full" style={{ backgroundColor: driverColors[bestForNext.id] }} />
                    <span className="text-chalk font-telemetry text-sm">{bestForNext.driver_name}</span>
                    <span className="text-marshal-yellow font-telemetry text-xs">
                      {Math.round((bestForNext.wet_confidence || 0.5) * 100)}% confidence
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Rain scenario input — shown when condition is wet or damp */}
            {currentCondition !== 'dry' && !rainScenarios && (
              <div className="bg-marshal-yellow/5 border border-marshal-yellow/20 rounded-lg p-4 space-y-3">
                <p className="text-marshal-yellow font-telemetry text-xs uppercase tracking-wider">
                  Rain detected — enter conditions for strategy scenarios
                </p>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-steel font-telemetry text-[10px] uppercase tracking-wider block mb-1">Current wet lap time (s)</label>
                    <input
                      type="number"
                      value={rainInput?.wetLapTime || ''}
                      onChange={(e) => setRainInput(prev => ({ wetLapTime: e.target.value, durationMin: prev?.durationMin || '' }))}
                      placeholder="e.g. 85"
                      className="bg-asphalt border border-steel/20 rounded px-3 py-2 text-chalk font-telemetry text-sm w-full"
                      step="0.1"
                    />
                  </div>
                  <div>
                    <label className="text-steel font-telemetry text-[10px] uppercase tracking-wider block mb-1">Expected rain duration (min)</label>
                    <input
                      type="number"
                      value={rainInput?.durationMin || ''}
                      onChange={(e) => setRainInput(prev => ({ wetLapTime: prev?.wetLapTime || '', durationMin: e.target.value }))}
                      placeholder="e.g. 45"
                      className="bg-asphalt border border-steel/20 rounded px-3 py-2 text-chalk font-telemetry text-sm w-full"
                      min="1"
                    />
                  </div>
                </div>
                <button
                  type="button"
                  onClick={async () => {
                    const wetLap = parseFloat(rainInput?.wetLapTime || '0');
                    const durMin = parseInt(rainInput?.durationMin || '0');
                    if (!wetLap || !durMin) return;
                    setLoadingStrategies(true);
                    setStrategyError(null);
                    try {
                      const data = await api.post<{ strategies: typeof rainScenarios }>(`/race-strategy/${raceId}/strategies`, {
                        wet_lap_time_s: wetLap,
                        rain_duration_min: durMin,
                      });
                      const strategies = (data as any).strategies ?? data;
                      if (!strategies || (Array.isArray(strategies) && strategies.length === 0)) {
                        setStrategyError('No viable strategies found — all 7 approaches were infeasible for current race state.');
                        setRainScenarios(null);
                      } else {
                        setRainScenarios(strategies);
                      }
                    } catch (err) {
                      console.error('Strategy generation failed:', err);
                      setStrategyError(`Strategy generation failed: ${err instanceof Error ? err.message : String(err)}`);
                    } finally {
                      setLoadingStrategies(false);
                    }
                  }}
                  disabled={!rainInput?.wetLapTime || !rainInput?.durationMin || loadingStrategies}
                  className="px-4 py-2 bg-gold text-white font-telemetry text-xs uppercase tracking-wider rounded hover:bg-gold/80 transition-colors disabled:opacity-30"
                >
                  {loadingStrategies ? 'Computing 7 strategies...' : 'Generate strategies'}
                </button>
              </div>
            )}

            {/* Strategy error/empty feedback */}
            {strategyError && (
              <div className="p-3 border border-safety-red/30 bg-safety-red/5 rounded-lg">
                <p className="text-safety-red font-telemetry text-xs">{strategyError}</p>
              </div>
            )}

            {/* Scenario results */}
            {rainScenarios && rainScenarios.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-marshal-yellow font-telemetry text-xs uppercase tracking-wider">
                    {rainScenarios.length} Strategies Generated — Ranked by Score
                  </p>
                  <button type="button" onClick={() => { setRainScenarios(null); setRainInput(null); }} className="text-steel text-xs hover:text-chalk transition-colors">Clear</button>
                </div>
                {rainScenarios.map((sc, idx) => {
                  const risk = sc.metrics.risk_score;
                  const riskLevel = risk < 0.3 ? 'low' : risk < 0.6 ? 'medium' : 'high';
                  const borderColor = riskLevel === 'low' ? 'border-acid-green/30 bg-acid-green/5' : riskLevel === 'medium' ? 'border-marshal-yellow/30 bg-marshal-yellow/5' : 'border-safety-red/30 bg-safety-red/5';
                  const badgeColor = riskLevel === 'low' ? 'text-acid-green bg-acid-green/10 border-acid-green/30' : riskLevel === 'medium' ? 'text-marshal-yellow bg-marshal-yellow/10 border-marshal-yellow/30' : 'text-safety-red bg-safety-red/10 border-safety-red/30';

                  return (
                    <div key={idx} className={`border rounded-lg p-4 ${borderColor}`}>
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className="text-chalk font-telemetry text-sm">{sc.name}</span>
                          <span className="text-steel font-telemetry text-xs">Score: {sc.score}</span>
                        </div>
                        <span className={`inline-flex px-2 py-0.5 text-[10px] font-telemetry tracking-[0.12em] uppercase border ${badgeColor}`}>
                          {riskLevel} risk ({Math.round(risk * 100)}%)
                        </span>
                      </div>

                      <p className="text-steel font-body text-xs mb-3">{sc.description}</p>

                      {/* Metrics grid */}
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
                        <div>
                          <p className="text-steel font-telemetry text-[10px] uppercase tracking-wider">Rain pits</p>
                          <p className="text-marshal-yellow font-telemetry text-sm">{sc.metrics.pits_in_rain}</p>
                        </div>
                        <div>
                          <p className="text-steel font-telemetry text-[10px] uppercase tracking-wider">Dry pits</p>
                          <p className="text-chalk font-telemetry text-sm">{sc.metrics.pits_in_dry}</p>
                        </div>
                        <div>
                          <p className="text-steel font-telemetry text-[10px] uppercase tracking-wider">Transitions</p>
                          <p className="text-chalk font-telemetry text-sm">{sc.metrics.driver_transitions}</p>
                        </div>
                        <div>
                          <p className="text-steel font-telemetry text-[10px] uppercase tracking-wider">Flexibility</p>
                          <p className="text-chalk font-telemetry text-sm">{Math.round(sc.metrics.flexibility_score * 100)}%</p>
                        </div>
                      </div>

                      {/* Stint preview */}
                      <div className="mb-3">
                        <p className="text-steel font-telemetry text-[10px] uppercase tracking-wider mb-1">Stint preview (first 6)</p>
                        <div className="flex gap-1 flex-wrap">
                          {sc.stints.slice(0, 6).map((st, si) => {
                            const inRain = rainInput ? st.start_s < elapsed + parseInt(rainInput.durationMin || '0') * 60 && st.start_s + st.duration_s > elapsed : false;
                            return (
                              <div key={si} className={`px-2 py-1 rounded text-[10px] font-telemetry ${inRain ? 'bg-marshal-yellow/20 text-marshal-yellow' : 'bg-asphalt text-steel'}`}>
                                {st.driver_name.slice(0, 3)} {Math.round(st.duration_s / 60)}m
                              </div>
                            );
                          })}
                          {sc.stints.length > 6 && <span className="text-steel text-[10px] self-center">+{sc.stints.length - 6} more</span>}
                        </div>
                      </div>

                      <button
                        type="button"
                        onClick={async () => {
                          setApplyingStrategy(sc.approach);
                          try {
                            await api.post(`/race-strategy/${raceId}/apply-strategy`, {
                              approach: sc.approach,
                              stints: sc.stints,
                            });
                            qc.invalidateQueries({ queryKey: ['race-strategy', raceId, 'state'] });
                            setRainScenarios(null);
                            setRainInput(null);
                          } catch (err) {
                            console.error('Apply strategy failed:', err);
                          } finally {
                            setApplyingStrategy(null);
                          }
                        }}
                        disabled={applyingStrategy === sc.approach}
                        className="px-3 py-1.5 border border-gold/30 text-gold font-telemetry text-[10px] uppercase tracking-wider rounded hover:bg-gold/10 transition-colors disabled:opacity-50"
                      >
                        {applyingStrategy === sc.approach ? 'Applying...' : 'Adopt this strategy'}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Dry state info */}
            {currentCondition === 'dry' && !rainScenarios && (
              <p className="text-steel font-body text-xs">
                Track is dry. When conditions change, set the condition above and enter wet lap times to generate strategy scenarios.
              </p>
            )}
          </div>
        );
      })()}

      {/* Driver Summary */}
      {stints.length > 0 && (
        <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden">
          <div className="px-4 py-3 border-b border-steel/20">
            <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Driver Summary</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-steel/20">
                  <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Driver</th>
                  <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Stints</th>
                  <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Completed</th>
                  <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Laps</th>
                  <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Total Time</th>
                  <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Share</th>
                  {(state.total_penalty_laps ?? 0) > 0 && (
                    <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Penalties</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {drivers.map((d) => {
                  const dStints = stints.filter((s) => s.driver_id === d.id);
                  const completed = dStints.filter((s) => s.status === 'completed').length;
                  const active = dStints.find((s) => s.status === 'active');
                  // Actual driven time only (completed + active elapsed), starts from 0
                  const actualDrive = dStints.reduce((sum, s) => {
                    if (s.status === 'completed') return sum + (s.actual_duration_s ?? 0);
                    if (s.status === 'active' && s.actual_start_s != null) {
                      return sum + Math.max(0, elapsed - s.actual_start_s);
                    }
                    return sum;
                  }, 0);
                  // Total actual driven across all drivers (for share calc)
                  const totalActual = stints.reduce((sum, s) => {
                    if (s.status === 'completed') return sum + (s.actual_duration_s ?? 0);
                    if (s.status === 'active' && s.actual_start_s != null) {
                      return sum + Math.max(0, elapsed - s.actual_start_s);
                    }
                    return sum;
                  }, 0);
                  const share = totalActual > 0 ? (actualDrive / totalActual) * 100 : 0;
                  // Red if outside min/max cumulative window
                  const minCum = d.min_cumulative_s;
                  const maxCum = d.max_cumulative_s;
                  const underMin = minCum != null && actualDrive < minCum;
                  const overMax = maxCum != null && actualDrive > maxCum;
                  const timeColor = overMax ? 'text-safety-red' : underMin ? 'text-marshal-yellow' : 'text-chalk';
                  return (
                    <tr key={d.id} className="border-b border-steel/10">
                      <td className="px-4 py-3 text-chalk font-body text-sm">
                        <div className="flex items-center gap-2">
                          <span className="w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: driverColors[d.id] }} />
                          {d.driver_name}
                          {active && <span className="text-[10px] font-telemetry text-acid-green animate-pulse ml-1">LIVE</span>}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-chalk font-telemetry text-sm text-right">{dStints.length}</td>
                      <td className="px-4 py-3 text-chalk font-telemetry text-sm text-right">{completed}{active ? '+1' : ''}</td>
                      <td className="px-4 py-3 text-chalk font-telemetry text-sm text-right">
                        {dStints.reduce((sum, s) => sum + (estLaps(s) ?? 0), 0) || '\u2014'}
                      </td>
                      <td className={`px-4 py-3 font-telemetry text-sm text-right ${timeColor}`}>
                        {formatTime(Math.round(actualDrive))}
                        {(minCum || maxCum) && (
                          <span className="text-steel/40 text-[10px] ml-1">
                            ({minCum ? formatTime(minCum) : '0'}-{maxCum ? formatTime(maxCum) : '\u221E'})
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <div className="w-16 h-1.5 bg-asphalt rounded-full overflow-hidden">
                            <div className="h-full rounded-full" style={{ width: `${Math.min(100, share)}%`, backgroundColor: driverColors[d.id] }} />
                          </div>
                          <span className="text-chalk font-telemetry text-sm w-10 text-right">{totalActual > 0 ? `${share.toFixed(0)}%` : '0%'}</span>
                        </div>
                      </td>
                      {(state.total_penalty_laps ?? 0) > 0 && (() => {
                        const driverPenalties = (state.penalties ?? [])
                          .filter((p) => {
                            const pStint = p.stint_order != null ? stints.find((s) => s.stint_order === p.stint_order) : null;
                            return pStint ? pStint.driver_id === d.id : false;
                          })
                          .reduce((sum, p) => sum + p.laps_deducted, 0);
                        return (
                          <td className="px-4 py-3 text-right">
                            {driverPenalties > 0 ? (
                              <span className="text-safety-red font-telemetry text-sm">-{driverPenalties}</span>
                            ) : (
                              <span className="text-steel font-telemetry text-sm">{'\u2014'}</span>
                            )}
                          </td>
                        );
                      })()}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

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
                <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Laps</th>
                <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Total Laps</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Est. End</th>
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Ballast</th>
                {quickChangeEnabled && <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Kart</th>}
                <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Status</th>
              </tr>
            </thead>
            <tbody>
              {stints.map((s) => {
                const planned = s.planned_duration_s;
                const actual = s.actual_duration_s;
                const delta = planned != null && actual != null ? actual - planned : null;
                const sCfg = stintStatusConfig[s.status] || stintStatusConfig.planned;
                // Estimate clock time when this stint ends
                const plannedEndS = s.planned_end_s;
                const raceStartTs = race.race_start_ts;
                let estEndStr: string | null = null;
                if (plannedEndS != null && raceStartTs) {
                  try {
                    const start = new Date(raceStartTs.replace('Z', '+00:00')).getTime();
                    // Add pit stop time between stints (pit_time * (stint_order - 1))
                    const pitTime = race.min_pit_stop_s || 60;
                    const estEnd = new Date(start + (plannedEndS + (s.stint_order - 1) * pitTime) * 1000);
                    estEndStr = estEnd.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                  } catch { /* ignore */ }
                }
                return (
                  <tr key={s.stint_id} className={`border-b border-steel/10 ${s.status === 'active' ? 'bg-acid-green/5' : ''}`}>
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
                    <td className="px-4 py-3 text-chalk font-telemetry text-sm text-right">
                      {s.actual_laps != null ? s.actual_laps : (estLaps(s) ?? '\u2014')}
                    </td>
                    <td className="px-4 py-3 text-gold font-telemetry text-sm text-right">
                      {cumulativeLaps(s.stint_order) || '\u2014'}
                    </td>
                    <td className="px-4 py-3 text-chalk font-telemetry text-sm">
                      {estEndStr ?? '\u2014'}
                    </td>
                    <td className="px-4 py-3 text-marshal-yellow font-telemetry text-sm">
                      {s.ballast_kg != null && s.ballast_kg > 0 ? `${s.ballast_kg} kg` : '\u2014'}
                    </td>
                    {quickChangeEnabled && (
                      <td className="px-4 py-3 text-chalk font-telemetry text-sm">
                        {(s as Record<string, unknown>).kart_number ? String((s as Record<string, unknown>).kart_number) : '\u2014'}
                      </td>
                    )}
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

      {/* Kart History (quick change only) */}
      {quickChangeEnabled && stints.some((s) => (s as Record<string, unknown>).kart_number) && (
        <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden">
          <button
            type="button"
            onClick={() => setShowKartHistory(!showKartHistory)}
            className="w-full px-4 py-3 border-b border-steel/20 flex items-center justify-between"
          >
            <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Kart History</h3>
            <span className="text-steel text-xs font-telemetry">{showKartHistory ? '\u25BC' : '\u25B6'}</span>
          </button>
          {showKartHistory && (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-steel/20">
                    <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Stint #</th>
                    <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Driver</th>
                    <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Kart #</th>
                    <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Avg Lap Time</th>
                  </tr>
                </thead>
                <tbody>
                  {stints
                    .filter((s) => (s as Record<string, unknown>).kart_number)
                    .map((s) => {
                      const d = drivers.find((dr) => dr.id === s.driver_id);
                      return (
                        <tr key={s.stint_id} className="border-b border-steel/10">
                          <td className="px-4 py-3 text-chalk font-body text-sm">{s.stint_order}</td>
                          <td className="px-4 py-3 text-chalk font-body text-sm">
                            <div className="flex items-center gap-2">
                              <span className="w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: driverColors[s.driver_id] }} />
                              {s.driver_name}
                            </div>
                          </td>
                          <td className="px-4 py-3 text-chalk font-telemetry text-sm">{String((s as Record<string, unknown>).kart_number)}</td>
                          <td className="px-4 py-3 text-chalk font-telemetry text-sm text-right">{d?.avg_lap_time_s ? `${d.avg_lap_time_s.toFixed(1)}s` : '\u2014'}</td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Penalty Log */}
      {state.penalties && state.penalties.length > 0 && (
        <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden">
          <button
            type="button"
            onClick={() => setShowPenaltyLog(!showPenaltyLog)}
            className="w-full px-4 py-3 border-b border-steel/20 flex items-center justify-between"
          >
            <div className="flex items-center gap-3">
              <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider">Penalty Log</h3>
              {(state.total_penalty_laps ?? 0) > 0 && (
                <span className="inline-flex px-2 py-0.5 text-[10px] font-telemetry tracking-[0.12em] uppercase border text-safety-red bg-safety-red/10 border-safety-red/30">
                  -{state.total_penalty_laps} laps
                </span>
              )}
            </div>
            <span className="text-steel text-xs font-telemetry">{showPenaltyLog ? '\u25BC' : '\u25B6'}</span>
          </button>
          {showPenaltyLog && (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-steel/20">
                    <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Time</th>
                    <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Type</th>
                    <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Reason</th>
                    <th scope="col" className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Laps</th>
                    <th scope="col" className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {state.penalties.map((p) => (
                    <tr key={p.id} className="border-b border-steel/10">
                      <td className="px-4 py-3 text-chalk font-telemetry text-sm">{formatTime(p.elapsed_s)}</td>
                      <td className="px-4 py-3 text-chalk font-body text-sm capitalize">{p.penalty_type.replace('_', ' ')}</td>
                      <td className="px-4 py-3 text-steel font-body text-sm">{p.reason || '\u2014'}</td>
                      <td className="px-4 py-3 text-safety-red font-telemetry text-sm text-right">-{p.laps_deducted}</td>
                      <td className="px-4 py-3">
                        {p.cleared ? (
                          <span className="inline-flex px-2 py-0.5 text-[10px] font-telemetry tracking-[0.12em] uppercase border text-acid-green bg-acid-green/10 border-acid-green/30">
                            CLEARED
                          </span>
                        ) : (
                          <button
                            type="button"
                            onClick={() => clearPenaltyMut.mutate(p.id)}
                            disabled={clearPenaltyMut.isPending}
                            className="inline-flex px-2 py-0.5 text-[10px] font-telemetry tracking-[0.12em] uppercase border text-safety-red bg-safety-red/10 border-safety-red/30 hover:bg-safety-red/20 transition-colors disabled:opacity-50 cursor-pointer"
                          >
                            ACTIVE
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t border-steel/20">
                    <td colSpan={3} className="px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Total Penalty Laps</td>
                    <td className="px-4 py-3 text-safety-red font-telemetry text-sm text-right font-bold">-{state.total_penalty_laps ?? 0}</td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </div>
      )}

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
          <h3 className="font-telemetry text-xs text-steel uppercase tracking-wider mb-3">Team Messages</h3>
          <MessageLog messages={state.messages as Array<{ msg_id: number; author: string; message: string; category: string; created_at: string }>} />
        </div>
      )}

      {/* Mutation errors */}
      {(pitInMut.error || pitOutMut.error || reoptimizeMut.error || wakeDriverMut.error || finishMut.error || techStopInMut.error || techStopOutMut.error || addPenaltyMut.error || clearPenaltyMut.error) && (
        <div className="flex items-center justify-between bg-safety-red/10 border border-safety-red/30 rounded-lg px-4 py-2 mt-4">
          <p className="text-safety-red font-telemetry text-xs">
            {((pitInMut.error || pitOutMut.error || reoptimizeMut.error || wakeDriverMut.error || finishMut.error || techStopInMut.error || techStopOutMut.error || addPenaltyMut.error || clearPenaltyMut.error) as Error).message || 'Action failed'}
          </p>
          <button type="button" onClick={() => { pitInMut.reset(); pitOutMut.reset(); reoptimizeMut.reset(); wakeDriverMut.reset(); finishMut.reset(); techStopInMut.reset(); techStopOutMut.reset(); addPenaltyMut.reset(); clearPenaltyMut.reset(); }} className="text-safety-red/60 hover:text-safety-red text-xs ml-3">dismiss</button>
        </div>
      )}

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
              <button type="button" onClick={() => setShowSleepWarning(false)}
                className="px-4 py-2 text-sm text-steel border border-steel/30 rounded-lg hover:bg-steel/10">
                Cancel
              </button>
              <button type="button" onClick={() => { setShowSleepWarning(false); pitInMut.mutate(); }}
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
