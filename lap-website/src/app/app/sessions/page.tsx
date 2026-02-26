'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, DataTable } from '@/components/app';

interface SessionRow {
  id: string;
  date: string;
  track_name: string;
  driver_name: string;
  laps: number;
  best_time: number | null;
  score: number | null;
  grade: string | null;
}

interface BrowseResponse {
  sessions: SessionRow[];
  total: number;
  avg_score: number | null;
  best_lap: number | null;
  active_drivers: number;
}

function formatLapTime(seconds: number | null): string {
  if (seconds == null) return '—';
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toFixed(3).padStart(6, '0')}`;
}

function gradeColor(score: number | null): string {
  if (score == null) return 'text-steel';
  if (score >= 80) return 'text-acid-green';
  if (score >= 60) return 'text-marshal-yellow';
  return 'text-safety-red';
}

export default function SessionsPage() {
  const router = useRouter();
  const [search, setSearch] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['sessions', 'browse', search],
    queryFn: () =>
      api.get<BrowseResponse>(
        `/sessions/browse${search ? `?q=${encodeURIComponent(search)}` : ''}`,
      ),
  });

  const sessions = data?.sessions ?? [];

  const columns = [
    {
      key: 'date',
      header: 'Date',
      sortable: true,
      className: 'font-telemetry',
    },
    {
      key: 'track_name',
      header: 'Track',
      sortable: true,
    },
    {
      key: 'driver_name',
      header: 'Driver',
      sortable: true,
    },
    {
      key: 'laps',
      header: 'Laps',
      sortable: true,
      className: 'font-telemetry text-right',
    },
    {
      key: 'best_time',
      header: 'Best Time',
      sortable: true,
      className: 'font-telemetry',
      render: (row: SessionRow) => (
        <span className="text-acid-green">{formatLapTime(row.best_time)}</span>
      ),
    },
    {
      key: 'score',
      header: 'Score',
      sortable: true,
      className: 'font-telemetry text-right',
      render: (row: SessionRow) => (
        <span className={gradeColor(row.score)}>
          {row.score != null ? row.score.toFixed(1) : '—'}
        </span>
      ),
    },
    {
      key: 'grade',
      header: 'Grade',
      className: 'font-telemetry',
      render: (row: SessionRow) => (
        <span className={`font-monument text-lg ${gradeColor(row.score)}`}>
          {row.grade ?? '—'}
        </span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Sessions"
        subtitle={`${data?.total ?? 0} sessions`}
      />

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Total Sessions" value={data?.total ?? 0} />
        <StatCard
          label="Avg Score"
          value={data?.avg_score != null ? data.avg_score.toFixed(1) : '—'}
          unit="/100"
        />
        <StatCard
          label="Best Lap"
          value={formatLapTime(data?.best_lap ?? null)}
        />
        <StatCard label="Active Drivers" value={data?.active_drivers ?? 0} />
      </div>

      {/* Search */}
      <div className="mb-6">
        <input
          type="text"
          placeholder="Search sessions by track, driver..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full max-w-md bg-concrete border border-steel/30 rounded px-4 py-2.5 text-chalk font-body text-sm
            placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        />
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-48">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      ) : (
        <DataTable
          columns={columns}
          data={sessions}
          keyField="id"
          onRowClick={(row) => router.push(`/app/sessions/${row.id}`)}
          emptyMessage="No sessions found"
        />
      )}
    </div>
  );
}
