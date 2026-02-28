'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import { useState, useMemo } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, DataTable } from '@/components/app';
import {
  SpeedTrace,
  GGDiagram,
  TrackMap,
  DrivingStyle,
  LapProgress,
  SectorChart,
  LapDistribution,
  LapOverlay,
  Fingerprint,
  ConsistencyHeatmap,
  BrakeScatter,
  CornerMastery,
  EnergyBalance,
  FatigueChart,
  SpeedProfile,
  ThrottleHeatmap,
  WorkloadChart,
  TyreChart,
  WeatherChart,
  TrendChart,
  StintChart,
  PitWindowChart,
  RivalChart,
  ComparisonMatrix,
} from '@/components/app/charts';
import { CornerReplay } from '@/components/app/corner-replay';
import { FocusMode } from '@/components/app/focus-mode';

/* ─── Types ───────────────────────────────────────────────────────────── */

interface SessionDetail {
  id: string;
  date: string;
  track_name: string;
  driver_name: string;
  laps: number;
  best_time: number | null;
  mean_time: number | null;
  score: number | null;
  grade: string | null;
  consistency_score: number | null;
  pace_score: number | null;
  execution_score: number | null;
  robustness_score: number | null;
  session_type: string | null;
  condition: string | null;
  kart_name: string | null;
  condition_phases?: ConditionPhase[];
  data_health?: {
    gps_quality: number | null;
    gps_coverage_pct: number | null;
    sampling_rate_hz: number | null;
    total_points: number | null;
    dropped_points: number | null;
    sensor_channels: string[] | null;
  } | null;
  weather?: {
    temperature_c: number | null;
    humidity_pct: number | null;
    wind_speed_ms: number | null;
    conditions: string | null;
  } | null;
}

interface LapRow {
  lap_number: number;
  time: number;
  speed_avg: number | null;
  speed_max: number | null;
  max_braking: number | null;
  max_accel: number | null;
  line_length: number | null;
  valid: boolean;
  is_best: boolean;
  phase_id: number | null;
}

interface ConditionPhase {
  phase_id: number;
  lap_start: number;
  lap_end: number;
  label: string;
  confidence: number | null;
  median_pace_s: number | null;
}

interface CoachingMetric {
  name: string;
  value: number;
  max: number;
}

interface FingerprintData {
  metrics: CoachingMetric[];
  strengths: string[];
  weaknesses: string[];
  adaptation_score: number | null;
}

interface Badge {
  badge_type: string;
  badge_name: string;
  badge_level: string;
  metadata?: Record<string, unknown>;
  earned_at: string;
}

interface SessionTag {
  tag: string;
  confidence: number;
  source: string;
  created_at: string;
}

interface BadgesData {
  session_id: string;
  badges: Badge[];
  tags: SessionTag[];
}

interface CornerCoachingEntry {
  corner_id: number;
  coaching_hint: string | null;
  avg_entry_speed_mps: number | null;
  avg_apex_speed_mps: number | null;
  avg_exit_speed_mps: number | null;
  avg_time_loss_ms: number | null;
  best_practice?: {
    best_entry_mps: number;
    best_apex_mps: number;
    best_exit_mps: number;
    best_brake_m: number;
    best_time_s: number;
  };
}

interface TheoreticalData {
  theoretical_time_s: number | null;
  actual_best_time_s: number | null;
  gap_pct: number | null;
  simulation_method: string | null;
  corner_coaching?: unknown[];
}

interface StintEntry {
  stint_number: number;
  start_lap: number;
  end_lap: number;
  avg_time: number;
  best_time: number;
  laps_count: number;
}

/* ─── Helpers ─────────────────────────────────────────────────────────── */

function formatTime(s: number | null): string {
  if (s == null) return '--';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function stdDev(values: number[]): number {
  if (values.length < 2) return 0;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const sqDiffs = values.map((v) => (v - mean) ** 2);
  return Math.sqrt(sqDiffs.reduce((a, b) => a + b, 0) / (values.length - 1));
}

function gradeColor(grade: string | null): string {
  if (!grade) return 'bg-steel/20 text-steel';
  const g = grade.toUpperCase();
  if (g === 'A+' || g === 'A') return 'bg-acid-green/20 text-acid-green';
  if (g === 'B+' || g === 'B') return 'bg-emerald-500/20 text-emerald-400';
  if (g === 'C+' || g === 'C') return 'bg-amber-400/20 text-amber-400';
  if (g === 'D+' || g === 'D') return 'bg-orange-400/20 text-orange-400';
  return 'bg-safety-red/20 text-safety-red';
}

/* ─── Score Category Descriptions ─────────────────────────────────────── */

const SCORE_DESCRIPTIONS: Record<string, string> = {
  Pace: 'How close to theoretical best lap time',
  Consistency: 'Lap-to-lap time variation and repeatability',
  Execution: 'Corner precision, brake and throttle technique',
  Robustness: 'Performance under changing conditions and fatigue',
};

/* ─── Score Bar Component ─────────────────────────────────────────────── */

function ScoreBar({ label, value, max, description }: {
  label: string;
  value: number | null;
  max: number;
  description?: string;
}) {
  const pct = value != null ? (value / max) * 100 : 0;
  const tier =
    pct >= 80 ? 'excellent' : pct >= 60 ? 'good' : pct >= 40 ? 'average' : 'poor';
  const barColor = {
    excellent: 'bg-acid-green',
    good: 'bg-emerald-400',
    average: 'bg-amber-400',
    poor: 'bg-safety-red',
  }[tier];
  const tierLabel = {
    excellent: 'text-acid-green',
    good: 'text-emerald-400',
    average: 'text-amber-400',
    poor: 'text-safety-red',
  }[tier];

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-chalk text-sm font-body font-medium">{label}</span>
          {description && (
            <span className="text-steel/60 text-[10px] font-telemetry hidden sm:inline">
              {description}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-xs font-telemetry ${tierLabel}`}>
            {pct.toFixed(0)}%
          </span>
          <span className="text-chalk font-telemetry text-sm w-16 text-right">
            {value?.toFixed(1) ?? '--'}/{max}
          </span>
        </div>
      </div>
      <div className="h-2.5 bg-carbon rounded-full overflow-hidden">
        <div
          className={`h-full ${barColor} rounded-full transition-all duration-500`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/* ─── Badge Level Colors ─────────────────────────────────────────────── */

function badgeLevelColor(level: string): string {
  switch (level.toLowerCase()) {
    case 'gold': return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
    case 'silver': return 'bg-gray-400/20 text-gray-300 border-gray-400/30';
    case 'bronze': return 'bg-orange-600/20 text-orange-400 border-orange-600/30';
    default: return 'bg-steel/20 text-steel border-steel/30';
  }
}

/* ─── Section Header ──────────────────────────────────────────────────── */

function SectionHeader({ title }: { title: string }) {
  return (
    <h3 className="font-body text-chalk text-lg font-semibold mb-4 mt-2">{title}</h3>
  );
}

/* ─── Tab Definitions ─────────────────────────────────────────────────── */

const tabs = ['Overview', 'Corners & Coaching', 'Performance', 'Analytics', 'Lap Data'] as const;
type Tab = (typeof tabs)[number];

/* ─── Page Component ──────────────────────────────────────────────────── */

export default function SessionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState<Tab>('Overview');
  const [focusOpen, setFocusOpen] = useState(false);
  const [selectedCorner, setSelectedCorner] = useState(1);

  /* ── Data Fetching ── */

  const { data: session, isLoading } = useQuery({
    queryKey: ['session', id],
    queryFn: () => api.get<SessionDetail>(`/sessions/${id}/details`),
  });

  const { data: lapsData } = useQuery({
    queryKey: ['session', id, 'laps'],
    queryFn: () => api.get<{ laps: LapRow[] }>(`/sessions/${id}/laps`),
  });

  const { data: coachingData } = useQuery({
    queryKey: ['session', id, 'fingerprint'],
    queryFn: () => api.get<FingerprintData>(`/sessions/${id}/fingerprint`),
  });

  const { data: badgesData } = useQuery({
    queryKey: ['session', id, 'badges'],
    queryFn: () => api.get<BadgesData>(`/sessions/${id}/badges`),
  });

  const { data: cornerCoachingData } = useQuery({
    queryKey: ['session', id, 'corner-coaching'],
    queryFn: () => api.get<{ coaching: CornerCoachingEntry[] }>(`/sessions/${id}/corner-coaching`),
    enabled: activeTab === 'Corners & Coaching',
  });

  const { data: theoreticalData } = useQuery({
    queryKey: ['session', id, 'theoretical'],
    queryFn: () => api.get<TheoreticalData>(`/sessions/${id}/theoretical`),
    enabled: activeTab === 'Corners & Coaching',
  });

  const { data: stintData } = useQuery({
    queryKey: ['session', id, 'stints'],
    queryFn: () => api.get<{ stints: StintEntry[] }>(`/sessions/${id}/stints`),
    enabled: activeTab === 'Performance',
  });

  /* ── Derived Values ── */

  const laps = lapsData?.laps ?? [];
  const validTimes = useMemo(() => laps.filter((l) => l.valid).map((l) => l.time), [laps]);
  const bestTime = useMemo(() => (validTimes.length > 0 ? Math.min(...validTimes) : null), [validTimes]);
  const meanTime = useMemo(
    () => (validTimes.length > 0 ? validTimes.reduce((a, b) => a + b, 0) / validTimes.length : null),
    [validTimes],
  );
  const lapStdDev = useMemo(() => (validTimes.length >= 2 ? stdDev(validTimes) : null), [validTimes]);
  const consistencyPct = useMemo(() => {
    if (meanTime == null || lapStdDev == null || meanTime === 0) return null;
    return Math.max(0, 100 - (lapStdDev / meanTime) * 100);
  }, [meanTime, lapStdDev]);
  const improvementTrend = useMemo(() => {
    if (validTimes.length < 3) return null;
    const firstHalf = validTimes.slice(0, Math.floor(validTimes.length / 2));
    const secondHalf = validTimes.slice(Math.floor(validTimes.length / 2));
    const avgFirst = firstHalf.reduce((a, b) => a + b, 0) / firstHalf.length;
    const avgSecond = secondHalf.reduce((a, b) => a + b, 0) / secondHalf.length;
    return avgFirst - avgSecond; // positive = improving (faster)
  }, [validTimes]);
  const bestVsMeanGap = useMemo(() => {
    if (bestTime == null || meanTime == null || bestTime === 0) return null;
    return ((meanTime - bestTime) / bestTime) * 100;
  }, [bestTime, meanTime]);
  const top25Avg = useMemo(() => {
    if (validTimes.length < 4) return null;
    const sorted = [...validTimes].sort((a, b) => a - b);
    const q = sorted.slice(0, Math.ceil(sorted.length / 4));
    return q.reduce((a, b) => a + b, 0) / q.length;
  }, [validTimes]);
  const validLapCount = useMemo(() => laps.filter((l) => l.valid).length, [laps]);

  const hasCoaching = (coachingData?.metrics?.length ?? 0) > 0;

  /* ── Loading & Error States ── */

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      </div>
    );
  }

  if (!session) {
    return <div className="text-steel font-body p-8">Session not found.</div>;
  }

  /* ── Lap Table Columns ── */

  const lapColumns = [
    {
      key: 'lap_number',
      header: 'Lap',
      sortable: true,
      className: 'font-telemetry w-16',
      render: (row: LapRow) => (
        <span className="flex items-center gap-2">
          <span className={row.is_best ? 'text-acid-green font-bold' : !row.valid ? 'text-steel/50' : 'text-chalk'}>
            {row.lap_number}
          </span>
          {row.is_best && (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-telemetry bg-acid-green/20 text-acid-green border border-acid-green/30">
              BEST
            </span>
          )}
          {!row.valid && (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-telemetry bg-safety-red/20 text-safety-red border border-safety-red/30">
              INV
            </span>
          )}
        </span>
      ),
    },
    {
      key: 'time',
      header: 'Time',
      sortable: true,
      className: 'font-telemetry',
      render: (row: LapRow) => (
        <span className={row.is_best ? 'text-acid-green font-semibold' : !row.valid ? 'text-steel/50' : 'text-chalk'}>
          {formatTime(row.time)}
        </span>
      ),
    },
    {
      key: 'delta',
      header: 'Delta',
      sortable: false,
      className: 'font-telemetry',
      render: (row: LapRow) => {
        if (!row.valid || bestTime == null) return <span className="text-steel/40">--</span>;
        const delta = row.time - bestTime;
        if (delta === 0) return <span className="text-acid-green font-semibold">±0.000</span>;
        return (
          <span className={delta < 0.5 ? 'text-emerald-400' : delta < 1.5 ? 'text-amber-400' : 'text-safety-red'}>
            +{delta.toFixed(3)}
          </span>
        );
      },
    },
    {
      key: 'speed_avg',
      header: 'Avg km/h',
      sortable: true,
      className: 'font-telemetry',
      render: (row: LapRow) => (
        <span className={!row.valid ? 'text-steel/50' : 'text-chalk'}>
          {row.speed_avg != null ? row.speed_avg.toFixed(1) : '--'}
        </span>
      ),
    },
    {
      key: 'speed_max',
      header: 'Max km/h',
      sortable: true,
      className: 'font-telemetry',
      render: (row: LapRow) => (
        <span className={!row.valid ? 'text-steel/50' : 'text-chalk'}>
          {row.speed_max != null ? row.speed_max.toFixed(1) : '--'}
        </span>
      ),
    },
    {
      key: 'max_braking',
      header: 'Brake G',
      sortable: true,
      className: 'font-telemetry',
      render: (row: LapRow) => (
        <span className={!row.valid ? 'text-steel/50' : 'text-chalk'}>
          {row.max_braking != null ? (row.max_braking / 9.81).toFixed(2) : '--'}
        </span>
      ),
    },
    {
      key: 'max_accel',
      header: 'Accel G',
      sortable: true,
      className: 'font-telemetry',
      render: (row: LapRow) => (
        <span className={!row.valid ? 'text-steel/50' : 'text-chalk'}>
          {row.max_accel != null ? (row.max_accel / 9.81).toFixed(2) : '--'}
        </span>
      ),
    },
    {
      key: 'line_length',
      header: 'Line (m)',
      sortable: true,
      className: 'font-telemetry',
      render: (row: LapRow) => (
        <span className={!row.valid ? 'text-steel/50' : 'text-chalk'}>
          {row.line_length != null ? Math.round(row.line_length) : '--'}
        </span>
      ),
    },
    {
      key: 'phase_id',
      header: 'Phase',
      className: 'font-telemetry w-16',
      render: (row: LapRow) => {
        if (row.phase_id == null) return <span className="text-steel/40">--</span>;
        const phase = session.condition_phases?.find((p) => p.phase_id === row.phase_id);
        const phaseLabel = phase?.label ?? `P${row.phase_id}`;
        const phaseColor = phaseLabel.toLowerCase().includes('dry') ? 'text-emerald-400'
          : phaseLabel.toLowerCase().includes('wet') ? 'text-blue-400'
          : phaseLabel.toLowerCase().includes('damp') ? 'text-amber-400'
          : 'text-purple-400';
        return <span className={`text-xs ${phaseColor}`}>{phaseLabel}</span>;
      },
    },
  ];

  /* ── Render ── */

  return (
    <div className="max-w-7xl mx-auto">
      {/* ── Focus Mode Overlay ── */}
      <FocusMode sessionId={id} isOpen={focusOpen} onClose={() => setFocusOpen(false)} />

      {/* ── Breadcrumb ── */}
      <nav className="mb-4">
        <Link
          href="/app/sessions"
          className="text-steel hover:text-acid-green transition-colors font-body text-sm"
        >
          &larr; Sessions
        </Link>
      </nav>

      {/* ── Header: Track Name + Grade Badge ── */}
      <PageHeader
        title={session.track_name}
        subtitle={session.date}
        actions={
          session.grade ? (
            <span
              className={`inline-flex items-center px-3 py-1 rounded-md font-monument text-lg ${gradeColor(session.grade)}`}
            >
              {session.grade}
            </span>
          ) : undefined
        }
      />

      {/* ── Metadata Cards Row 1 ── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3 mb-3">
        <StatCard label="Date" value={session.date} />
        <StatCard label="Driver" value={session.driver_name || '--'} />
        <StatCard label="Track" value={session.track_name} />
        <StatCard label="Type" value={session.session_type || 'Practice'} />
        <StatCard label="Condition" value={session.condition || 'Dry'} />
      </div>

      {/* ── Metadata Cards Row 2 ── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3 mb-6">
        <StatCard label="Laps" value={session.laps} />
        <StatCard
          label="Best Lap"
          value={formatTime(session.best_time)}
          trend="up"
        />
        <StatCard
          label="Mean Lap"
          value={formatTime(session.mean_time)}
          trend="neutral"
        />
        <StatCard
          label="Score"
          value={session.score?.toFixed(1) ?? '--'}
          unit="/100"
          trend={session.score != null && session.score >= 75 ? 'up' : 'neutral'}
        />
        <StatCard label="Kart" value={session.kart_name || '--'} />
      </div>

      {/* ── Tab Bar + Focus Mode Button ── */}
      <div className="flex items-center justify-between border-b border-steel/20 mb-6">
        <div className="flex gap-1 overflow-x-auto">
          {tabs.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2.5 font-telemetry text-sm whitespace-nowrap transition-colors ${
                activeTab === tab
                  ? 'text-acid-green border-b-2 border-acid-green'
                  : 'text-steel hover:text-chalk'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
        <button
          onClick={() => setFocusOpen(true)}
          className="flex items-center gap-2 px-3 py-1.5 mb-1 rounded-lg border border-steel/20 text-steel hover:text-acid-green hover:border-acid-green/40 transition-colors font-telemetry text-sm whitespace-nowrap"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="shrink-0">
            <rect x="1" y="1" width="14" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
            <rect x="5" y="5" width="6" height="6" rx="1" fill="currentColor" />
          </svg>
          Focus Mode
        </button>
      </div>

      {/* ── Tab Content ── */}
      <div className="min-h-[400px]">
        {/* ─────────── Tab 1: Overview ─────────── */}
        {activeTab === 'Overview' && (
          <div className="space-y-8">
            {/* Score Breakdown — uses fingerprint API max values */}
            <section>
              <SectionHeader title="Score Breakdown" />
              <div className="bg-concrete rounded-lg border border-steel/10 p-5 space-y-4">
                {(coachingData?.metrics ?? []).length > 0 ? (
                  coachingData!.metrics.map((m) => (
                    <ScoreBar
                      key={m.name}
                      label={m.name}
                      value={m.value}
                      max={m.max}
                      description={SCORE_DESCRIPTIONS[m.name]}
                    />
                  ))
                ) : (
                  <>
                    <ScoreBar label="Pace" value={session.pace_score} max={25} description={SCORE_DESCRIPTIONS.Pace} />
                    <ScoreBar label="Consistency" value={session.consistency_score} max={25} description={SCORE_DESCRIPTIONS.Consistency} />
                    <ScoreBar label="Execution" value={session.execution_score} max={20} description={SCORE_DESCRIPTIONS.Execution} />
                    <ScoreBar label="Robustness" value={session.robustness_score} max={15} description={SCORE_DESCRIPTIONS.Robustness} />
                  </>
                )}
                <div className="pt-3 border-t border-steel/10 flex items-center justify-between">
                  <span className="text-steel text-sm font-body">Total Score</span>
                  <div className="flex items-center gap-2">
                    {session.grade && (
                      <span className={`px-2 py-0.5 rounded text-xs font-monument ${gradeColor(session.grade)}`}>
                        {session.grade}
                      </span>
                    )}
                    <span className="font-monument text-xl text-acid-green">
                      {session.score?.toFixed(1) ?? '--'}
                      <span className="text-steel text-sm font-telemetry">/100</span>
                    </span>
                  </div>
                </div>

                {/* Adaptation Score */}
                {coachingData?.adaptation_score != null && (
                  <div className="flex items-center justify-between pt-2 border-t border-steel/10">
                    <span className="text-steel text-xs font-body">Session Adaptation</span>
                    <span className={`font-telemetry text-sm ${
                      coachingData.adaptation_score > 0.5 ? 'text-acid-green' : 'text-amber-400'
                    }`}>
                      {(coachingData.adaptation_score * 100).toFixed(0)}%
                    </span>
                  </div>
                )}
              </div>
            </section>

            {/* Strengths & Weaknesses */}
            {((coachingData?.strengths?.length ?? 0) > 0 || (coachingData?.weaknesses?.length ?? 0) > 0) && (
              <section>
                <SectionHeader title="Strengths & Areas to Improve" />
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Strengths */}
                  {(coachingData?.strengths?.length ?? 0) > 0 && (
                    <div className="bg-concrete rounded-lg border border-acid-green/20 p-4">
                      <div className="flex items-center gap-2 mb-3">
                        <span className="w-2 h-2 rounded-full bg-acid-green" />
                        <h4 className="text-acid-green font-telemetry text-xs uppercase tracking-wider">Strengths</h4>
                      </div>
                      <ul className="space-y-2">
                        {coachingData!.strengths.map((s, i) => (
                          <li key={i} className="text-chalk text-sm font-body flex items-start gap-2">
                            <span className="text-acid-green mt-1 shrink-0">+</span>
                            {s}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {/* Weaknesses */}
                  {(coachingData?.weaknesses?.length ?? 0) > 0 && (
                    <div className="bg-concrete rounded-lg border border-amber-400/20 p-4">
                      <div className="flex items-center gap-2 mb-3">
                        <span className="w-2 h-2 rounded-full bg-amber-400" />
                        <h4 className="text-amber-400 font-telemetry text-xs uppercase tracking-wider">Areas to Improve</h4>
                      </div>
                      <ul className="space-y-2">
                        {coachingData!.weaknesses.map((w, i) => (
                          <li key={i} className="text-chalk text-sm font-body flex items-start gap-2">
                            <span className="text-amber-400 mt-1 shrink-0">!</span>
                            {w}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* Charts 2x2 */}
            <section>
              <SectionHeader title="Session Overview" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <SpeedTrace sessionId={id} />
                <GGDiagram sessionId={id} />
                <TrackMap sessionId={id} />
                <DrivingStyle sessionId={id} />
              </div>
            </section>

            {/* Fingerprint */}
            <section>
              <SectionHeader title="Driving Fingerprint" />
              <Fingerprint sessionId={id} />
            </section>

            {/* Next Session Actions / Coaching Cards */}
            {hasCoaching && (
              <section>
                <SectionHeader title="Next Session Actions" />
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
                  {coachingData!.metrics
                    .filter((m) => m.max > 0 && (m.value / m.max) < 0.75)
                    .sort((a, b) => (a.value / a.max) - (b.value / b.max))
                    .slice(0, 6)
                    .map((metric, idx) => {
                      const pct = (metric.value / metric.max) * 100;
                      const priority = pct < 40 ? 'P1' : pct < 60 ? 'P2' : 'P3';
                      const priorityColor = priority === 'P1'
                        ? 'bg-safety-red/20 text-safety-red border-safety-red/30'
                        : priority === 'P2'
                          ? 'bg-amber-400/20 text-amber-400 border-amber-400/30'
                          : 'bg-steel/20 text-steel border-steel/30';
                      return (
                        <div
                          key={metric.name}
                          className="bg-concrete rounded-lg border border-steel/10 p-4"
                        >
                          <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-2">
                              <span className="font-monument text-lg text-steel/40">{idx + 1}</span>
                              <span className="font-body text-chalk text-sm">{metric.name}</span>
                            </div>
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-telemetry font-bold border ${priorityColor}`}>
                              {priority}
                            </span>
                          </div>
                          <div className="h-2 bg-carbon rounded-full overflow-hidden mb-2">
                            <div
                              className={`h-full rounded-full ${pct >= 60 ? 'bg-emerald-400' : pct >= 40 ? 'bg-amber-400' : 'bg-safety-red'}`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <p className="text-steel text-xs font-body">
                            {pct < 40 ? 'Critical focus area' : pct < 60 ? 'Needs improvement' : 'Fine-tuning opportunity'}
                          </p>
                        </div>
                      );
                    })}
                </div>
              </section>
            )}

            {/* Achievements & Badges */}
            {badgesData && (badgesData.badges.length > 0 || badgesData.tags.length > 0) && (
              <section>
                <SectionHeader title="Achievements & Rating" />
                <div className="space-y-4">
                  {/* Badge Cards */}
                  {badgesData.badges.length > 0 && (
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                      {badgesData.badges.map((badge, i) => (
                        <div
                          key={i}
                          className={`rounded-lg border p-3 text-center ${badgeLevelColor(badge.badge_level)}`}
                        >
                          <div className="text-lg mb-1">
                            {badge.badge_level === 'gold' ? '🥇' : badge.badge_level === 'silver' ? '🥈' : '🥉'}
                          </div>
                          <p className="font-body text-xs font-medium">{badge.badge_name}</p>
                          <p className="font-telemetry text-[10px] opacity-70 mt-1">
                            {badge.badge_level.toUpperCase()}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                  {/* Session Tags */}
                  {badgesData.tags.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      {badgesData.tags.map((tag, i) => (
                        <span
                          key={i}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-concrete rounded-md border border-steel/20 text-xs font-telemetry text-chalk"
                        >
                          <span className="w-1.5 h-1.5 rounded-full bg-acid-green" />
                          {tag.tag.replace(/_/g, ' ')}
                          <span className="text-steel/60">{(tag.confidence * 100).toFixed(0)}%</span>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </section>
            )}
          </div>
        )}

        {/* ─────────── Tab 2: Corners & Coaching ─────────── */}
        {activeTab === 'Corners & Coaching' && (
          <div className="space-y-8">
            {/* Theoretical Lap */}
            {theoreticalData && theoreticalData.theoretical_time_s != null && (
              <section>
                <SectionHeader title="Theoretical Lap" />
                <div className="bg-concrete rounded-lg border border-steel/10 p-5">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                    <div>
                      <p className="text-steel font-telemetry text-xs uppercase tracking-wider mb-1">Theoretical</p>
                      <p className="text-acid-green font-telemetry text-lg font-bold">
                        {formatTime(theoreticalData.theoretical_time_s)}
                      </p>
                    </div>
                    <div>
                      <p className="text-steel font-telemetry text-xs uppercase tracking-wider mb-1">Actual Best</p>
                      <p className="text-chalk font-telemetry text-lg">
                        {formatTime(theoreticalData.actual_best_time_s)}
                      </p>
                    </div>
                    <div>
                      <p className="text-steel font-telemetry text-xs uppercase tracking-wider mb-1">Gap</p>
                      <p className={`font-telemetry text-lg ${
                        (theoreticalData.gap_pct ?? 0) < 2 ? 'text-acid-green' :
                        (theoreticalData.gap_pct ?? 0) < 5 ? 'text-amber-400' : 'text-safety-red'
                      }`}>
                        {theoreticalData.gap_pct != null ? `+${theoreticalData.gap_pct.toFixed(2)}%` : '--'}
                      </p>
                    </div>
                    <div>
                      <p className="text-steel font-telemetry text-xs uppercase tracking-wider mb-1">Method</p>
                      <span className="inline-block px-2 py-0.5 rounded bg-steel/10 text-chalk font-telemetry text-xs">
                        {theoreticalData.simulation_method || 'Best sectors'}
                      </span>
                    </div>
                  </div>
                </div>
              </section>
            )}

            {/* Corner Replay (full width) */}
            <section>
              <div className="flex items-center justify-between mb-4 mt-2">
                <h3 className="font-body text-chalk text-lg font-semibold">Corner Replay</h3>
                <div className="flex items-center gap-2">
                  {/* Corner navigation pills */}
                  {(cornerCoachingData?.coaching ?? []).length > 0 && (
                    <div className="flex gap-1 mr-3">
                      {cornerCoachingData!.coaching.slice(0, 10).map((c) => (
                        <button
                          key={c.corner_id}
                          onClick={() => setSelectedCorner(c.corner_id)}
                          className={`w-7 h-7 rounded text-xs font-telemetry transition-colors ${
                            selectedCorner === c.corner_id
                              ? 'bg-acid-green text-carbon font-bold'
                              : 'bg-steel/10 text-steel hover:text-chalk'
                          }`}
                        >
                          {c.corner_id}
                        </button>
                      ))}
                    </div>
                  )}
                  <button
                    onClick={() => setSelectedCorner(Math.max(1, selectedCorner - 1))}
                    className="px-2 py-1 bg-steel/10 text-steel hover:text-chalk rounded font-telemetry text-sm"
                  >
                    &larr;
                  </button>
                  <span className="text-chalk font-telemetry text-sm w-6 text-center">{selectedCorner}</span>
                  <button
                    onClick={() => setSelectedCorner(selectedCorner + 1)}
                    className="px-2 py-1 bg-steel/10 text-steel hover:text-chalk rounded font-telemetry text-sm"
                  >
                    &rarr;
                  </button>
                </div>
              </div>
              <div className="bg-concrete rounded-lg border border-steel/10 p-4 min-h-[300px]">
                <CornerReplay sessionId={id} cornerId={selectedCorner} />
              </div>
            </section>

            {/* Corner Coaching Table */}
            {(cornerCoachingData?.coaching ?? []).length > 0 && (
              <section>
                <SectionHeader title="Corner Coaching" />
                <div className="bg-concrete rounded-lg border border-steel/10 overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-steel/10">
                          <th className="px-4 py-3 text-left text-steel font-telemetry text-xs uppercase tracking-wider">Corner</th>
                          <th className="px-4 py-3 text-right text-steel font-telemetry text-xs uppercase tracking-wider">Avg Entry</th>
                          <th className="px-4 py-3 text-right text-steel font-telemetry text-xs uppercase tracking-wider">Avg Apex</th>
                          <th className="px-4 py-3 text-right text-steel font-telemetry text-xs uppercase tracking-wider">Avg Exit</th>
                          <th className="px-4 py-3 text-right text-steel font-telemetry text-xs uppercase tracking-wider">Time Loss</th>
                          <th className="px-4 py-3 text-left text-steel font-telemetry text-xs uppercase tracking-wider">Coaching Hint</th>
                        </tr>
                      </thead>
                      <tbody>
                        {cornerCoachingData!.coaching.map((c) => {
                          const toKmh = (mps: number | null) => mps != null ? (mps * 3.6).toFixed(1) : '--';
                          const timeLoss = c.avg_time_loss_ms != null ? c.avg_time_loss_ms.toFixed(0) : '--';
                          const lossColor = c.avg_time_loss_ms != null
                            ? c.avg_time_loss_ms < 50 ? 'text-acid-green'
                            : c.avg_time_loss_ms < 150 ? 'text-amber-400'
                            : 'text-safety-red'
                            : 'text-steel';
                          return (
                            <tr
                              key={c.corner_id}
                              className={`border-b border-steel/5 hover:bg-steel/5 transition-colors cursor-pointer ${
                                selectedCorner === c.corner_id ? 'bg-acid-green/5' : ''
                              }`}
                              onClick={() => setSelectedCorner(c.corner_id)}
                            >
                              <td className="px-4 py-2.5 font-telemetry text-chalk">T{c.corner_id}</td>
                              <td className="px-4 py-2.5 font-telemetry text-chalk text-right">{toKmh(c.avg_entry_speed_mps)} km/h</td>
                              <td className="px-4 py-2.5 font-telemetry text-chalk text-right">{toKmh(c.avg_apex_speed_mps)} km/h</td>
                              <td className="px-4 py-2.5 font-telemetry text-chalk text-right">{toKmh(c.avg_exit_speed_mps)} km/h</td>
                              <td className={`px-4 py-2.5 font-telemetry text-right ${lossColor}`}>{timeLoss} ms</td>
                              <td className="px-4 py-2.5 font-body text-steel text-xs max-w-[200px] truncate">
                                {c.coaching_hint || '--'}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              </section>
            )}

            {/* Corner Mastery Chart */}
            <section>
              <SectionHeader title="Corner Mastery" />
              <CornerMastery sessionId={id} />
            </section>

            {/* Brake Precision + Consistency (hidden on corners tab of old tool) */}
            <section>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <BrakeScatter sessionId={id} />
                <ConsistencyHeatmap sessionId={id} />
              </div>
            </section>
          </div>
        )}

        {/* ─────────── Tab 3: Performance ─────────── */}
        {activeTab === 'Performance' && (
          <div className="space-y-8">
            {/* Charts 2x2 */}
            <section>
              <SectionHeader title="Lap Performance" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <LapProgress sessionId={id} />
                <SectorChart sessionId={id} />
                <LapDistribution sessionId={id} />
                <LapOverlay sessionId={id} />
              </div>
            </section>

            {/* Stint Analysis — Cards + Chart */}
            <section>
              <SectionHeader title="Stint Analysis" />
              {/* Stint Cards */}
              {(stintData?.stints ?? []).length > 0 && (
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3 mb-4">
                  {stintData!.stints.map((stint) => {
                    const cv = stint.avg_time > 0 && stint.laps_count > 1
                      ? ((stint.avg_time - stint.best_time) / stint.avg_time * 100)
                      : 0;
                    // Fade: compare first and last stint to detect tyre deg
                    const stints = stintData!.stints;
                    const isLast = stint.stint_number === stints[stints.length - 1].stint_number;
                    const fade = isLast && stints.length > 1
                      ? ((stint.avg_time - stints[0].avg_time) / stints[0].avg_time * 100)
                      : null;
                    return (
                      <div
                        key={stint.stint_number}
                        className="bg-concrete rounded-lg border border-steel/10 p-3"
                      >
                        <div className="flex items-center justify-between mb-2">
                          <span className="font-telemetry text-xs text-steel">Stint {stint.stint_number}</span>
                          <span className="font-telemetry text-[10px] text-steel/60">
                            L{stint.start_lap}-{stint.end_lap}
                          </span>
                        </div>
                        <p className="font-telemetry text-sm text-acid-green font-bold mb-1">
                          {formatTime(stint.best_time)}
                        </p>
                        <div className="space-y-1 text-[10px] font-telemetry">
                          <div className="flex justify-between">
                            <span className="text-steel">Mean</span>
                            <span className="text-chalk">{formatTime(stint.avg_time)}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-steel">CV%</span>
                            <span className={cv < 1 ? 'text-acid-green' : cv < 3 ? 'text-amber-400' : 'text-safety-red'}>
                              {cv.toFixed(1)}%
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-steel">Laps</span>
                            <span className="text-chalk">{stint.laps_count}</span>
                          </div>
                          {fade != null && (
                            <div className="flex justify-between pt-1 border-t border-steel/10">
                              <span className="text-steel">Fade</span>
                              <span className={fade < 1 ? 'text-acid-green' : fade < 3 ? 'text-amber-400' : 'text-safety-red'}>
                                +{fade.toFixed(1)}%
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Stint Pace Chart */}
              <StintChart sessionId={id} />

              {/* Tyre Cliff Detection */}
              {(stintData?.stints ?? []).length >= 2 && (() => {
                const s = stintData!.stints;
                const lastStint = s[s.length - 1];
                const firstStint = s[0];
                const fadeRate = ((lastStint.avg_time - firstStint.avg_time) / firstStint.avg_time) * 100;
                if (fadeRate <= 0.5) return null;
                const severity = fadeRate > 5 ? 'critical' : fadeRate > 2 ? 'moderate' : 'mild';
                const severityColor = {
                  critical: 'border-safety-red/30 bg-safety-red/5',
                  moderate: 'border-amber-400/30 bg-amber-400/5',
                  mild: 'border-steel/20 bg-steel/5',
                }[severity];
                return (
                  <div className={`mt-4 rounded-lg border p-4 ${severityColor}`}>
                    <div className="flex items-center gap-2 mb-2">
                      <span className={`w-2 h-2 rounded-full ${
                        severity === 'critical' ? 'bg-safety-red' : severity === 'moderate' ? 'bg-amber-400' : 'bg-steel'
                      }`} />
                      <h4 className="font-telemetry text-xs uppercase tracking-wider text-chalk">
                        Tyre Cliff Detection — {severity.toUpperCase()}
                      </h4>
                    </div>
                    <p className="text-chalk text-sm font-body">
                      {severity === 'critical'
                        ? `Significant pace fade of +${fadeRate.toFixed(1)}% from stint 1 to stint ${s.length}. Tyre degradation is severely affecting lap times. Consider shorter stints or different tyre management strategy.`
                        : severity === 'moderate'
                          ? `Moderate pace fade of +${fadeRate.toFixed(1)}% detected. Tyre performance is declining but manageable. Focus on smoother inputs to preserve rubber.`
                          : `Mild pace fade of +${fadeRate.toFixed(1)}% — tyre management is acceptable. Minor adjustments could extend tyre life further.`
                      }
                    </p>
                  </div>
                );
              })()}
            </section>

            {/* Tyre Chart (full width) */}
            <section>
              <SectionHeader title="Tyre Degradation" />
              <TyreChart sessionId={id} />
            </section>

            {/* Trend Analysis */}
            <section>
              <SectionHeader title="Pace Trend" />
              <TrendChart sessionId={id} />
            </section>

            {/* Race Strategy — pit window and rival gap */}
            <section>
              <SectionHeader title="Race Strategy" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <PitWindowChart sessionId={id} />
                <RivalChart sessionId={id} />
              </div>
            </section>
          </div>
        )}

        {/* ─────────── Tab 4: Analytics ─────────── */}
        {activeTab === 'Analytics' && (
          <div className="space-y-8">
            {/* Data Quality & Conditions Panel */}
            {(session.data_health || session.weather) && (
              <section>
                <SectionHeader title="Session Context" />
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {session.data_health && (
                    <div className="bg-concrete rounded-lg border border-steel/10 p-4">
                      <h4 className="text-steel font-telemetry text-xs uppercase tracking-wider mb-3">Data Quality</h4>
                      <div className="grid grid-cols-2 gap-3">
                        {session.data_health.gps_quality != null && (
                          <div>
                            <span className="text-steel/60 text-[10px] font-telemetry block">GPS Quality</span>
                            <span className={`font-telemetry text-sm ${session.data_health.gps_quality > 0.8 ? 'text-acid-green' : session.data_health.gps_quality > 0.5 ? 'text-amber-400' : 'text-safety-red'}`}>
                              {(session.data_health.gps_quality * 100).toFixed(0)}%
                            </span>
                          </div>
                        )}
                        {session.data_health.sampling_rate_hz != null && (
                          <div>
                            <span className="text-steel/60 text-[10px] font-telemetry block">Sample Rate</span>
                            <span className="text-chalk font-telemetry text-sm">{session.data_health.sampling_rate_hz} Hz</span>
                          </div>
                        )}
                        {session.data_health.total_points != null && (
                          <div>
                            <span className="text-steel/60 text-[10px] font-telemetry block">Data Points</span>
                            <span className="text-chalk font-telemetry text-sm">{session.data_health.total_points.toLocaleString()}</span>
                          </div>
                        )}
                        {session.data_health.gps_coverage_pct != null && (
                          <div>
                            <span className="text-steel/60 text-[10px] font-telemetry block">GPS Coverage</span>
                            <span className="text-chalk font-telemetry text-sm">{(session.data_health.gps_coverage_pct * 100).toFixed(0)}%</span>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                  {session.weather && (
                    <div className="bg-concrete rounded-lg border border-steel/10 p-4">
                      <h4 className="text-steel font-telemetry text-xs uppercase tracking-wider mb-3">Weather</h4>
                      <div className="grid grid-cols-2 gap-3">
                        {session.weather.conditions && (
                          <div>
                            <span className="text-steel/60 text-[10px] font-telemetry block">Conditions</span>
                            <span className="text-chalk font-telemetry text-sm capitalize">{session.weather.conditions}</span>
                          </div>
                        )}
                        {session.weather.temperature_c != null && (
                          <div>
                            <span className="text-steel/60 text-[10px] font-telemetry block">Temperature</span>
                            <span className="text-chalk font-telemetry text-sm">{session.weather.temperature_c}°C</span>
                          </div>
                        )}
                        {session.weather.humidity_pct != null && (
                          <div>
                            <span className="text-steel/60 text-[10px] font-telemetry block">Humidity</span>
                            <span className="text-chalk font-telemetry text-sm">{session.weather.humidity_pct}%</span>
                          </div>
                        )}
                        {session.weather.wind_speed_ms != null && (
                          <div>
                            <span className="text-steel/60 text-[10px] font-telemetry block">Wind</span>
                            <span className="text-chalk font-telemetry text-sm">{(session.weather.wind_speed_ms * 3.6).toFixed(0)} km/h</span>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* Driving Style — braking, cornering, consistency fingerprint */}
            <section>
              <SectionHeader title="Driving Style" />
              <p className="text-steel/60 text-xs font-telemetry mb-3 -mt-2">
                Driver fingerprint, braking patterns, corner technique, and lap consistency
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Fingerprint sessionId={id} />
                <DrivingStyle sessionId={id} />
                <BrakeScatter sessionId={id} />
                <CornerMastery sessionId={id} />
              </div>
            </section>

            {/* Vehicle Physics — energy, fatigue, speed envelope, throttle */}
            <section>
              <SectionHeader title="Vehicle Physics" />
              <p className="text-steel/60 text-xs font-telemetry mb-3 -mt-2">
                Energy balance, fatigue patterns, speed profile, and throttle application
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <EnergyBalance sessionId={id} />
                <FatigueChart sessionId={id} />
                <SpeedProfile sessionId={id} />
                <ThrottleHeatmap sessionId={id} />
              </div>
            </section>

            {/* Conditions & Trends — weather impact, progression, consistency heatmap */}
            <section>
              <SectionHeader title="Conditions & Trends" />
              <p className="text-steel/60 text-xs font-telemetry mb-3 -mt-2">
                Session progression, weather impact, tyre behavior, and workload analysis
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                <TrendChart sessionId={id} />
                <ConsistencyHeatmap sessionId={id} />
                <WorkloadChart sessionId={id} />
                <WeatherChart sessionId={id} />
                <TyreChart sessionId={id} />
                <StintChart sessionId={id} />
              </div>
            </section>

            {/* Multi-Metric Comparison */}
            <section>
              <SectionHeader title="Multi-Metric Comparison" />
              <ComparisonMatrix sessionId={id} />
            </section>
          </div>
        )}

        {/* ─────────── Tab 5: Lap Data ─────────── */}
        {activeTab === 'Lap Data' && (
          <div className="space-y-8">
            {/* 8-Stat KPI Row — matches old tool */}
            <section>
              <SectionHeader title="Lap Statistics" />
              <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-8 gap-3">
                <StatCard label="Best Lap" value={formatTime(bestTime)} trend="up" />
                <StatCard label="Mean Lap" value={formatTime(meanTime)} trend="neutral" />
                <StatCard
                  label="Std Dev"
                  value={lapStdDev != null ? `${lapStdDev.toFixed(3)}s` : '--'}
                />
                <StatCard
                  label="Consistency"
                  value={consistencyPct != null ? `${consistencyPct.toFixed(1)}%` : '--'}
                  trend={
                    consistencyPct != null
                      ? consistencyPct >= 95 ? 'up' : consistencyPct >= 90 ? 'neutral' : 'down'
                      : 'neutral'
                  }
                />
                <StatCard
                  label="Best→Mean"
                  value={bestVsMeanGap != null ? `${bestVsMeanGap.toFixed(2)}%` : '--'}
                  trend={bestVsMeanGap != null ? (bestVsMeanGap < 2 ? 'up' : bestVsMeanGap < 5 ? 'neutral' : 'down') : 'neutral'}
                />
                <StatCard
                  label="Top 25%"
                  value={formatTime(top25Avg ?? null)}
                />
                <StatCard
                  label="Improvement"
                  value={
                    improvementTrend != null
                      ? `${improvementTrend > 0 ? '+' : ''}${improvementTrend.toFixed(3)}s`
                      : '--'
                  }
                  trend={
                    improvementTrend != null
                      ? improvementTrend > 0 ? 'up' : improvementTrend < 0 ? 'down' : 'neutral'
                      : 'neutral'
                  }
                />
                <StatCard
                  label="Valid Laps"
                  value={`${validLapCount}/${laps.length}`}
                  trend={validLapCount === laps.length ? 'up' : 'neutral'}
                />
              </div>
            </section>

            {/* Lap Charts — Bar + Distribution side by side */}
            <section>
              <SectionHeader title="Lap Times" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <LapProgress sessionId={id} />
                <LapDistribution sessionId={id} />
              </div>
            </section>

            {/* Condition Phases */}
            {(session.condition_phases?.length ?? 0) > 0 && (
              <section>
                <SectionHeader title="Track Condition Phases" />
                <div className="flex flex-wrap gap-3">
                  {session.condition_phases!.map((phase) => {
                    const labelLower = phase.label.toLowerCase();
                    const borderColor = labelLower.includes('dry') ? 'border-t-emerald-400'
                      : labelLower.includes('wet') ? 'border-t-blue-400'
                      : labelLower.includes('damp') ? 'border-t-amber-400'
                      : 'border-t-purple-400';
                    const textColor = labelLower.includes('dry') ? 'text-emerald-400'
                      : labelLower.includes('wet') ? 'text-blue-400'
                      : labelLower.includes('damp') ? 'text-amber-400'
                      : 'text-purple-400';
                    return (
                      <div
                        key={phase.phase_id}
                        className={`bg-concrete/60 backdrop-blur rounded-lg border border-steel/10 ${borderColor} border-t-2 p-4 min-w-[160px] hover:-translate-y-0.5 transition-transform`}
                      >
                        <div className={`font-telemetry text-sm font-semibold ${textColor} mb-1`}>
                          {phase.label}
                        </div>
                        <div className="text-steel text-xs font-telemetry mb-2">
                          Laps {phase.lap_start}–{phase.lap_end}
                        </div>
                        {phase.median_pace_s != null && (
                          <div className="text-chalk text-sm font-telemetry">
                            Median: {formatTime(phase.median_pace_s)}
                          </div>
                        )}
                        {phase.confidence != null && (
                          <div className="text-steel/60 text-[10px] font-telemetry mt-1">
                            {(phase.confidence * 100).toFixed(0)}% confidence
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {/* Full Data Table */}
            <section>
              <SectionHeader title="All Laps" />
              {laps.length > 0 ? (
                <DataTable
                  columns={lapColumns}
                  data={laps}
                  keyField="lap_number"
                  rowClassName={(row: LapRow) =>
                    row.is_best
                      ? 'bg-acid-green/5 hover:bg-acid-green/10'
                      : !row.valid
                        ? 'opacity-50'
                        : ''
                  }
                />
              ) : (
                <div className="bg-carbon-light rounded-lg border border-steel/10 p-8 text-center">
                  <p className="text-steel font-body">No lap data available for this session.</p>
                </div>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
