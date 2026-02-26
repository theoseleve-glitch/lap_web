'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, ChartPanel } from '@/components/app';

/* ---------- types ---------- */

interface SessionOption {
  id: string;
  label: string;
}

interface SessionMetrics {
  id: string;
  track_name: string;
  driver_name: string;
  date: string;
  laps: number;
  best_time: number | null;
  score: number | null;
  grade: string | null;
  pace_score: number | null;
  consistency_score: number | null;
  execution_score: number | null;
  robustness_score: number | null;
}

interface CompareSessionsResponse {
  session_a: SessionMetrics;
  session_b: SessionMetrics;
}

interface SessionListResponse {
  sessions: SessionOption[];
}

/* ---------- helpers ---------- */

function formatTime(s: number | null): string {
  if (s == null) return '--';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function diffIndicator(a: number | null, b: number | null, lowerIsBetter = false) {
  if (a == null || b == null) return null;
  const diff = b - a;
  if (Math.abs(diff) < 0.001) return null;
  const better = lowerIsBetter ? diff > 0 : diff < 0;
  return (
    <span className={`font-telemetry text-xs ${better ? 'text-acid-green' : 'text-safety-red'}`}>
      {better ? '▲' : '▼'} {Math.abs(diff).toFixed(2)}
    </span>
  );
}

/* ---------- component ---------- */

export default function CompareSessionsPage() {
  const [sessionA, setSessionA] = useState('');
  const [sessionB, setSessionB] = useState('');
  const [searchA, setSearchA] = useState('');
  const [searchB, setSearchB] = useState('');

  const { data: sessionList } = useQuery({
    queryKey: ['sessions-list'],
    queryFn: () => api.get<SessionListResponse>('/sessions'),
  });

  const sessions = sessionList?.sessions ?? [];
  const filteredA = sessions.filter((s) =>
    s.label.toLowerCase().includes(searchA.toLowerCase()),
  );
  const filteredB = sessions.filter((s) =>
    s.label.toLowerCase().includes(searchB.toLowerCase()),
  );

  const canCompare = sessionA !== '' && sessionB !== '' && sessionA !== sessionB;

  const { data: comparison, isLoading: comparing } = useQuery({
    queryKey: ['compare-sessions', sessionA, sessionB],
    queryFn: () =>
      api.get<CompareSessionsResponse>(`/compare/sessions?a=${sessionA}&b=${sessionB}`),
    enabled: canCompare,
  });

  const a = comparison?.session_a;
  const b = comparison?.session_b;

  return (
    <div>
      <PageHeader
        title="Compare Sessions"
        subtitle="Select two sessions to compare side-by-side"
      />

      {/* Session selectors */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        {/* Session A */}
        <div className="bg-concrete rounded-lg border border-steel/20 p-4">
          <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-2">
            Session A
          </label>
          <input
            type="text"
            placeholder="Search sessions..."
            value={searchA}
            onChange={(e) => setSearchA(e.target.value)}
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
              placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
              transition-colors mb-2"
          />
          <select
            value={sessionA}
            onChange={(e) => setSessionA(e.target.value)}
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
              focus:outline-none focus:border-pit-orange transition-colors"
          >
            <option value="">Select session...</option>
            {filteredA.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </div>

        {/* Session B */}
        <div className="bg-concrete rounded-lg border border-steel/20 p-4">
          <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-2">
            Session B
          </label>
          <input
            type="text"
            placeholder="Search sessions..."
            value={searchB}
            onChange={(e) => setSearchB(e.target.value)}
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
              placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
              transition-colors mb-2"
          />
          <select
            value={sessionB}
            onChange={(e) => setSessionB(e.target.value)}
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
              focus:outline-none focus:border-pit-orange transition-colors"
          >
            <option value="">Select session...</option>
            {filteredB.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Comparison results */}
      {comparing && (
        <div className="flex items-center justify-center h-32">
          <div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      )}

      {a && b && (
        <>
          {/* Session headers */}
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div className="bg-concrete rounded-lg border border-acid-green/30 p-3">
              <p className="font-monument text-sm text-acid-green">{a.track_name}</p>
              <p className="text-steel font-telemetry text-xs">
                {a.driver_name} &middot; {a.date}
              </p>
            </div>
            <div className="bg-concrete rounded-lg border border-pit-orange/30 p-3">
              <p className="font-monument text-sm text-pit-orange">{b.track_name}</p>
              <p className="text-steel font-telemetry text-xs">
                {b.driver_name} &middot; {b.date}
              </p>
            </div>
          </div>

          {/* Key metrics */}
          <h2 className="font-body text-chalk text-lg mb-3">Key Metrics</h2>
          <div className="grid grid-cols-2 gap-4 mb-6">
            <div className="space-y-4">
              <StatCard label="Best Time" value={formatTime(a.best_time)} />
              <StatCard label="Score" value={a.score?.toFixed(1) ?? '--'} unit="/100" />
              <StatCard label="Laps" value={a.laps} />
              <StatCard label="Grade" value={a.grade ?? '--'} />
            </div>
            <div className="space-y-4">
              <div className="relative">
                <StatCard label="Best Time" value={formatTime(b.best_time)} />
                <div className="absolute top-2 right-3">
                  {diffIndicator(a.best_time, b.best_time, true)}
                </div>
              </div>
              <div className="relative">
                <StatCard label="Score" value={b.score?.toFixed(1) ?? '--'} unit="/100" />
                <div className="absolute top-2 right-3">
                  {diffIndicator(a.score, b.score)}
                </div>
              </div>
              <StatCard label="Laps" value={b.laps} />
              <StatCard label="Grade" value={b.grade ?? '--'} />
            </div>
          </div>

          {/* Score breakdown */}
          <h2 className="font-body text-chalk text-lg mb-3">Score Breakdown</h2>
          <div className="grid grid-cols-2 gap-4 mb-6">
            <div className="grid grid-cols-2 gap-3">
              <StatCard label="Pace" value={a.pace_score?.toFixed(1) ?? '--'} unit="/25" />
              <StatCard label="Consistency" value={a.consistency_score?.toFixed(1) ?? '--'} unit="/25" />
              <StatCard label="Execution" value={a.execution_score?.toFixed(1) ?? '--'} unit="/25" />
              <StatCard label="Robustness" value={a.robustness_score?.toFixed(1) ?? '--'} unit="/25" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="relative">
                <StatCard label="Pace" value={b.pace_score?.toFixed(1) ?? '--'} unit="/25" />
                <div className="absolute top-2 right-3">
                  {diffIndicator(a.pace_score, b.pace_score)}
                </div>
              </div>
              <div className="relative">
                <StatCard label="Consistency" value={b.consistency_score?.toFixed(1) ?? '--'} unit="/25" />
                <div className="absolute top-2 right-3">
                  {diffIndicator(a.consistency_score, b.consistency_score)}
                </div>
              </div>
              <div className="relative">
                <StatCard label="Execution" value={b.execution_score?.toFixed(1) ?? '--'} unit="/25" />
                <div className="absolute top-2 right-3">
                  {diffIndicator(a.execution_score, b.execution_score)}
                </div>
              </div>
              <div className="relative">
                <StatCard label="Robustness" value={b.robustness_score?.toFixed(1) ?? '--'} unit="/25" />
                <div className="absolute top-2 right-3">
                  {diffIndicator(a.robustness_score, b.robustness_score)}
                </div>
              </div>
            </div>
          </div>

          {/* Overlay chart placeholder */}
          <ChartPanel
            title="Lap Time Overlay"
            subtitle="Session A (green) vs Session B (orange)"
          >
            <div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">
              Overlay chart will render once data is connected
            </div>
          </ChartPanel>
        </>
      )}

      {!canCompare && !comparing && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          <p className="text-steel font-body">
            Select two different sessions above to begin comparison.
          </p>
        </div>
      )}
    </div>
  );
}
