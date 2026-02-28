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
}

interface LapRow {
  lap_number: number;
  time: number;
  speed_avg: number | null;
  speed_max: number | null;
  max_braking: number | null;
  max_accel: number | null;
  valid: boolean;
}

interface CoachingMetric {
  name: string;
  value: number;
  max: number;
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

/* ─── Score Bar Component ─────────────────────────────────────────────── */

function ScoreBar({ label, value, max = 25 }: { label: string; value: number | null; max?: number }) {
  const pct = value != null ? (value / max) * 100 : 0;
  const color = pct >= 75 ? 'bg-acid-green' : pct >= 50 ? 'bg-amber-400' : 'bg-safety-red';
  return (
    <div className="flex items-center gap-3">
      <span className="text-steel text-sm w-28 font-body">{label}</span>
      <div className="flex-1 h-3 bg-carbon rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-chalk font-telemetry text-sm w-14 text-right">
        {value?.toFixed(1) ?? '--'}/{max}
      </span>
    </div>
  );
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
    queryFn: () => api.get<{ metrics: CoachingMetric[] }>(`/sessions/${id}/fingerprint`),
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
    },
    {
      key: 'time',
      header: 'Time',
      sortable: true,
      className: 'font-telemetry',
      render: (row: LapRow) => {
        const isBest = row.valid && row.time === bestTime;
        return (
          <span className={isBest ? 'text-acid-green font-semibold' : 'text-chalk'}>
            {formatTime(row.time)}
            {isBest && <span className="ml-2 text-xs text-acid-green/70">BEST</span>}
          </span>
        );
      },
    },
    {
      key: 'speed_avg',
      header: 'Avg Speed',
      sortable: true,
      className: 'font-telemetry',
      render: (row: LapRow) => (
        <span>{row.speed_avg != null ? `${row.speed_avg.toFixed(1)} km/h` : '--'}</span>
      ),
    },
    {
      key: 'speed_max',
      header: 'Max Speed',
      sortable: true,
      className: 'font-telemetry',
      render: (row: LapRow) => (
        <span>{row.speed_max != null ? `${row.speed_max.toFixed(1)} km/h` : '--'}</span>
      ),
    },
    {
      key: 'max_braking',
      header: 'Max Brake (G)',
      sortable: true,
      className: 'font-telemetry',
      render: (row: LapRow) => (
        <span>{row.max_braking != null ? row.max_braking.toFixed(2) : '--'}</span>
      ),
    },
    {
      key: 'max_accel',
      header: 'Max Accel (G)',
      sortable: true,
      className: 'font-telemetry',
      render: (row: LapRow) => (
        <span>{row.max_accel != null ? row.max_accel.toFixed(2) : '--'}</span>
      ),
    },
    {
      key: 'valid',
      header: 'Valid',
      className: 'font-telemetry w-16',
      render: (row: LapRow) => (
        <span className={row.valid ? 'text-acid-green' : 'text-safety-red'}>
          {row.valid ? 'Y' : 'N'}
        </span>
      ),
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
            {/* Score Breakdown */}
            <section>
              <SectionHeader title="Score Breakdown" />
              <div className="bg-carbon-light rounded-lg border border-steel/10 p-5 space-y-3">
                <ScoreBar label="Pace" value={session.pace_score} />
                <ScoreBar label="Consistency" value={session.consistency_score} />
                <ScoreBar label="Execution" value={session.execution_score} />
                <ScoreBar label="Robustness" value={session.robustness_score} />
                <div className="pt-2 border-t border-steel/10 flex items-center justify-between">
                  <span className="text-steel text-sm font-body">Total</span>
                  <span className="font-monument text-xl text-acid-green">
                    {session.score?.toFixed(1) ?? '--'}
                    <span className="text-steel text-sm font-telemetry">/100</span>
                  </span>
                </div>
              </div>
            </section>

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
                  {coachingData!.metrics.slice(0, 6).map((metric) => {
                    const pct = metric.max > 0 ? (metric.value / metric.max) * 100 : 0;
                    const needsWork = pct < 60;
                    return (
                      <div
                        key={metric.name}
                        className={`bg-carbon-light rounded-lg border p-4 ${
                          needsWork ? 'border-amber-400/30' : 'border-steel/10'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <span className="font-body text-chalk text-sm">{metric.name}</span>
                          <span className="font-telemetry text-xs text-steel">
                            {metric.value.toFixed(1)}/{metric.max}
                          </span>
                        </div>
                        <div className="h-2 bg-carbon rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${pct >= 75 ? 'bg-acid-green' : pct >= 50 ? 'bg-amber-400' : 'bg-safety-red'}`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        {needsWork && (
                          <p className="text-amber-400/80 text-xs font-body mt-2">
                            Focus area for next session
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>
              </section>
            )}
          </div>
        )}

        {/* ─────────── Tab 2: Corners & Coaching ─────────── */}
        {activeTab === 'Corners & Coaching' && (
          <div className="space-y-8">
            {/* Corner Replay (full width) */}
            <section>
              <div className="flex items-center justify-between mb-4 mt-2">
                <h3 className="font-body text-chalk text-lg font-semibold">Corner Replay</h3>
                <div className="flex items-center gap-2">
                  <label className="text-steel font-telemetry text-xs">Corner:</label>
                  <input
                    type="number"
                    min={1}
                    value={selectedCorner}
                    onChange={(e) => setSelectedCorner(Math.max(1, parseInt(e.target.value) || 1))}
                    className="w-16 bg-carbon border border-steel/20 rounded px-2 py-1 text-chalk font-telemetry text-sm focus:border-acid-green focus:outline-none"
                  />
                </div>
              </div>
              <div className="bg-carbon-light rounded-lg border border-steel/10 p-4 min-h-[400px]">
                <CornerReplay sessionId={id} cornerId={selectedCorner} />
              </div>
            </section>

            {/* Corner Mastery Chart */}
            <section>
              <SectionHeader title="Corner Mastery" />
              <CornerMastery sessionId={id} />
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

            {/* Stint Chart (full width) */}
            <section>
              <SectionHeader title="Stint Analysis" />
              <StintChart sessionId={id} />
            </section>

            {/* Tyre Chart (full width) */}
            <section>
              <SectionHeader title="Tyre Degradation" />
              <TyreChart sessionId={id} />
            </section>
          </div>
        )}

        {/* ─────────── Tab 4: Analytics ─────────── */}
        {activeTab === 'Analytics' && (
          <div className="space-y-8">
            {/* Style Section 2x2 */}
            <section>
              <SectionHeader title="Style" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Fingerprint sessionId={id} />
                <ConsistencyHeatmap sessionId={id} />
                <BrakeScatter sessionId={id} />
                <CornerMastery sessionId={id} />
              </div>
            </section>

            {/* Physics Section 2x2 */}
            <section>
              <SectionHeader title="Physics" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <EnergyBalance sessionId={id} />
                <FatigueChart sessionId={id} />
                <SpeedProfile sessionId={id} />
                <ThrottleHeatmap sessionId={id} />
              </div>
            </section>

            {/* Advanced Section */}
            <section>
              <SectionHeader title="Advanced" />
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                <WorkloadChart sessionId={id} />
                <TrendChart sessionId={id} />
                <WeatherChart sessionId={id} />
              </div>
            </section>
          </div>
        )}

        {/* ─────────── Tab 5: Lap Data ─────────── */}
        {activeTab === 'Lap Data' && (
          <div className="space-y-8">
            {/* Lap Stats Row */}
            <section>
              <SectionHeader title="Lap Statistics" />
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
                <StatCard label="Best" value={formatTime(bestTime)} trend="up" />
                <StatCard label="Mean" value={formatTime(meanTime)} trend="neutral" />
                <StatCard
                  label="Std Dev"
                  value={lapStdDev != null ? `${lapStdDev.toFixed(3)}s` : '--'}
                />
                <StatCard
                  label="Consistency"
                  value={consistencyPct != null ? `${consistencyPct.toFixed(1)}%` : '--'}
                  trend={
                    consistencyPct != null
                      ? consistencyPct >= 95
                        ? 'up'
                        : consistencyPct >= 90
                          ? 'neutral'
                          : 'down'
                      : 'neutral'
                  }
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
                      ? improvementTrend > 0
                        ? 'up'
                        : improvementTrend < 0
                          ? 'down'
                          : 'neutral'
                      : 'neutral'
                  }
                />
              </div>
            </section>

            {/* Lap Times Bar Chart */}
            <section>
              <SectionHeader title="Lap Times" />
              <LapProgress sessionId={id} />
            </section>

            {/* Full Data Table */}
            <section>
              <SectionHeader title="All Laps" />
              {laps.length > 0 ? (
                <DataTable columns={lapColumns} data={laps} keyField="lap_number" />
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
