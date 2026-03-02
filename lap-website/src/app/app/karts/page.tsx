'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useState, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, QueryError, SkeletonCardGrid } from '@/components/app';

/* ── Types ──────────────────────────────────────────────── */

interface KartRow {
  id: number;
  name: string;
  manufacturer?: string | null;
  model?: string | null;
  engine?: string | null;
  power_hp?: number | null;
  weight_kg?: number | null;
  session_count?: number;
  notes: string | null;
}

/* ── Helpers ────────────────────────────────────────────── */

function fmtPower(hp: number | null | undefined): string {
  if (hp == null || hp <= 0) return '—';
  return `${hp.toFixed(0)} hp`;
}

function fmtWeight(kg: number | null | undefined): string {
  if (kg == null || kg <= 0) return '—';
  return `${kg.toFixed(1)} kg`;
}

const ENGINE_COLORS: Record<string, string> = {
  Rotax: 'bg-pit-orange/10 text-pit-orange',
  IAME: 'bg-acid-green/10 text-acid-green',
  TM: 'bg-marshal-yellow/10 text-marshal-yellow',
  Vortex: 'bg-blue-400/10 text-blue-400',
  Honda: 'bg-safety-red/10 text-safety-red',
};

function engineBadgeClass(engine: string | null | undefined): string {
  if (!engine) return 'bg-steel/10 text-steel';
  for (const [key, cls] of Object.entries(ENGINE_COLORS)) {
    if (engine.toLowerCase().includes(key.toLowerCase())) return cls;
  }
  return 'bg-steel/10 text-steel';
}

/* ── Page ───────────────────────────────────────────────── */

export default function KartsPage() {

  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<'name' | 'sessions' | 'power'>('sessions');

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['karts'],
    queryFn: () => api.get<KartRow[]>('/karts'),
  });

  const karts = data ?? [];

  const filtered = useMemo(() => {
    let list = karts;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (k) =>
          k.name.toLowerCase().includes(q) ||
          (k.manufacturer?.toLowerCase().includes(q) ?? false) ||
          (k.engine?.toLowerCase().includes(q) ?? false),
      );
    }
    list = [...list].sort((a, b) => {
      if (sort === 'name') return a.name.localeCompare(b.name);
      if (sort === 'sessions') return (b.session_count ?? 0) - (a.session_count ?? 0);
      if (sort === 'power') return (b.power_hp ?? 0) - (a.power_hp ?? 0);
      return 0;
    });
    return list;
  }, [karts, search, sort]);

  // Aggregates
  const totalSessions = karts.reduce((s, k) => s + (k.session_count ?? 0), 0);
  const avgPower = (() => {
    const powered = karts.filter((k) => k.power_hp != null && k.power_hp > 0);
    if (powered.length === 0) return null;
    return powered.reduce((s, k) => s + k.power_hp!, 0) / powered.length;
  })();
  const avgWeight = (() => {
    const weighted = karts.filter((k) => k.weight_kg != null && k.weight_kg > 0);
    if (weighted.length === 0) return null;
    return weighted.reduce((s, k) => s + k.weight_kg!, 0) / weighted.length;
  })();

  return (
    <div>
      <PageHeader
        title="Karts"
        subtitle={`${karts.length} kart${karts.length !== 1 ? 's' : ''}`}
        actions={
          <Link
            href="/app/karts/new"
            className="px-4 py-2 bg-pit-orange text-asphalt font-telemetry text-sm rounded hover:bg-pit-orange/80 transition-colors"
          >
            + New Kart
          </Link>
        }
      />

      {/* ── Stats ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Total Karts" value={karts.length} />
        <StatCard label="Total Sessions" value={totalSessions} />
        <StatCard label="Avg Power" value={avgPower != null ? `${avgPower.toFixed(0)}` : '—'} unit="hp" />
        <StatCard label="Avg Weight" value={avgWeight != null ? `${avgWeight.toFixed(1)}` : '—'} unit="kg" />
      </div>

      {/* ── Filter Bar ──────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <input
          type="text"
          placeholder="Search karts, chassis, engines..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 min-w-0 bg-concrete border border-steel/30 rounded px-4 py-2.5 text-chalk font-body text-sm
            placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        />
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as 'name' | 'sessions' | 'power')}
          className="sm:w-44 bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
            focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        >
          <option value="sessions">Most Sessions</option>
          <option value="name">Alphabetical</option>
          <option value="power">Highest Power</option>
        </select>
      </div>

      {/* ── Content ─────────────────────────────────────── */}
      {isLoading ? (
        <SkeletonCardGrid count={6} cols={3} />
      ) : error ? (
        <QueryError message="Couldn't load karts." onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          {search ? (
            <>
              <p className="text-steel font-body text-sm">No karts match &quot;{search}&quot;</p>
              <button type="button" onClick={() => setSearch('')}
                className="mt-3 text-pit-orange font-telemetry text-xs hover:underline">
                Clear search
              </button>
            </>
          ) : (
            <>
              <div className="text-4xl mb-3" aria-hidden="true">🏎️</div>
              <h2 className="font-monument text-lg text-chalk mb-2">No karts yet</h2>
              <p className="text-steel font-body text-sm max-w-md mx-auto">
                Add your karts to track chassis, engine, and weight configurations across sessions.
              </p>
              <Link
                href="/app/karts/new"
                className="inline-block mt-4 px-6 py-2.5 bg-pit-orange text-asphalt font-telemetry text-sm rounded hover:bg-pit-orange/80 transition-colors"
              >
                Add First Kart
              </Link>
            </>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((kart) => (
            <Link
              key={kart.id}
              href={`/app/karts/${kart.id}`}
              className="group text-left bg-concrete rounded-lg border border-steel/20 p-5
                hover:border-acid-green/40 transition-all"
            >
              {/* Name + Engine badge */}
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="font-monument text-lg text-chalk group-hover:text-acid-green transition-colors truncate">
                    {kart.name}
                  </h3>
                  <span className="text-steel font-telemetry text-xs">#{kart.id}</span>
                </div>
                {kart.engine && (
                  <span className={`shrink-0 px-2 py-0.5 rounded text-[10px] font-telemetry uppercase ${engineBadgeClass(kart.engine)}`}>
                    {kart.engine}
                  </span>
                )}
              </div>

              {/* Chassis line */}
              {(kart.manufacturer || kart.model) && (
                <p className="text-steel font-body text-sm mt-1 truncate">
                  {[kart.manufacturer, kart.model].filter(Boolean).join(' ')}
                </p>
              )}

              {/* Stats row */}
              <div className="flex items-center gap-3 mt-2 text-steel font-telemetry text-xs">
                <span>{kart.session_count ?? 0} session{(kart.session_count ?? 0) !== 1 ? 's' : ''}</span>
                {kart.power_hp != null && kart.power_hp > 0 && (
                  <>
                    <span className="text-steel/20">|</span>
                    <span>{fmtPower(kart.power_hp)}</span>
                  </>
                )}
                {kart.weight_kg != null && kart.weight_kg > 0 && (
                  <>
                    <span className="text-steel/20">|</span>
                    <span>{fmtWeight(kart.weight_kg)}</span>
                  </>
                )}
              </div>

              {/* Specs grid */}
              <div className="grid grid-cols-3 gap-3 mt-3">
                <div>
                  <span className="text-steel/60 text-[10px] font-telemetry block">POWER</span>
                  <span className="text-pit-orange font-telemetry text-sm">
                    {fmtPower(kart.power_hp)}
                  </span>
                </div>
                <div>
                  <span className="text-steel/60 text-[10px] font-telemetry block">WEIGHT</span>
                  <span className="text-chalk font-telemetry text-sm">
                    {fmtWeight(kart.weight_kg)}
                  </span>
                </div>
                <div className="text-right">
                  <span className="text-steel/60 text-[10px] font-telemetry block">SESSIONS</span>
                  <span className="text-chalk font-telemetry text-sm">{kart.session_count ?? 0}</span>
                </div>
              </div>

              {/* Notes preview */}
              {kart.notes && (
                <p className="text-steel/50 font-body text-xs mt-2 truncate">
                  {kart.notes}
                </p>
              )}

              <div className="mt-3 text-right">
                <span className="text-steel/30 font-telemetry text-xs group-hover:text-acid-green transition-colors">
                  View kart →
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
