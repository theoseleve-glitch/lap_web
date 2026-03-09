'use client';

import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { PageIntro } from '@/components/ui/PageIntro';
import { useEntitlements } from '@/hooks/useEntitlements';
import { UpgradeBanner } from '@/components/billing/UpgradeBanner';
import { api } from '@/lib/api-client';
import { formatLapTime } from '@/lib/format-utils';

// ── Types ────────────────────────────────────────────────────────

interface SessionListItem {
  session_id: string;
  driver_name: string;
  track_name: string | null;
  session_date: string;
  n_laps?: number;
  best_lap_time_s?: number | null;
  total_score?: number | null;
  grade?: string | null;
  session_type?: string | null;
}

interface DriverListItem {
  id: number;
  name: string;
}

// ── Searchable Session Picker ─────────────────────────────────────

function SessionPicker({
  sessions,
  selectedId,
  onSelect,
  excludeId,
  placeholder,
}: {
  sessions: SessionListItem[];
  selectedId: string;
  onSelect: (id: string) => void;
  excludeId: string;
  placeholder: string;
}) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    return sessions.filter((s) => {
      if (s.session_id === excludeId) return false;
      if (!q) return true;
      return (
        s.driver_name.toLowerCase().includes(q) ||
        (s.track_name || '').toLowerCase().includes(q) ||
        s.session_date.includes(q) ||
        (s.session_type || '').toLowerCase().includes(q)
      );
    });
  }, [sessions, query, excludeId]);

  const selected = sessions.find((s) => s.session_id === selectedId);

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  return (
    <div ref={containerRef} className="relative">
      {/* Selected display / trigger */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full text-left text-xs bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-chalk font-body
          focus:outline-none focus:ring-1 focus:ring-acid-green/50 cursor-pointer hover:border-zinc-600 transition-colors"
      >
        {selected ? (
          <span>
            <span className="text-acid-green">{selected.driver_name}</span>
            {' — '}
            {selected.track_name || 'Unknown'} ({selected.session_date})
            {selected.best_lap_time_s != null && (
              <span className="text-steel ml-1">{formatLapTime(selected.best_lap_time_s)}</span>
            )}
          </span>
        ) : (
          <span className="text-steel">{placeholder}</span>
        )}
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full bg-zinc-900 border border-zinc-700 rounded shadow-xl max-h-64 overflow-hidden flex flex-col">
          {/* Search input */}
          <div className="p-1.5 border-b border-zinc-700">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search driver, track, date..."
              className="w-full text-xs bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-chalk font-body
                focus:outline-none focus:ring-1 focus:ring-acid-green/50 placeholder:text-zinc-500"
              autoFocus
            />
          </div>
          {/* Results */}
          <div className="overflow-y-auto max-h-52">
            {filtered.length === 0 ? (
              <div className="px-2 py-3 text-center text-zinc-500 text-xs font-body">No sessions match</div>
            ) : (
              filtered.map((s) => (
                <button
                  key={s.session_id}
                  type="button"
                  onClick={() => {
                    onSelect(s.session_id);
                    setOpen(false);
                    setQuery('');
                  }}
                  className={`w-full text-left px-2 py-1.5 text-xs font-body hover:bg-zinc-800 transition-colors
                    ${s.session_id === selectedId ? 'bg-zinc-800 text-acid-green' : 'text-chalk'}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate">
                      <span className="font-medium">{s.driver_name}</span>
                      {' — '}
                      {s.track_name || 'Unknown'}
                    </span>
                    <span className="text-steel shrink-0">{s.session_date}</span>
                  </div>
                  <div className="flex items-center gap-3 mt-0.5 text-steel">
                    {s.n_laps != null && <span>{s.n_laps} laps</span>}
                    {s.best_lap_time_s != null && (
                      <span>Best: {formatLapTime(s.best_lap_time_s)}</span>
                    )}
                    {s.total_score != null && (
                      <span>Score: {Math.round(s.total_score)}{s.grade ? ` (${s.grade})` : ''}</span>
                    )}
                    {s.session_type && <span className="capitalize">{s.session_type}</span>}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Quick Start: Sessions ────────────────────────────────────────

function SessionQuickStart({ disabled }: { disabled: boolean }) {
  const router = useRouter();
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [sessionA, setSessionA] = useState('');
  const [sessionB, setSessionB] = useState('');

  useEffect(() => {
    if (disabled) return;
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const res = await api.get<{ sessions: SessionListItem[] }>('/sessions?limit=100');
        if (!cancelled) setSessions(res.sessions || []);
      } catch {
        // non-critical
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [disabled]);

  const canCompare = sessionA !== '' && sessionB !== '' && sessionA !== sessionB;

  const handleCompare = useCallback(() => {
    if (!canCompare) return;
    router.push(`/app/compare/sessions?a=${encodeURIComponent(sessionA)}&b=${encodeURIComponent(sessionB)}`);
  }, [canCompare, sessionA, sessionB, router]);

  if (disabled) return null;

  return (
    <div className="mt-4 pt-4 border-t border-steel/10">
      <p className="text-xs font-monument uppercase tracking-wider text-steel mb-3">Quick Start</p>
      {loading ? (
        <div className="flex items-center gap-2 py-2">
          <div className="w-3 h-3 border border-acid-green border-t-transparent rounded-full animate-spin" />
          <span className="text-steel text-xs font-body">Loading sessions...</span>
        </div>
      ) : (
        <div className="space-y-2">
          <SessionPicker
            sessions={sessions}
            selectedId={sessionA}
            onSelect={setSessionA}
            excludeId={sessionB}
            placeholder="Session A..."
          />
          <SessionPicker
            sessions={sessions}
            selectedId={sessionB}
            onSelect={setSessionB}
            excludeId={sessionA}
            placeholder="Session B..."
          />
          <button
            type="button"
            disabled={!canCompare}
            onClick={handleCompare}
            className="bg-[#3ddc84] text-zinc-900 text-xs font-medium px-3 py-1 rounded
              disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[#34c575] transition-colors"
          >
            Compare
          </button>
        </div>
      )}
    </div>
  );
}

// ── Quick Start: Drivers ─────────────────────────────────────────

function DriverQuickStart({ disabled }: { disabled: boolean }) {
  const router = useRouter();
  const [drivers, setDrivers] = useState<DriverListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [driverA, setDriverA] = useState('');
  const [driverB, setDriverB] = useState('');

  useEffect(() => {
    if (disabled) return;
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const res = await api.get<DriverListItem[]>('/drivers');
        if (!cancelled) setDrivers(Array.isArray(res) ? res : []);
      } catch {
        // non-critical
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [disabled]);

  const canCompare = driverA !== '' && driverB !== '' && driverA !== driverB;

  function handleCompare() {
    if (!canCompare) return;
    router.push(`/app/compare/drivers?a=${encodeURIComponent(driverA)}&b=${encodeURIComponent(driverB)}`);
  }

  if (disabled) return null;

  return (
    <div className="mt-4 pt-4 border-t border-steel/10">
      <p className="text-xs font-monument uppercase tracking-wider text-steel mb-3">Quick Start</p>
      {loading ? (
        <div className="flex items-center gap-2 py-2">
          <div className="w-3 h-3 border border-acid-green border-t-transparent rounded-full animate-spin" />
          <span className="text-steel text-xs font-body">Loading drivers...</span>
        </div>
      ) : (
        <div className="space-y-2">
          <select
            value={driverA}
            onChange={(e) => setDriverA(e.target.value)}
            className="w-full text-xs bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-chalk font-body
              focus:outline-none focus:ring-1 focus:ring-acid-green/50 appearance-none cursor-pointer"
          >
            <option value="">Driver A...</option>
            {drivers.map((d) => (
              <option key={d.id} value={String(d.id)}>
                {d.name}
              </option>
            ))}
          </select>
          <select
            value={driverB}
            onChange={(e) => setDriverB(e.target.value)}
            className="w-full text-xs bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-chalk font-body
              focus:outline-none focus:ring-1 focus:ring-acid-green/50 appearance-none cursor-pointer"
          >
            <option value="">Driver B...</option>
            {drivers.map((d) => (
              <option key={d.id} value={String(d.id)}>
                {d.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={!canCompare}
            onClick={handleCompare}
            className="bg-[#3ddc84] text-zinc-900 text-xs font-medium px-3 py-1 rounded
              disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[#34c575] transition-colors"
          >
            Compare
          </button>
        </div>
      )}
    </div>
  );
}

// ── Hub Page ─────────────────────────────────────────────────────

const compareCards = [
  {
    key: 'sessions',
    title: 'Compare Sessions',
    description:
      'Put two sessions side-by-side to see how lap times, scores, and driving style differ across different outings.',
    href: '/app/compare/sessions',
    icon: '\u25CE', // ◎
  },
  {
    key: 'drivers',
    title: 'Compare Drivers',
    description:
      'Benchmark two drivers head-to-head with performance radar, pace metrics, and consistency analysis.',
    href: '/app/compare/drivers',
    icon: '\u25C8', // ◈
  },
];

export default function CompareHubPage() {
  const { canUse } = useEntitlements();
  const comparisonAllowed = canUse('comparison');

  return (
    <div>
      <PageIntro
        title="Compare"
        subtitle="Side-by-side analysis of sessions and drivers"
      />

      {!comparisonAllowed && (
        <div className="mb-6">
          <UpgradeBanner
            feature="comparison"
            context="Session comparison is available on the World-Class plan"
          />
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-2">
        {compareCards.map((card) => (
          <div
            key={card.key}
            className={`bg-concrete rounded-lg border border-steel/20 p-6 transition-colors ${
              comparisonAllowed
                ? 'hover:border-acid-green/40'
                : 'opacity-50'
            }`}
          >
            <Link
              href={comparisonAllowed ? card.href : '#'}
              className={`group block ${!comparisonAllowed ? 'pointer-events-none' : ''}`}
              aria-disabled={!comparisonAllowed}
            >
              <div className="flex items-start gap-4">
                <span className="font-telemetry text-3xl text-acid-green">{card.icon}</span>
                <div>
                  <h2 className="font-monument text-xl text-chalk group-hover:text-acid-green transition-colors">
                    {card.title}
                  </h2>
                  <p className="mt-2 text-steel font-body text-sm leading-relaxed">
                    {card.description}
                  </p>
                </div>
              </div>
              <div className="mt-4 text-right">
                <span className="font-telemetry text-xs text-steel group-hover:text-acid-green transition-colors">
                  {comparisonAllowed ? 'Open \u2192' : 'Requires World-Class'}
                </span>
              </div>
            </Link>

            {card.key === 'sessions' && (
              <SessionQuickStart disabled={!comparisonAllowed} />
            )}
            {card.key === 'drivers' && (
              <DriverQuickStart disabled={!comparisonAllowed} />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
