'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useState, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { DataTable, QueryError, SkeletonTableRows, StatCard } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';

/* -- Types ---------------------------------------------------- */

interface LeaderboardEntry {
  session_id: string;
  session_date: string;
  best_lap_time_s: number;
  total_score: number;
  track_state: string;
  n_laps: number;
  driver_name: string;
  track_name: string;
  track_id: number;
}

interface TrackOption {
  id: string | number;
  name: string;
}

interface DriverOption {
  id: string | number;
  name: string;
}

/* -- Helpers --------------------------------------------------- */

function formatLapTime(seconds: number | null): string {
  if (!seconds) return '\u2014';
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return mins > 0 ? `${mins}:${secs.toFixed(3).padStart(6, '0')}` : `${secs.toFixed(3)}`;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '\u2014';
  try {
    const d = new Date(dateStr + 'T00:00:00');
    return d.toLocaleDateString('en-GB', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    });
  } catch {
    return dateStr;
  }
}

function scoreToGrade(score: number | null): string {
  if (score == null) return '\u2014';
  if (score >= 90) return 'S';
  if (score >= 80) return 'A';
  if (score >= 65) return 'B';
  if (score >= 50) return 'C';
  if (score >= 35) return 'D';
  return 'F';
}

const GRADE_COLORS: Record<string, string> = {
  'S': 'bg-yellow-500/20 text-yellow-400',
  'A': 'bg-emerald-500/20 text-emerald-400',
  'B': 'bg-blue-500/20 text-blue-400',
  'C': 'bg-amber-500/20 text-amber-400',
  'D': 'bg-red-500/20 text-red-400',
  'F': 'bg-red-500/20 text-red-300',
};

function scoreColor(score: number | null): string {
  if (score == null) return 'text-steel';
  if (score >= 80) return 'text-acid-green';
  if (score >= 60) return 'text-marshal-yellow';
  if (score >= 40) return 'text-pit-orange';
  return 'text-safety-red';
}

function GradeBadge({ score }: { score: number | null }) {
  const grade = scoreToGrade(score);
  if (grade === '\u2014') return <span className="text-steel/60">{grade}</span>;
  const colorClass = GRADE_COLORS[grade] ?? 'bg-steel/10 text-steel';
  return (
    <span
      className={`inline-flex items-center justify-center w-7 h-7 rounded-md font-monument text-xs ${colorClass}`}
    >
      {grade}
    </span>
  );
}

function ConditionBadge({ condition }: { condition: string | null }) {
  if (!condition) return <span className="text-steel/60">{'\u2014'}</span>;
  const styles: Record<string, { bg: string; text: string }> = {
    dry:      { bg: 'bg-acid-green/10', text: 'text-acid-green' },
    wet:      { bg: 'bg-blue-400/10', text: 'text-blue-400' },
    damp:     { bg: 'bg-marshal-yellow/10', text: 'text-marshal-yellow' },
    mixed:    { bg: 'bg-purple-400/10', text: 'text-purple-400' },
    green:    { bg: 'bg-emerald-400/10', text: 'text-emerald-400' },
    rubbered: { bg: 'bg-zinc-400/10', text: 'text-zinc-400' },
    dusty:    { bg: 'bg-amber-400/10', text: 'text-amber-400' },
  };
  const s = styles[condition] ?? { bg: 'bg-steel/10', text: 'text-steel' };
  return (
    <span
      className={`inline-flex px-2 py-0.5 rounded text-[10px] font-telemetry uppercase tracking-wider ${s.bg} ${s.text}`}
    >
      {condition}
    </span>
  );
}

/* -- Filter Select --------------------------------------------- */

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="bg-asphalt border border-steel/20 text-chalk text-xs font-telemetry rounded px-3 py-2
        focus:border-acid-green/40 focus:outline-none transition-colors"
      aria-label={label}
    >
      <option value="">All {label}s</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

/* -- Page Component -------------------------------------------- */

export default function LeaderboardPage() {
  const router = useRouter();

  const [trackFilter, setTrackFilter] = useState('');
  const [driverFilter, setDriverFilter] = useState('');

  // Build API query string
  const queryParams = useMemo(() => {
    const params = new URLSearchParams();
    params.set('limit', '50');
    if (trackFilter) params.set('track_id', trackFilter);
    if (driverFilter) params.set('driver_id', driverFilter);
    return params.toString();
  }, [trackFilter, driverFilter]);

  // Fetch leaderboard
  const { data: entries, isLoading, error, refetch } = useQuery({
    queryKey: ['leaderboard', queryParams],
    queryFn: () => api.get<LeaderboardEntry[]>(`/leaderboard?${queryParams}`),
  });

  // Fetch filter options
  const { data: tracks } = useQuery({
    queryKey: ['leaderboard-tracks'],
    queryFn: () => api.get<TrackOption[]>('/tracks'),
    staleTime: 60_000,
  });

  const { data: drivers } = useQuery({
    queryKey: ['leaderboard-drivers'],
    queryFn: () => api.get<DriverOption[]>('/drivers'),
    staleTime: 60_000,
  });

  const rows = entries ?? [];

  // Augment rows with computed rank field for DataTable
  const rankedRows = useMemo(
    () => rows.map((r, i) => ({ ...r, _rank: i + 1 })),
    [rows],
  );

  // Summary stats
  const bestLap = rows.length > 0 ? rows[0].best_lap_time_s : null;
  const totalLaps = rows.reduce((sum, r) => sum + (r.n_laps ?? 0), 0);
  const avgScore =
    rows.length > 0
      ? rows.reduce((sum, r) => sum + (r.total_score ?? 0), 0) / rows.length
      : null;

  const hasFilters = !!(trackFilter || driverFilter);

  const columns = useMemo(() => [
    {
      key: '_rank',
      header: '#',
      className: 'w-12 font-telemetry text-center',
      render: (row: LeaderboardEntry & { _rank: number }) => (
        <span className={`font-telemetry ${row._rank <= 3 ? 'text-marshal-yellow font-bold' : 'text-steel'}`}>
          {row._rank}
        </span>
      ),
    },
    {
      key: 'driver_name',
      header: 'Driver',
      className: 'font-body',
    },
    {
      key: 'track_name',
      header: 'Track',
      className: 'font-body',
    },
    {
      key: 'best_lap_time_s',
      header: 'Best Lap',
      sortable: true,
      className: 'font-telemetry',
      render: (row: LeaderboardEntry) => (
        <span className="text-acid-green">{formatLapTime(row.best_lap_time_s)}</span>
      ),
    },
    {
      key: 'n_laps',
      header: 'Laps',
      className: 'font-telemetry text-right',
    },
    {
      key: 'total_score',
      header: 'Score',
      sortable: true,
      className: 'font-telemetry text-right',
      render: (row: LeaderboardEntry) => (
        <span className={scoreColor(row.total_score)}>
          {row.total_score != null ? row.total_score.toFixed(1) : '\u2014'}
        </span>
      ),
    },
    {
      key: 'grade',
      header: 'Grade',
      className: 'text-center',
      render: (row: LeaderboardEntry) => <GradeBadge score={row.total_score} />,
    },
    {
      key: 'track_state',
      header: 'Condition',
      render: (row: LeaderboardEntry) => <ConditionBadge condition={row.track_state} />,
    },
    {
      key: 'session_date',
      header: 'Date',
      className: 'font-telemetry whitespace-nowrap',
      render: (row: LeaderboardEntry) => (
        <span className="text-steel">{formatDate(row.session_date)}</span>
      ),
    },
  ], []);

  return (
    <div>
      <PageIntro
        title="Leaderboard"
        subtitle={rows.length > 0 ? `${rows.length} result${rows.length !== 1 ? 's' : ''}` : undefined}
      />

      {/* -- Summary Stats --------------------------------------- */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Entries" value={rows.length} />
        <StatCard label="Best Lap" value={formatLapTime(bestLap)} />
        <StatCard label="Total Laps" value={totalLaps} />
        <StatCard label="Avg Score" value={avgScore != null ? avgScore.toFixed(1) : '\u2014'} />
      </div>

      {/* -- Filter Bar ------------------------------------------ */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <FilterSelect
          label="Track"
          value={trackFilter}
          options={(tracks ?? []).map((t) => ({
            value: String(t.id),
            label: t.name,
          }))}
          onChange={setTrackFilter}
        />
        <FilterSelect
          label="Driver"
          value={driverFilter}
          options={(drivers ?? []).map((d) => ({
            value: String(d.id),
            label: d.name,
          }))}
          onChange={setDriverFilter}
        />
        {hasFilters && (
          <button
            type="button"
            onClick={() => {
              setTrackFilter('');
              setDriverFilter('');
            }}
            className="text-safety-red text-xs font-body hover:text-safety-red/80 transition-colors px-2 py-2"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* -- Table / States -------------------------------------- */}
      {isLoading ? (
        <SkeletonTableRows rows={8} cols={9} />
      ) : error ? (
        <QueryError message="Failed to load leaderboard data." onRetry={() => refetch()} />
      ) : rows.length === 0 ? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          {hasFilters ? (
            <>
              <p className="text-steel font-body text-sm mb-3">
                No leaderboard entries match your filters.
              </p>
              <button
                type="button"
                onClick={() => {
                  setTrackFilter('');
                  setDriverFilter('');
                }}
                className="text-acid-green text-sm font-body hover:underline"
              >
                Clear filters
              </button>
            </>
          ) : (
            <>
              <h2 className="font-monument text-xl text-chalk mb-2">No leaderboard data yet</h2>
              <p className="text-steel font-body text-sm max-w-md mx-auto">
                Upload and analyze sessions with lap times to populate the leaderboard.
                The fastest laps will appear here ranked by time.
              </p>
            </>
          )}
        </div>
      ) : (
        <DataTable
          columns={columns}
          data={rankedRows}
          keyField="session_id"
          onRowClick={(row) => router.push(`/app/sessions/${row.session_id}`)}
          emptyMessage="No leaderboard entries"
          rowClassName={(row: LeaderboardEntry & { _rank: number }) => {
            if (row._rank === 1) return 'border-l-2 border-l-marshal-yellow/40';
            if (row._rank <= 3) return 'border-l-2 border-l-marshal-yellow/20';
            return '';
          }}
        />
      )}
    </div>
  );
}
