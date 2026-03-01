'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useState, useCallback, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, DataTable, QueryError, SkeletonTableRows } from '@/components/app';
import type { ContextAction } from '@/components/app/DataTable';

/* ── Types ──────────────────────────────────────────────── */

interface SessionRow {
  session_id: string;
  session_date: string;
  track_name: string;
  driver_name: string;
  n_laps: number;
  best_lap_time_s: number | null;
  mean_lap_time_s: number | null;
  total_score: number | null;
  grade: string | null;
  session_type: string | null;
  track_state: string | null;
}

interface ListResponse {
  sessions: SessionRow[];
  total: number;
  limit: number;
  offset: number;
}

interface FilterOptions {
  drivers: string[];
  tracks: string[];
  session_types: string[];
  track_states: string[];
}

/* ── Helpers ────────────────────────────────────────────── */

function formatLapTime(seconds: number | null): string {
  if (seconds == null) return '—';
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toFixed(3).padStart(6, '0')}`;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—';
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

/* ── Filter Select ─────────────────────────────────────── */

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
      className="bg-asphalt border border-steel/20 text-chalk text-xs font-telemetry rounded px-2 py-1.5
        focus:border-acid-green/40 focus:outline-none transition-colors"
      aria-label={label}
    >
      <option value="">{label}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

/* ── Page Component ─────────────────────────────────────── */

const PER_PAGE = 25;

export default function SessionsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [showFilters, setShowFilters] = useState(false);

  // Filters
  const [search, setSearch] = useState('');
  const [filterDriver, setFilterDriver] = useState('');
  const [filterTrack, setFilterTrack] = useState('');
  const [filterType, setFilterType] = useState('');
  const [filterCondition, setFilterCondition] = useState('');
  const [filterDateFrom, setFilterDateFrom] = useState('');
  const [filterDateTo, setFilterDateTo] = useState('');
  const [filterMinScore, setFilterMinScore] = useState('');
  const [filterMaxScore, setFilterMaxScore] = useState('');

  // Sorting
  const [sortBy, setSortBy] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  // Bulk action confirm
  const [confirmDelete, setConfirmDelete] = useState(false);

  const offset = (page - 1) * PER_PAGE;

  // Build query string from filters
  const queryParams = useMemo(() => {
    const params = new URLSearchParams();
    params.set('limit', String(PER_PAGE));
    params.set('offset', String(offset));
    if (search) params.set('search', search);
    if (filterDriver) params.set('driver', filterDriver);
    if (filterTrack) params.set('track', filterTrack);
    if (filterType) params.set('session_type', filterType);
    if (filterCondition) params.set('track_state', filterCondition);
    if (filterDateFrom) params.set('date_from', filterDateFrom);
    if (filterDateTo) params.set('date_to', filterDateTo);
    if (filterMinScore) params.set('min_score', filterMinScore);
    if (filterMaxScore) params.set('max_score', filterMaxScore);
    if (sortBy) {
      params.set('sort_by', sortBy);
      params.set('sort_dir', sortDir);
    }
    return params.toString();
  }, [offset, search, filterDriver, filterTrack, filterType, filterCondition,
      filterDateFrom, filterDateTo, filterMinScore, filterMaxScore, sortBy, sortDir]);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['sessions', 'list', queryParams],
    queryFn: () => api.get<ListResponse>(`/sessions?${queryParams}`),
  });

  // Filter options for dropdowns
  const { data: filterOpts } = useQuery({
    queryKey: ['sessions', 'filter-options'],
    queryFn: () => api.get<FilterOptions>('/sessions/filter-options'),
    staleTime: 60_000,
  });

  const sessions = data?.sessions ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));

  // Reset to page 1 when filters change
  const applyFilter = useCallback((setter: (v: string) => void, value: string) => {
    setter(value);
    setPage(1);
    setSelectedKeys(new Set());
  }, []);

  const clearFilters = useCallback(() => {
    setSearch('');
    setFilterDriver('');
    setFilterTrack('');
    setFilterType('');
    setFilterCondition('');
    setFilterDateFrom('');
    setFilterDateTo('');
    setFilterMinScore('');
    setFilterMaxScore('');
    setPage(1);
    setSelectedKeys(new Set());
  }, []);

  const hasActiveFilters = !!(search || filterDriver || filterTrack || filterType ||
    filterCondition || filterDateFrom || filterDateTo || filterMinScore || filterMaxScore);

  // Sort handler
  const handleSortChange = useCallback((key: string, dir: 'asc' | 'desc') => {
    setSortBy(key);
    setSortDir(dir);
    setPage(1);
  }, []);

  // Bulk delete mutation
  const deleteMutation = useMutation({
    mutationFn: async (ids: string[]) => {
      await Promise.all(ids.map((id) => api.delete(`/sessions/${id}`)));
    },
    onSuccess: () => {
      setSelectedKeys(new Set());
      setConfirmDelete(false);
      queryClient.invalidateQueries({ queryKey: ['sessions'] });
    },
  });

  // Context menu actions
  const contextActions: ContextAction<SessionRow>[] = useMemo(() => [
    {
      label: 'Open Session',
      onClick: (row) => router.push(`/app/sessions/${row.session_id}`),
    },
    {
      label: 'Open in Visualize',
      onClick: (row) => router.push(`/app/visualize/${row.session_id}`),
    },
    {
      label: 'Copy Session ID',
      onClick: (row) => navigator.clipboard.writeText(row.session_id),
    },
    {
      label: 'Delete',
      destructive: true,
      onClick: (row) => {
        if (window.confirm(`Delete session "${row.session_id}"?`)) {
          deleteMutation.mutate([row.session_id]);
        }
      },
    },
  ], [router, deleteMutation]);

  const columns = [
    {
      key: 'session_date',
      header: 'Date',
      sortable: true,
      className: 'font-telemetry whitespace-nowrap',
      render: (row: SessionRow) => (
        <span>{formatDate(row.session_date)}</span>
      ),
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
      sortable: true,
      render: (row: SessionRow) => <TypeBadge type={row.session_type} />,
    },
    {
      key: 'track_state',
      header: 'Condition',
      sortable: true,
      render: (row: SessionRow) => <ConditionBadge condition={row.track_state} />,
    },
    {
      key: 'n_laps',
      header: 'Laps',
      sortable: true,
      className: 'font-telemetry text-right',
    },
    {
      key: 'best_lap_time_s',
      header: 'Best Lap',
      sortable: true,
      className: 'font-telemetry',
      render: (row: SessionRow) => (
        <span className="text-acid-green">{formatLapTime(row.best_lap_time_s)}</span>
      ),
    },
    {
      key: 'mean_lap_time_s',
      header: 'Mean Lap',
      sortable: true,
      className: 'font-telemetry',
      render: (row: SessionRow) => (
        <span className="text-steel">{formatLapTime(row.mean_lap_time_s)}</span>
      ),
    },
    {
      key: 'total_score',
      header: 'Score',
      sortable: true,
      className: 'font-telemetry text-right',
      render: (row: SessionRow) => (
        <span className={scoreColor(row.total_score)}>
          {row.total_score != null ? row.total_score.toFixed(1) : '—'}
        </span>
      ),
    },
    {
      key: 'grade',
      header: 'Grade',
      sortable: true,
      render: (row: SessionRow) => <GradeBadge grade={row.grade} score={row.total_score} />,
    },
  ];

  return (
    <div>
      <PageHeader
        title="Sessions"
        subtitle={data ? `${total} session${total !== 1 ? 's' : ''}` : undefined}
        actions={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowFilters(!showFilters)}
              className={`inline-flex items-center gap-1.5 px-3 py-2.5 border rounded-lg font-telemetry text-xs transition-colors ${
                showFilters || hasActiveFilters
                  ? 'border-acid-green/40 text-acid-green bg-acid-green/5'
                  : 'border-steel/20 text-steel hover:text-chalk hover:border-steel/40'
              }`}
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <path d="M1 3h12M3 7h8M5 11h4" strokeLinecap="round" />
              </svg>
              Filters
              {hasActiveFilters && (
                <span className="w-1.5 h-1.5 rounded-full bg-acid-green" />
              )}
            </button>
            <Link
              href="/app/sessions/upload"
              className="inline-flex items-center gap-2 px-4 py-2.5 bg-acid-green text-carbon font-monument text-xs rounded-lg hover:bg-acid-green/90 transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" focusable="false">
                <line x1="7" y1="2" x2="7" y2="12" />
                <line x1="2" y1="7" x2="12" y2="7" />
              </svg>
              Upload Session
            </Link>
          </div>
        }
      />

      {/* ── Search + Filters ─────────────────────────────── */}
      <div className="mb-4">
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-steel" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="7" cy="7" r="5" />
            <path d="M11 11l3.5 3.5" strokeLinecap="round" />
          </svg>
          <input
            type="text"
            placeholder="Search by driver, track, or filename..."
            value={search}
            onChange={(e) => applyFilter(setSearch, e.target.value)}
            className="w-full pl-10 pr-4 py-2.5 bg-concrete border border-steel/20 rounded-lg text-chalk font-body text-sm
              placeholder:text-steel/40 focus:border-acid-green/40 focus:outline-none transition-colors"
          />
        </div>
      </div>

      {showFilters && (
        <div className="bg-concrete border border-steel/20 rounded-lg p-4 mb-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-steel font-telemetry text-xs uppercase tracking-wider">Filters</span>
            {hasActiveFilters && (
              <button
                type="button"
                onClick={clearFilters}
                className="text-safety-red text-xs font-body hover:text-safety-red/80 transition-colors"
              >
                Clear all
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <FilterSelect
              label="Driver"
              value={filterDriver}
              options={(filterOpts?.drivers ?? []).map((d) => ({ value: d, label: d }))}
              onChange={(v) => applyFilter(setFilterDriver, v)}
            />
            <FilterSelect
              label="Track"
              value={filterTrack}
              options={(filterOpts?.tracks ?? []).map((t) => ({ value: t, label: t }))}
              onChange={(v) => applyFilter(setFilterTrack, v)}
            />
            <FilterSelect
              label="Type"
              value={filterType}
              options={(filterOpts?.session_types ?? []).map((t) => ({
                value: t,
                label: t.charAt(0).toUpperCase() + t.slice(1),
              }))}
              onChange={(v) => applyFilter(setFilterType, v)}
            />
            <FilterSelect
              label="Condition"
              value={filterCondition}
              options={(filterOpts?.track_states ?? []).map((s) => ({
                value: s,
                label: s.charAt(0).toUpperCase() + s.slice(1),
              }))}
              onChange={(v) => applyFilter(setFilterCondition, v)}
            />
            <input
              type="date"
              value={filterDateFrom}
              onChange={(e) => applyFilter(setFilterDateFrom, e.target.value)}
              className="bg-asphalt border border-steel/20 text-chalk text-xs font-telemetry rounded px-2 py-1.5
                focus:border-acid-green/40 focus:outline-none transition-colors"
              aria-label="Date from"
              placeholder="From"
            />
            <input
              type="date"
              value={filterDateTo}
              onChange={(e) => applyFilter(setFilterDateTo, e.target.value)}
              className="bg-asphalt border border-steel/20 text-chalk text-xs font-telemetry rounded px-2 py-1.5
                focus:border-acid-green/40 focus:outline-none transition-colors"
              aria-label="Date to"
              placeholder="To"
            />
            <input
              type="number"
              value={filterMinScore}
              onChange={(e) => applyFilter(setFilterMinScore, e.target.value)}
              placeholder="Min score"
              min="0"
              max="100"
              className="w-24 bg-asphalt border border-steel/20 text-chalk text-xs font-telemetry rounded px-2 py-1.5
                placeholder:text-steel/40 focus:border-acid-green/40 focus:outline-none transition-colors"
              aria-label="Minimum score"
            />
            <input
              type="number"
              value={filterMaxScore}
              onChange={(e) => applyFilter(setFilterMaxScore, e.target.value)}
              placeholder="Max score"
              min="0"
              max="100"
              className="w-24 bg-asphalt border border-steel/20 text-chalk text-xs font-telemetry rounded px-2 py-1.5
                placeholder:text-steel/40 focus:border-acid-green/40 focus:outline-none transition-colors"
              aria-label="Maximum score"
            />
          </div>
        </div>
      )}

      {/* ── Bulk Actions Bar ─────────────────────────────── */}
      {selectedKeys.size > 0 && (
        <div className="bg-asphalt border border-steel/20 rounded-lg px-4 py-2.5 mb-4 flex items-center gap-3">
          <span className="text-chalk font-telemetry text-xs">
            {selectedKeys.size} selected
          </span>
          <div className="h-4 w-px bg-steel/20" />
          <button
            type="button"
            onClick={() => {
              // Re-analyze selected: navigate to upload with re-analyze hint
              // For now, just refetch to trigger fresh data
              const ids = Array.from(selectedKeys);
              if (window.confirm(`Re-analyze ${ids.length} session(s)? This will re-run the pipeline.`)) {
                // Future: POST /api/v1/sessions/batch-reanalyze
                refetch();
              }
            }}
            className="text-marshal-yellow text-xs font-body hover:text-marshal-yellow/80 transition-colors"
          >
            Re-analyze
          </button>
          {!confirmDelete ? (
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              className="text-safety-red text-xs font-body hover:text-safety-red/80 transition-colors"
            >
              Delete
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-safety-red text-xs font-body">Delete {selectedKeys.size}?</span>
              <button
                type="button"
                onClick={() => deleteMutation.mutate(Array.from(selectedKeys))}
                disabled={deleteMutation.isPending}
                className="px-2 py-0.5 bg-safety-red text-chalk text-xs rounded font-body hover:bg-safety-red/80 disabled:opacity-50"
              >
                {deleteMutation.isPending ? 'Deleting...' : 'Confirm'}
              </button>
              <button
                type="button"
                onClick={() => setConfirmDelete(false)}
                className="text-steel text-xs font-body hover:text-chalk"
              >
                Cancel
              </button>
            </div>
          )}
          <button
            type="button"
            onClick={() => setSelectedKeys(new Set())}
            className="ml-auto text-steel text-xs font-body hover:text-chalk transition-colors"
          >
            Clear selection
          </button>
        </div>
      )}

      {/* ── Stat Cards ──────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
        <StatCard label="Total Sessions" value={total} />
        <StatCard label="Page" value={`${page} / ${totalPages}`} />
        <StatCard label="Showing" value={sessions.length} />
      </div>

      {/* ── Table ───────────────────────────────────────── */}
      {isLoading ? (
        <SkeletonTableRows rows={8} cols={7} />
      ) : error ? (
        <QueryError message="Couldn't load sessions." onRetry={() => refetch()} />
      ) : sessions.length === 0 && !hasActiveFilters ? (
        /* Rich empty state */
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          <div className="text-5xl mb-4" aria-hidden="true">🏁</div>
          <h2 className="font-monument text-xl text-chalk mb-2">No sessions yet</h2>
          <p className="text-steel font-body text-sm max-w-md mx-auto mb-6">
            This is where all your analyzed sessions will appear. Each session
            gets a score, grade, and detailed breakdown. Upload a RaceChrono or
            RaceBox CSV to get started.
          </p>
          <Link
            href="/app/sessions/upload"
            className="inline-flex items-center gap-2 px-6 py-3 bg-acid-green text-carbon font-monument text-sm rounded-lg hover:bg-acid-green/90 transition-colors"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" focusable="false">
              <line x1="8" y1="2" x2="8" y2="14" />
              <line x1="2" y1="8" x2="14" y2="8" />
            </svg>
            Upload Session
          </Link>
        </div>
      ) : sessions.length === 0 && hasActiveFilters ? (
        /* No results for filters */
        <div className="bg-concrete rounded-lg border border-steel/20 p-8 text-center">
          <p className="text-steel font-body mb-3">No sessions match your filters.</p>
          <button
            type="button"
            onClick={clearFilters}
            className="text-acid-green text-sm font-body hover:underline"
          >
            Clear filters
          </button>
        </div>
      ) : (
        <>
          <DataTable
            columns={columns}
            data={sessions}
            keyField="session_id"
            selectable
            selectedKeys={selectedKeys}
            onSelectionChange={setSelectedKeys}
            onRowClick={(row) => router.push(`/app/sessions/${row.session_id}`)}
            contextActions={contextActions}
            onSortChange={handleSortChange}
            activeSortKey={sortBy}
            activeSortDir={sortDir}
            emptyMessage="No sessions found"
            rowClassName={(row: SessionRow) => {
              if (row.total_score != null && row.total_score >= 80) return 'border-l-2 border-l-acid-green/30';
              if (row.total_score != null && row.total_score < 40) return 'border-l-2 border-l-safety-red/20';
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
                  onClick={() => { setPage((p) => Math.max(1, p - 1)); setSelectedKeys(new Set()); }}
                  disabled={page <= 1}
                  className="px-3 py-1.5 rounded bg-concrete border border-steel/20 text-steel text-xs font-telemetry
                    hover:text-chalk hover:border-steel/40 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  Previous
                </button>
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
                      onClick={() => { setPage(pageNum); setSelectedKeys(new Set()); }}
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
                  onClick={() => { setPage((p) => Math.min(totalPages, p + 1)); setSelectedKeys(new Set()); }}
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

      {/* Scroll-to-top */}
      <button
        type="button"
        onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
        className="fixed bottom-6 right-6 w-10 h-10 rounded-full bg-concrete border border-steel/20
          text-steel hover:text-chalk hover:border-steel/40 transition-colors shadow-lg
          flex items-center justify-center z-40"
        aria-label="Scroll to top"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M8 12V4M4 7l4-3 4 3" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </div>
  );
}
