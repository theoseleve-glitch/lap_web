'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { useSearchParams, usePathname } from 'next/navigation';
import { api } from '@/lib/api-client';
import { formatLapTime, formatDate, scoreColor } from '@/lib/format-utils';
import { StatCard, DataTable, QueryError, SkeletonTableRows } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';
import { EmptyState } from '@/components/ui/EmptyState';
import type { ContextAction } from '@/components/app/DataTable';
import { canPrefetch, markPrefetched, incrementInFlight, decrementInFlight } from '@/lib/prefetch';

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

const TYPE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  practice:   { bg: 'bg-acid-green/10', text: 'text-acid-green', label: 'Practice' },
  qualifying: { bg: 'bg-marshal-yellow/10', text: 'text-marshal-yellow', label: 'Qualifying' },
  race:       { bg: 'bg-safety-red/10', text: 'text-safety-red', label: 'Race' },
  test:       { bg: 'bg-blue-400/10', text: 'text-blue-400', label: 'Test' },
  endurance:  { bg: 'bg-purple-400/10', text: 'text-purple-400', label: 'Endurance' },
  heat:       { bg: 'bg-pit-orange/10', text: 'text-pit-orange', label: 'Heat' },
  final:      { bg: 'bg-safety-red/10', text: 'text-safety-red', label: 'Final' },
};

const CONDITION_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  dry:      { bg: 'bg-acid-green/10', text: 'text-acid-green', label: 'Dry' },
  wet:      { bg: 'bg-blue-400/10', text: 'text-blue-400', label: 'Wet' },
  damp:     { bg: 'bg-marshal-yellow/10', text: 'text-marshal-yellow', label: 'Damp' },
  mixed:    { bg: 'bg-purple-400/10', text: 'text-purple-400', label: 'Mixed' },
  green:    { bg: 'bg-emerald-400/10', text: 'text-emerald-400', label: 'Green' },
  rubbered: { bg: 'bg-zinc-400/10', text: 'text-zinc-400', label: 'Rubbered' },
  dusty:    { bg: 'bg-amber-400/10', text: 'text-amber-400', label: 'Dusty' },
};

function TypeBadge({ type }: { type: string | null }) {
  if (!type) return <span className="text-steel/60">—</span>;
  const style = TYPE_STYLES[type] ?? { bg: 'bg-steel/10', text: 'text-steel', label: type };
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-telemetry uppercase tracking-wider ${style.bg} ${style.text}`}>
      {style.label}
    </span>
  );
}

function ConditionBadge({ condition }: { condition: string | null }) {
  if (!condition) return <span className="text-steel/60">—</span>;
  const style = CONDITION_STYLES[condition] ?? { bg: 'bg-steel/10', text: 'text-steel', label: condition };
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-telemetry uppercase tracking-wider ${style.bg} ${style.text}`}>
      {style.label}
    </span>
  );
}

function GradeBadge({ grade, score }: { grade: string | null; score: number | null }) {
  if (!grade) return <span className="text-steel/60">—</span>;
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

/* ── Session Calendar ───────────────────────────────────── */

function SessionCalendar({ sessions }: { sessions: SessionRow[] }) {
  const router = useRouter();
  const [viewDate, setViewDate] = useState(() => new Date());

  const year = viewDate.getFullYear();
  const month = viewDate.getMonth();
  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  // Group sessions by day
  const sessionsByDay = useMemo(() => {
    const map: Record<number, SessionRow[]> = {};
    for (const s of sessions) {
      const d = new Date(s.session_date);
      if (d.getFullYear() === year && d.getMonth() === month) {
        const day = d.getDate();
        if (!map[day]) map[day] = [];
        map[day].push(s);
      }
    }
    return map;
  }, [sessions, year, month]);

  const prevMonth = () => setViewDate(new Date(year, month - 1, 1));
  const nextMonth = () => setViewDate(new Date(year, month + 1, 1));

  const monthLabel = viewDate.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-4">
      <div className="flex items-center justify-between mb-4">
        <button type="button" onClick={prevMonth} className="text-steel hover:text-chalk transition-colors px-2 py-1 text-sm" aria-label="Previous month">&lt;</button>
        <span className="font-monument text-chalk text-sm">{monthLabel}</span>
        <button type="button" onClick={nextMonth} className="text-steel hover:text-chalk transition-colors px-2 py-1 text-sm" aria-label="Next month">&gt;</button>
      </div>
      <div className="grid grid-cols-7 gap-px">
        {days.map((d) => (
          <div key={d} className="text-center text-[10px] font-telemetry text-steel/60 py-1">{d}</div>
        ))}
        {Array.from({ length: firstDay }).map((_, i) => (
          <div key={`empty-${i}`} />
        ))}
        {Array.from({ length: daysInMonth }, (_, i) => {
          const day = i + 1;
          const daySessions = sessionsByDay[day];
          const isToday = (() => {
            const now = new Date();
            return now.getFullYear() === year && now.getMonth() === month && now.getDate() === day;
          })();
          return (
            <div
              key={day}
              className={`relative min-h-[48px] p-1 rounded-lg border transition-colors ${
                daySessions
                  ? 'border-steel/20 bg-asphalt hover:border-acid-green/30 cursor-pointer'
                  : 'border-transparent'
              } ${isToday ? 'ring-1 ring-pit-orange/40' : ''}`}
              onClick={() => {
                if (daySessions?.length === 1 && daySessions[0]) {
                  router.push(`/app/sessions/${daySessions[0].session_id}`);
                }
              }}
            >
              <span className={`text-[10px] font-telemetry ${isToday ? 'text-pit-orange' : daySessions ? 'text-chalk' : 'text-steel/40'}`}>
                {day}
              </span>
              {daySessions && (
                <div className="mt-0.5 space-y-0.5">
                  {daySessions.slice(0, 2).map((s) => (
                    <div
                      key={s.session_id}
                      onClick={(e) => { e.stopPropagation(); router.push(`/app/sessions/${s.session_id}`); }}
                      className="truncate text-[8px] font-body text-chalk/70 bg-steel/10 rounded px-1 py-0.5 hover:bg-steel/20 cursor-pointer"
                      title={`${s.track_name} - ${s.driver_name}`}
                    >
                      {s.track_name || 'Session'}
                    </div>
                  ))}
                  {daySessions.length > 2 && (
                    <span className="text-[8px] text-steel/50 font-telemetry">+{daySessions.length - 2} more</span>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Grouped by Event View ─────────────────────────────── */

interface EventGroup {
  key: string;
  track: string;
  dateRange: string;
  sessions: SessionRow[];
}

function groupSessionsByEvent(sessions: SessionRow[]): EventGroup[] {
  // Group sessions that share the same track and fall within 3 days of each other
  const sorted = [...sessions].sort((a, b) => a.session_date.localeCompare(b.session_date));
  const groups: EventGroup[] = [];
  const used = new Set<number>();

  for (let i = 0; i < sorted.length; i++) {
    if (used.has(i)) continue;
    const base = sorted[i];
    if (!base) continue;
    const cluster: SessionRow[] = [base];
    used.add(i);
    const baseDate = new Date(base.session_date).getTime();

    for (let j = i + 1; j < sorted.length; j++) {
      if (used.has(j)) continue;
      const other = sorted[j];
      if (!other) continue;
      if (other.track_name !== base.track_name) continue;
      const diff = Math.abs(new Date(other.session_date).getTime() - baseDate);
      if (diff <= 3 * 86400000) { // within 3 days
        cluster.push(other);
        used.add(j);
      }
    }

    const dates = cluster.map((s) => s.session_date).sort();
    const first = dates[0] ?? '';
    const last = dates[dates.length - 1] ?? '';
    const dateRange = first === last ? formatDate(first) : `${formatDate(first)} – ${formatDate(last)}`;

    groups.push({
      key: `${base.track_name}-${first}`,
      track: base.track_name || 'Unknown Track',
      dateRange,
      sessions: cluster,
    });
  }

  return groups.sort((a, b) => b.sessions[0]!.session_date.localeCompare(a.sessions[0]!.session_date));
}

function SessionGroupedView({ sessions, onSessionClick }: { sessions: SessionRow[]; onSessionClick: (id: string) => void }) {
  const groups = useMemo(() => groupSessionsByEvent(sessions), [sessions]);

  if (groups.length === 0) return <p className="text-steel text-sm">No sessions to group.</p>;

  return (
    <div className="space-y-4">
      {groups.map((group) => (
        <div key={group.key} className="bg-concrete rounded-xl border border-steel/10 p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h3 className="text-sm font-monument text-chalk">{group.track}</h3>
              <p className="text-[10px] font-telemetry text-steel/60">{group.dateRange}</p>
            </div>
            <span className="text-xs font-telemetry text-steel">
              {group.sessions.length} session{group.sessions.length !== 1 ? 's' : ''}
            </span>
          </div>
          <div className="space-y-1">
            {group.sessions.map((s) => (
              <button
                key={s.session_id}
                type="button"
                onClick={() => onSessionClick(s.session_id)}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-asphalt/50 transition-colors text-left"
              >
                <span className="text-xs font-telemetry text-steel w-20">{formatDate(s.session_date)}</span>
                <span className="text-xs font-body text-chalk flex-1 truncate">{s.driver_name}</span>
                <TypeBadge type={s.session_type} />
                <span className="text-xs font-telemetry text-acid-green w-16 text-right">{formatLapTime(s.best_lap_time_s)}</span>
                <span className={`text-xs font-telemetry w-10 text-right ${scoreColor(s.total_score)}`}>
                  {s.total_score != null ? s.total_score.toFixed(0) : '—'}
                </span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Column Customization ──────────────────────────────── */

const ALL_COLUMN_KEYS = [
  'session_date', 'track_name', 'driver_name', 'session_type',
  'track_state', 'n_laps', 'best_lap_time_s', 'mean_lap_time_s',
  'total_score', 'grade',
] as const;

const COLUMN_LABELS: Record<string, string> = {
  session_date: 'Date',
  track_name: 'Track',
  driver_name: 'Driver',
  session_type: 'Type',
  track_state: 'Condition',
  n_laps: 'Laps',
  best_lap_time_s: 'Best Lap',
  mean_lap_time_s: 'Mean Lap',
  total_score: 'Score',
  grade: 'Grade',
};

const DEFAULT_VISIBLE = new Set(ALL_COLUMN_KEYS);
const COLUMNS_STORAGE_KEY = 'session_list_columns';

function loadVisibleColumns(): Set<string> {
  try {
    const raw = localStorage.getItem(COLUMNS_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as string[];
      if (Array.isArray(parsed) && parsed.length > 0) return new Set(parsed);
    }
  } catch {}
  return new Set(DEFAULT_VISIBLE);
}

function saveVisibleColumns(cols: Set<string>) {
  try { localStorage.setItem(COLUMNS_STORAGE_KEY, JSON.stringify([...cols])); } catch {}
}

function ColumnCustomizer({
  visible,
  onChange,
}: {
  visible: Set<string>;
  onChange: (cols: Set<string>) => void;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close on outside click or Escape
  useEffect(() => {
    if (!open) return;
    const handleClick = (e: Event) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`inline-flex items-center gap-1.5 px-3 py-2.5 border rounded-lg font-telemetry text-xs transition-colors ${
          visible.size < ALL_COLUMN_KEYS.length
            ? 'border-pit-orange/40 text-pit-orange bg-pit-orange/5'
            : 'border-steel/20 text-steel hover:text-chalk hover:border-steel/40'
        }`}
        title="Customize columns"
        aria-label="Customize visible columns"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
          <rect x="1" y="1" width="5" height="12" rx="0.5" />
          <rect x="8" y="1" width="5" height="12" rx="0.5" />
        </svg>
        Columns
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-30 bg-concrete border border-steel/20 rounded-lg p-3 shadow-xl min-w-[180px]">
          <p className="text-[10px] font-telemetry text-steel/60 uppercase tracking-wider mb-2">Visible columns</p>
          {ALL_COLUMN_KEYS.map((key) => (
            <label key={key} className="flex items-center gap-2 py-1 cursor-pointer">
              <input
                type="checkbox"
                checked={visible.has(key)}
                onChange={() => {
                  const next = new Set(visible);
                  if (next.has(key)) {
                    if (next.size > 2) next.delete(key); // keep at least 2
                  } else {
                    next.add(key);
                  }
                  saveVisibleColumns(next);
                  onChange(next);
                }}
                className="accent-acid-green w-3.5 h-3.5"
              />
              <span className="text-xs font-body text-chalk">{COLUMN_LABELS[key]}</span>
            </label>
          ))}
          <button
            type="button"
            onClick={() => { onChange(new Set(DEFAULT_VISIBLE)); saveVisibleColumns(new Set(DEFAULT_VISIBLE)); }}
            className="mt-2 text-[10px] font-telemetry text-steel hover:text-chalk transition-colors"
          >
            Reset to default
          </button>
        </div>
      )}
    </div>
  );
}

/* ── Page Component ─────────────────────────────────────── */

const PER_PAGE = 25;

export default function SessionsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const pathname = usePathname();

  // Initialize filters from URL search params (bookmarkable/shareable)
  const [page, setPage] = useState(() => Number(searchParams.get('page') ?? '1'));
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [showFilters, setShowFilters] = useState(false);
  const [visibleCols, setVisibleCols] = useState<Set<string>>(() => loadVisibleColumns());

  // Filters — seeded from URL params
  const [search, setSearch] = useState(() => searchParams.get('q') ?? '');
  const [filterDriver, setFilterDriver] = useState(() => searchParams.get('driver') ?? '');
  const [filterTrack, setFilterTrack] = useState(() => searchParams.get('track') ?? '');
  const [filterType, setFilterType] = useState(() => searchParams.get('type') ?? '');
  const [filterCondition, setFilterCondition] = useState(() => searchParams.get('condition') ?? '');
  const [filterDateFrom, setFilterDateFrom] = useState(() => searchParams.get('from') ?? '');
  const [filterDateTo, setFilterDateTo] = useState(() => searchParams.get('to') ?? '');
  const [filterMinScore, setFilterMinScore] = useState(() => searchParams.get('minScore') ?? '');
  const [filterMaxScore, setFilterMaxScore] = useState(() => searchParams.get('maxScore') ?? '');

  // Sorting — seeded from URL params
  const [sortBy, setSortBy] = useState<string | null>(() => searchParams.get('sort') ?? null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>(() => (searchParams.get('dir') === 'asc' ? 'asc' : 'desc'));

  // Sync filters → URL (shallow replace, no scroll)
  useEffect(() => {
    const params = new URLSearchParams();
    if (page > 1) params.set('page', String(page));
    if (search) params.set('q', search);
    if (filterDriver) params.set('driver', filterDriver);
    if (filterTrack) params.set('track', filterTrack);
    if (filterType) params.set('type', filterType);
    if (filterCondition) params.set('condition', filterCondition);
    if (filterDateFrom) params.set('from', filterDateFrom);
    if (filterDateTo) params.set('to', filterDateTo);
    if (filterMinScore) params.set('minScore', filterMinScore);
    if (filterMaxScore) params.set('maxScore', filterMaxScore);
    if (sortBy) { params.set('sort', sortBy); params.set('dir', sortDir); }
    const qs = params.toString();
    const target = qs ? `${pathname}?${qs}` : pathname;
    router.replace(target, { scroll: false });
  }, [page, search, filterDriver, filterTrack, filterType, filterCondition,
      filterDateFrom, filterDateTo, filterMinScore, filterMaxScore, sortBy, sortDir,
      pathname, router]);

  // Bulk action confirm — reset when selection changes so the
  // confirmation isn't stale after clear → re-select.
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [bulkStatus, setBulkStatus] = useState<string | null>(null);
  useEffect(() => { setConfirmDelete(false); }, [selectedKeys]);

  // View mode: list, calendar, or grouped by event
  const [viewMode, setViewMode] = useState<'list' | 'calendar' | 'grouped'>('list');
  // Archive filter: 'active' (default), 'archived', 'all'
  const [archiveView, setArchiveView] = useState<'active' | 'archived' | 'all'>('active');

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
    if (archiveView === 'archived') params.set('archived', 'true');
    else if (archiveView === 'all') params.set('archived', 'all');
    // 'active' is the default — server hides archived by default
    return params.toString();
  }, [offset, search, filterDriver, filterTrack, filterType, filterCondition,
      filterDateFrom, filterDateTo, filterMinScore, filterMaxScore, sortBy, sortDir, archiveView]);

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

  // Select All helpers
  const allVisibleIds = sessions.map((s) => s.session_id);
  const allSelected = allVisibleIds.length > 0 && allVisibleIds.every((id) => selectedKeys.has(id));

  function handleSelectAll() {
    if (allSelected) {
      setSelectedKeys(new Set());
    } else {
      setSelectedKeys(new Set(allVisibleIds));
    }
  }

  // Bulk delete mutation with optimistic update.
  // CRITICAL: Uses Promise.allSettled (NOT Promise.all) so that a single
  // failed delete does NOT roll back the optimistic removal of successfully
  // deleted sessions. Promise.all short-circuits on first rejection and
  // would roll back ALL optimistic updates — even the successful ones.
  // Do NOT change to Promise.all.
  const deleteMutation = useMutation({
    mutationFn: async (ids: string[]) => {
      const results = await Promise.allSettled(
        ids.map((id) => api.delete(`/sessions/${id}`)),
      );
      const failed = results
        .map((r, i) => (r.status === 'rejected' ? ids[i] : null))
        .filter((id): id is string => id !== null);
      if (failed.length > 0) {
        // Throw with the failed IDs so onError can do a partial rollback
        const err = new Error(
          failed.length === ids.length
            ? 'All deletes failed'
            : `${failed.length} of ${ids.length} deletes failed`,
        );
        (err as Error & { failedIds: string[] }).failedIds = failed;
        throw err;
      }
    },
    onMutate: async (ids) => {
      await queryClient.cancelQueries({ queryKey: ['sessions', 'list'] });
      const previous = queryClient.getQueryData<ListResponse>(['sessions', 'list', queryParams]);
      if (previous) {
        const idSet = new Set(ids);
        queryClient.setQueryData<ListResponse>(['sessions', 'list', queryParams], {
          ...previous,
          sessions: previous.sessions.filter((s) => !idSet.has(s.session_id)),
          total: previous.total - ids.length,
        });
      }
      setSelectedKeys(new Set());
      setConfirmDelete(false);
      return { previous };
    },
    onSuccess: () => {
      // The optimistic removal in onMutate already updated the UI.
      // Just invalidate dashboard counts + filter options.
      // Do NOT touch the session list cache — the optimistic state IS the
      // correct state (the DELETE committed on the server).
      queryClient.invalidateQueries({ queryKey: ['sessions', 'filter-options'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
    onError: (err, ids, context) => {
      // Partial failure: only restore the sessions that failed to delete.
      // The ones that succeeded stay removed — the invalidation refetch
      // will reconcile with the server.
      const failedIds: string[] =
        (err as Error & { failedIds?: string[] }).failedIds ?? ids;

      if (context?.previous && failedIds.length < ids.length) {
        // Partial failure — remove the successfully deleted ones from cache,
        // restore only the failed ones. Then refetch to reconcile.
        const failedSet = new Set(failedIds);
        const succeededIds = ids.filter((id) => !failedSet.has(id));
        if (succeededIds.length > 0) {
          const succSet = new Set(succeededIds);
          queryClient.setQueriesData<ListResponse>(
            { queryKey: ['sessions', 'list'] },
            (old) => old ? {
              ...old,
              sessions: old.sessions.filter((s) => !succSet.has(s.session_id)),
              total: Math.max(0, old.total - succeededIds.length),
            } : old,
          );
        }
      } else if (context?.previous) {
        // Total failure — roll back optimistic update
        queryClient.setQueryData(['sessions', 'list', queryParams], context.previous);
      }

      const msg = err instanceof Error ? err.message : 'Delete failed';
      setBulkStatus(`Delete failed: ${msg}`);
      console.error('[session-delete]', err);
    },
  });

  // Bulk re-analyze mutation — calls /sessions/<id>/recoach per session
  const reanalyzeMutation = useMutation({
    mutationFn: async (ids: (string | number)[]) => {
      setBulkStatus(`Re-analyzing 0/${ids.length}...`);
      let succeeded = 0;
      let failed = 0;
      await Promise.all(
        ids.map(async (id) => {
          try {
            await api.post(`/sessions/${id}/recoach`);
            succeeded++;
          } catch {
            failed++;
          }
          setBulkStatus(`Re-analyzing ${succeeded + failed}/${ids.length}...`);
        })
      );
      return { succeeded, failed };
    },
    onSuccess: (data) => {
      const msg = data.failed
        ? `Done: ${data.succeeded} succeeded, ${data.failed} failed`
        : `Done: ${data.succeeded} sessions re-analyzed`;
      setBulkStatus(msg);
      setTimeout(() => setBulkStatus(null), 3000);
      setSelectedKeys(new Set());
      queryClient.invalidateQueries({ queryKey: ['sessions'] });
    },
    onError: (err: Error) => {
      setBulkStatus(`Error: ${err.message}`);
      setTimeout(() => setBulkStatus(null), 5000);
    },
  });

  // Prefetch session detail + route on row hover
  const handleRowHover = useCallback((row: SessionRow) => {
    const href = `/app/sessions/${row.session_id}`;
    const routeKey = `route:${href}`;
    if (canPrefetch(routeKey)) {
      markPrefetched(routeKey);
      router.prefetch(href);
    }

    const dataKey = `data:session-detail-${row.session_id}`;
    if (canPrefetch(dataKey)) {
      markPrefetched(dataKey);
      incrementInFlight();
      queryClient
        .prefetchQuery({
          queryKey: ['sessions', 'detail', row.session_id],
          queryFn: () => api.get(`/sessions/${row.session_id}`),
          staleTime: 30_000,
        })
        .finally(decrementInFlight);
    }
  }, [router, queryClient]);

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
      label: archiveView === 'archived' ? 'Unarchive' : 'Archive',
      onClick: async (row) => {
        const newArchived = archiveView !== 'archived';
        // Optimistically remove from current view
        await queryClient.cancelQueries({ queryKey: ['sessions', 'list'] });
        const prev = queryClient.getQueryData<ListResponse>(['sessions', 'list', queryParams]);
        if (prev) {
          queryClient.setQueryData<ListResponse>(['sessions', 'list', queryParams], {
            ...prev,
            sessions: prev.sessions.filter((s) => s.session_id !== row.session_id),
            total: prev.total - 1,
          });
        }
        try {
          await api.post(`/sessions/${row.session_id}/archive`, { archived: newArchived });
          queryClient.invalidateQueries({ queryKey: ['sessions'] });
        } catch {
          // Rollback on failure
          if (prev) queryClient.setQueryData(['sessions', 'list', queryParams], prev);
        }
      },
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
  ], [router, deleteMutation, archiveView, queryClient, queryParams]);

  const columns = useMemo(() => [
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
  ].filter((col) => visibleCols.has(col.key)), [visibleCols]);

  return (
    <div>
      <PageIntro
        title="Sessions"
        subtitle={data ? `${total} session${total !== 1 ? 's' : ''}` : undefined}
        actions={
          <div className="flex items-center gap-2">
            {/* View toggle */}
            <div className="inline-flex rounded-lg border border-steel/20 overflow-hidden">
              <button
                type="button"
                onClick={() => setViewMode('list')}
                className={`px-2.5 py-2 text-xs font-telemetry transition-colors ${viewMode === 'list' ? 'bg-steel/20 text-chalk' : 'text-steel hover:text-chalk'}`}
                title="List view"
                aria-label="List view"
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                  <path d="M2 3h10M2 7h10M2 11h10" strokeLinecap="round" />
                </svg>
              </button>
              <button
                type="button"
                onClick={() => setViewMode('calendar')}
                className={`px-2.5 py-2 text-xs font-telemetry transition-colors ${viewMode === 'calendar' ? 'bg-steel/20 text-chalk' : 'text-steel hover:text-chalk'}`}
                title="Calendar view"
                aria-label="Calendar view"
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                  <rect x="1" y="2" width="12" height="11" rx="1" />
                  <path d="M4 1v2M10 1v2M1 5h12" strokeLinecap="round" />
                </svg>
              </button>
              <button
                type="button"
                onClick={() => setViewMode('grouped')}
                className={`px-2.5 py-2 text-xs font-telemetry transition-colors ${viewMode === 'grouped' ? 'bg-steel/20 text-chalk' : 'text-steel hover:text-chalk'}`}
                title="Grouped by event"
                aria-label="Grouped by event"
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                  <rect x="1" y="1" width="5" height="5" rx="0.5" />
                  <rect x="8" y="1" width="5" height="5" rx="0.5" />
                  <rect x="1" y="8" width="5" height="5" rx="0.5" />
                  <rect x="8" y="8" width="5" height="5" rx="0.5" />
                </svg>
              </button>
            </div>
            {/* Archive view toggle */}
            <div className="inline-flex rounded-lg border border-steel/20 overflow-hidden">
              {(['active', 'archived', 'all'] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => { setArchiveView(mode); setPage(1); }}
                  className={`px-2.5 py-2 text-[10px] font-telemetry uppercase transition-colors ${
                    archiveView === mode ? 'bg-steel/20 text-chalk' : 'text-steel hover:text-chalk'
                  }`}
                >
                  {mode === 'active' ? 'Active' : mode === 'archived' ? 'Archived' : 'All'}
                </button>
              ))}
            </div>
            <ColumnCustomizer visible={visibleCols} onChange={setVisibleCols} />
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
              className="inline-flex items-center gap-2 px-4 py-2.5 bg-gold text-white font-monument text-xs rounded-lg hover:bg-gold/90 transition-colors"
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
              placeholder:text-steel/60 focus:border-acid-green/40 focus:outline-none transition-colors"
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
                placeholder:text-steel/60 focus:border-acid-green/40 focus:outline-none transition-colors"
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
                placeholder:text-steel/60 focus:border-acid-green/40 focus:outline-none transition-colors"
              aria-label="Maximum score"
            />
          </div>
        </div>
      )}

      {/* ── Bulk Actions Bar ─────────────────────────────── */}
      {selectedKeys.size > 0 && (
        <div className="bg-asphalt border border-steel/20 rounded-lg px-4 py-2.5 mb-4 flex items-center gap-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={handleSelectAll}
              className="accent-acid-green w-4 h-4 cursor-pointer"
              aria-label="Select all visible sessions"
            />
            <span className="text-chalk font-telemetry text-xs">
              {allSelected ? 'All' : selectedKeys.size} selected
            </span>
          </label>
          {selectedKeys.size === 2 && (
            <button
              type="button"
              onClick={() => {
                const [a, b] = Array.from(selectedKeys);
                router.push(`/app/compare/sessions?a=${a}&b=${b}`);
              }}
              className="px-3 py-1.5 bg-blue-500/20 text-blue-400 border border-blue-500/30 rounded text-xs font-telemetry hover:bg-blue-500/30 transition-colors"
            >
              Compare 2 Sessions
            </button>
          )}
          {!confirmDelete ? (
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              className="text-safety-red text-xs font-body hover:text-safety-red/80 transition-colors"
            >
              Delete {selectedKeys.size} Session{selectedKeys.size !== 1 ? 's' : ''}
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
          {bulkStatus && (
            <span className="text-xs font-telemetry text-steel animate-pulse">{bulkStatus}</span>
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
        <EmptyState
          icon={
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" />
              <line x1="4" y1="22" x2="4" y2="15" />
            </svg>
          }
          title="No sessions yet"
          hint="Upload a RaceChrono, RaceBox, or MoTeC CSV to get your first analysis — score, grade, and per-corner coaching."
          action={{ label: 'Upload Session', href: '/app/sessions/upload' }}
        />
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
          {viewMode === 'calendar' && (
            <SessionCalendar sessions={sessions} />
          )}
          {viewMode === 'grouped' && (
            <SessionGroupedView
              sessions={sessions}
              onSessionClick={(id) => router.push(`/app/sessions/${id}`)}
            />
          )}
          {viewMode === 'list' && <DataTable
            columns={columns}
            data={sessions}
            keyField="session_id"
            selectable
            selectedKeys={selectedKeys}
            onSelectionChange={setSelectedKeys}
            onRowClick={(row) => router.push(`/app/sessions/${row.session_id}`)}
            onRowHover={handleRowHover}
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
          />}

          {/* ── Pagination ─────────────────────────────── */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4 px-1">
              <span className="text-steel/60 text-xs font-telemetry">
                Page {page} of {totalPages}
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
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
                      type="button"
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
                  type="button"
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
