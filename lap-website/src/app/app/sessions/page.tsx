'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useState, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, DataTable } from '@/components/app';

/* ── Types ──────────────────────────────────────────────── */

interface SessionRow {
  id: string;
  date: string;
  track_name: string;
  driver_name: string;
  laps: number;
  best_time: number | null;
  mean_time: number | null;
  score: number | null;
  grade: string | null;
  session_type: string | null;
  track_state: string | null;
}

interface BrowseResponse {
  sessions: SessionRow[];
  total: number;
  avg_score: number | null;
  best_lap: number | null;
  active_drivers: number;
  page: number;
  per_page: number;
  total_pages: number;
}

/* ── Helpers ────────────────────────────────────────────── */

function formatLapTime(seconds: number | null): string {
  if (seconds == null) return '—';
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toFixed(3).padStart(6, '0')}`;
}

function scoreColor(score: number | null): string {
  if (score == null) return 'text-steel';
  if (score >= 80) return 'text-acid-green';
  if (score >= 60) return 'text-marshal-yellow';
  if (score >= 40) return 'text-pit-orange';
  return 'text-safety-red';
}

const TYPE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  practice:   { bg: 'bg-acid-green/10', text: 'text-acid-green', label: 'Practice' },
  qualifying: { bg: 'bg-marshal-yellow/10', text: 'text-marshal-yellow', label: 'Qualifying' },
  race:       { bg: 'bg-safety-red/10', text: 'text-safety-red', label: 'Race' },
  test:       { bg: 'bg-blue-400/10', text: 'text-blue-400', label: 'Test' },
  endurance:  { bg: 'bg-purple-400/10', text: 'text-purple-400', label: 'Endurance' },
};

const CONDITION_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  dry:    { bg: 'bg-acid-green/10', text: 'text-acid-green', label: 'Dry' },
  wet:    { bg: 'bg-blue-400/10', text: 'text-blue-400', label: 'Wet' },
  damp:   { bg: 'bg-marshal-yellow/10', text: 'text-marshal-yellow', label: 'Damp' },
  mixed:  { bg: 'bg-purple-400/10', text: 'text-purple-400', label: 'Mixed' },
  greasy: { bg: 'bg-pit-orange/10', text: 'text-pit-orange', label: 'Greasy' },
};

function TypeBadge({ type }: { type: string | null }) {
  if (!type) return <span className="text-steel/40">—</span>;
  const style = TYPE_STYLES[type] ?? { bg: 'bg-steel/10', text: 'text-steel', label: type };
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-telemetry uppercase tracking-wider ${style.bg} ${style.text}`}>
      {style.label}
    </span>
  );
}

function ConditionBadge({ condition }: { condition: string | null }) {
  if (!condition) return <span className="text-steel/40">—</span>;
  const style = CONDITION_STYLES[condition] ?? { bg: 'bg-steel/10', text: 'text-steel', label: condition };
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-telemetry uppercase tracking-wider ${style.bg} ${style.text}`}>
      {style.label}
    </span>
  );
}

function GradeBadge({ grade, score }: { grade: string | null; score: number | null }) {
  if (!grade) return <span className="text-steel/40">—</span>;
  const color = scoreColor(score);
  return (
    <span className={`inline-flex items-center justify-center w-8 h-8 rounded-md border font-monument text-lg ${color} ${
      score != null && score >= 80 ? 'border-acid-green/30 bg-acid-green/5' :
      score != null && score >= 60 ? 'border-marshal-yellow/30 bg-marshal-yellow/5' :
      score != null && score >= 40 ? 'border-pit-orange/30 bg-pit-orange/5' :
      'border-safety-red/30 bg-safety-red/5'
    }`}>
      {grade}
    </span>
  );
}

/* ── Sort Options ───────────────────────────────────────── */

type SortOption = 'date' | 'score' | 'best_time';
const SORT_OPTIONS: { value: SortOption; label: string }[] = [
  { value: 'date', label: 'Newest First' },
  { value: 'score', label: 'Highest Score' },
  { value: 'best_time', label: 'Fastest Lap' },
];

/* ── Page Component ─────────────────────────────────────── */

export default function SessionsPage() {
  const router = useRouter();
  const [search, setSearch] = useState('');
  const [driverFilter, setDriverFilter] = useState('');
  const [trackFilter, setTrackFilter] = useState('');
  const [sort, setSort] = useState<SortOption>('date');
  const [page, setPage] = useState(1);
  const perPage = 25;

  // Build query string from all filters
  const queryString = useMemo(() => {
    const params = new URLSearchParams();
    params.set('page', String(page));
    params.set('per_page', String(perPage));
    params.set('sort', sort);
    if (search) params.set('q', search);
    if (driverFilter) params.set('driver', driverFilter);
    if (trackFilter) params.set('track', trackFilter);
    return params.toString();
  }, [page, sort, search, driverFilter, trackFilter]);

  const { data, isLoading } = useQuery({
    queryKey: ['sessions', 'browse', queryString],
    queryFn: () => api.get<BrowseResponse>(`/sessions/browse?${queryString}`),
  });

  const sessions = data?.sessions ?? [];
  const totalPages = data?.total_pages ?? 1;

  // Reset page when filters change
  const updateFilter = (setter: (v: string) => void) => (value: string) => {
    setter(value);
    setPage(1);
  };

  const columns = [
    {
      key: 'date',
      header: 'Date',
      sortable: true,
      className: 'font-telemetry whitespace-nowrap',
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
      key: 'session_type',
      header: 'Type',
      render: (row: SessionRow) => <TypeBadge type={row.session_type} />,
    },
    {
      key: 'track_state',
      header: 'Condition',
      render: (row: SessionRow) => <ConditionBadge condition={row.track_state} />,
    },
    {
      key: 'laps',
      header: 'Laps',
      sortable: true,
      className: 'font-telemetry text-right',
    },
    {
      key: 'best_time',
      header: 'Best Lap',
      sortable: true,
      className: 'font-telemetry',
      render: (row: SessionRow) => (
        <span className="text-acid-green">{formatLapTime(row.best_time)}</span>
      ),
    },
    {
      key: 'mean_time',
      header: 'Mean Lap',
      className: 'font-telemetry',
      render: (row: SessionRow) => (
        <span className="text-steel">{formatLapTime(row.mean_time)}</span>
      ),
    },
    {
      key: 'score',
      header: 'Score',
      sortable: true,
      className: 'font-telemetry text-right',
      render: (row: SessionRow) => (
        <span className={scoreColor(row.score)}>
          {row.score != null ? row.score.toFixed(1) : '—'}
        </span>
      ),
    },
    {
      key: 'grade',
      header: 'Grade',
      render: (row: SessionRow) => <GradeBadge grade={row.grade} score={row.score} />,
    },
  ];

  /* ── Empty State ──────────────────────────────────────── */
  const hasFilters = search || driverFilter || trackFilter;

  return (
    <div>
      <PageHeader
        title="Sessions"
        subtitle={data ? `${data.total} session${data.total !== 1 ? 's' : ''}` : undefined}
      />

      {/* ── Stat Cards ──────────────────────────────────── */}
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

      {/* ── Filter Bar ──────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        {/* Search */}
        <input
          type="text"
          placeholder="Search sessions..."
          value={search}
          onChange={(e) => updateFilter(setSearch)(e.target.value)}
          className="flex-1 min-w-0 bg-concrete border border-steel/30 rounded px-4 py-2.5 text-chalk font-body text-sm
            placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        />

        {/* Driver filter */}
        <input
          type="text"
          placeholder="Filter driver..."
          value={driverFilter}
          onChange={(e) => updateFilter(setDriverFilter)(e.target.value)}
          className="sm:w-44 bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
            placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        />

        {/* Track filter */}
        <input
          type="text"
          placeholder="Filter track..."
          value={trackFilter}
          onChange={(e) => updateFilter(setTrackFilter)(e.target.value)}
          className="sm:w-44 bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
            placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        />

        {/* Sort dropdown */}
        <select
          value={sort}
          onChange={(e) => { setSort(e.target.value as SortOption); setPage(1); }}
          className="sm:w-44 bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
            focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        >
          {SORT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      {/* ── Active Filter Tags ──────────────────────────── */}
      {hasFilters && (
        <div className="flex items-center gap-2 mb-4">
          <span className="text-steel/60 text-xs font-telemetry">Filters:</span>
          {search && (
            <button type="button" onClick={() => updateFilter(setSearch)('')}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-pit-orange/10 text-pit-orange text-[10px] font-telemetry uppercase hover:bg-pit-orange/20 transition-colors"
            >
              &quot;{search}&quot; <span className="ml-1">×</span>
            </button>
          )}
          {driverFilter && (
            <button type="button" onClick={() => updateFilter(setDriverFilter)('')}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-acid-green/10 text-acid-green text-[10px] font-telemetry uppercase hover:bg-acid-green/20 transition-colors"
            >
              Driver: {driverFilter} <span className="ml-1">×</span>
            </button>
          )}
          {trackFilter && (
            <button type="button" onClick={() => updateFilter(setTrackFilter)('')}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-marshal-yellow/10 text-marshal-yellow text-[10px] font-telemetry uppercase hover:bg-marshal-yellow/20 transition-colors"
            >
              Track: {trackFilter} <span className="ml-1">×</span>
            </button>
          )}
          <button
            type="button"
            onClick={() => { setSearch(''); setDriverFilter(''); setTrackFilter(''); setSort('date'); setPage(1); }}
            className="text-steel/40 text-[10px] font-telemetry uppercase hover:text-chalk transition-colors ml-2"
          >
            Clear all
          </button>
        </div>
      )}

      {/* ── Table ───────────────────────────────────────── */}
      {isLoading ? (
        <div className="flex items-center justify-center h-48">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      ) : sessions.length === 0 && !hasFilters ? (
        /* Rich empty state */
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          <div className="text-5xl mb-4">🏁</div>
          <h3 className="font-monument text-xl text-chalk mb-2">No sessions yet</h3>
          <p className="text-steel font-body text-sm max-w-md mx-auto mb-6">
            This is where all your analyzed sessions will appear. Each session
            gets a score, grade, and detailed breakdown. Upload a RaceChrono or
            RaceBox CSV to get started.
          </p>
          <button
            onClick={() => router.push('/app/analyze')}
            className="inline-flex items-center gap-2 px-6 py-3 bg-acid-green text-carbon font-monument text-sm rounded-lg hover:bg-acid-green/90 transition-colors"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="8" y1="2" x2="8" y2="14" />
              <line x1="2" y1="8" x2="14" y2="8" />
            </svg>
            New Analysis
          </button>
        </div>
      ) : (
        <>
          <DataTable
            columns={columns}
            data={sessions}
            keyField="id"
            onRowClick={(row) => router.push(`/app/sessions/${row.id}`)}
            emptyMessage={hasFilters ? 'No sessions match your filters' : 'No sessions found'}
            rowClassName={(row: SessionRow) => {
              if (row.score != null && row.score >= 80) return 'border-l-2 border-l-acid-green/30';
              if (row.score != null && row.score < 40) return 'border-l-2 border-l-safety-red/20';
              return '';
            }}
          />

          {/* ── Pagination ─────────────────────────────── */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4 px-1">
              <span className="text-steel/60 text-xs font-telemetry">
                Page {page} of {totalPages}
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="px-3 py-1.5 rounded bg-concrete border border-steel/20 text-steel text-xs font-telemetry
                    hover:text-chalk hover:border-steel/40 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  Previous
                </button>
                {/* Page number buttons — show up to 5 */}
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  let pageNum: number;
                  if (totalPages <= 5) {
                    pageNum = i + 1;
                  } else if (page <= 3) {
                    pageNum = i + 1;
                  } else if (page >= totalPages - 2) {
                    pageNum = totalPages - 4 + i;
                  } else {
                    pageNum = page - 2 + i;
                  }
                  return (
                    <button
                      key={pageNum}
                      onClick={() => setPage(pageNum)}
                      className={`w-8 h-8 rounded text-xs font-telemetry transition-colors ${
                        pageNum === page
                          ? 'bg-pit-orange text-chalk'
                          : 'bg-concrete border border-steel/20 text-steel hover:text-chalk hover:border-steel/40'
                      }`}
                    >
                      {pageNum}
                    </button>
                  );
                })}
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="px-3 py-1.5 rounded bg-concrete border border-steel/20 text-steel text-xs font-telemetry
                    hover:text-chalk hover:border-steel/40 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
