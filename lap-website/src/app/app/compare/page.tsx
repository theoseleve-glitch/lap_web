'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { PageHeader } from '@/components/app';
import { useEntitlements } from '@/hooks/useEntitlements';
import { UpgradeBanner } from '@/components/billing/UpgradeBanner';
import { api } from '@/lib/api-client';

// ── Types ────────────────────────────────────────────────────────

interface SessionListItem {
  session_id: string;
  driver_name: string;
  track_name: string | null;
  session_date: string;
}

interface DriverListItem {
  id: number;
  name: string;
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

  function handleCompare() {
    if (!canCompare) return;
    router.push(`/app/compare/sessions?a=${encodeURIComponent(sessionA)}&b=${encodeURIComponent(sessionB)}`);
  }

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
          <select
            value={sessionA}
            onChange={(e) => setSessionA(e.target.value)}
            className="w-full text-xs bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-chalk font-body
              focus:outline-none focus:ring-1 focus:ring-acid-green/50 appearance-none cursor-pointer"
          >
            <option value="">Session A...</option>
            {sessions.map((s) => (
              <option key={s.session_id} value={s.session_id}>
                {s.driver_name} — {s.track_name || 'Unknown'} ({s.session_date})
              </option>
            ))}
          </select>
          <select
            value={sessionB}
            onChange={(e) => setSessionB(e.target.value)}
            className="w-full text-xs bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-chalk font-body
              focus:outline-none focus:ring-1 focus:ring-acid-green/50 appearance-none cursor-pointer"
          >
            <option value="">Session B...</option>
            {sessions.map((s) => (
              <option key={s.session_id} value={s.session_id}>
                {s.driver_name} — {s.track_name || 'Unknown'} ({s.session_date})
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
      <PageHeader
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
