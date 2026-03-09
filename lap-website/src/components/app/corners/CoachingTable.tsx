'use client';

import { useState, useMemo } from 'react';
import type { CornerData } from './CornersTab';

interface CoachingTableProps {
  corners: CornerData[];
}

type SortKey = 'corner_id' | 'time_loss_total_s';
type SortDir = 'asc' | 'desc';

/* ── Helpers ───────────────────────────────────────────── */

function mpsToKmh(mps: number | null | undefined): number | null {
  if (mps == null) return null;
  return mps * 3.6;
}

function fmtKmh(kmh: number | null): string {
  if (kmh == null) return '--';
  return kmh.toFixed(1);
}

function timeLossMs(seconds: number | null | undefined): number | null {
  if (seconds == null) return null;
  return Math.round(seconds * 1000);
}

function timeLossColor(ms: number | null): string {
  if (ms == null) return 'text-steel';
  if (ms < 50) return 'text-acid-green';
  if (ms < 150) return 'text-yellow-400';
  if (ms <= 300) return 'text-amber-400';
  return 'text-safety-red';
}

function timeLossBg(ms: number | null): string {
  if (ms == null) return 'bg-steel/10';
  if (ms < 50) return 'bg-acid-green/10';
  if (ms < 150) return 'bg-yellow-400/10';
  if (ms <= 300) return 'bg-amber-400/10';
  return 'bg-safety-red/10';
}

function gripColor(pct: number | null | undefined): string {
  if (pct == null) return 'text-steel';
  if (pct >= 85) return 'text-acid-green';
  if (pct >= 70) return 'text-yellow-400';
  if (pct >= 50) return 'text-amber-400';
  return 'text-safety-red';
}

function dirLabel(dir?: 'L' | 'R'): string {
  if (dir === 'L') return 'Left';
  if (dir === 'R') return 'Right';
  return '';
}

function dirColor(dir?: 'L' | 'R'): string {
  if (dir === 'L') return 'text-blue-400';
  if (dir === 'R') return 'text-orange-400';
  return 'text-steel';
}

/** Speed comparison bar: actual vs theoretical. */
function SpeedBar({ label, actual, theory }: { label: string; actual: number | null; theory: number | null }) {
  const maxKmh = Math.max(actual ?? 0, theory ?? 0, 1);
  const actualPct = actual != null ? (actual / maxKmh) * 100 : 0;
  const theoryPct = theory != null ? (theory / maxKmh) * 100 : 0;
  const delta = actual != null && theory != null ? actual - theory : null;
  const deltaColor = delta == null ? 'text-steel' : delta >= 0 ? 'text-acid-green' : 'text-safety-red';

  return (
    <div className="mb-2.5">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] font-telemetry uppercase tracking-wider text-steel/60">{label}</span>
        <div className="flex items-center gap-2 text-[10px] font-mono">
          <span className="text-chalk">{fmtKmh(actual)}</span>
          <span className="text-steel/50">/</span>
          <span className="text-steel/50">{fmtKmh(theory)}</span>
          {delta != null && (
            <span className={`${deltaColor} font-telemetry`}>
              {delta >= 0 ? '+' : ''}{delta.toFixed(1)}
            </span>
          )}
        </div>
      </div>
      <div className="relative h-2 rounded-full bg-steel/10 overflow-hidden">
        {/* Theoretical (background bar) */}
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-steel/20"
          style={{ width: `${theoryPct}%` }}
        />
        {/* Actual (foreground bar) */}
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-acid-green/70 transition-all duration-300"
          style={{ width: `${actualPct}%` }}
        />
      </div>
    </div>
  );
}

/** Grip utilization gauge. */
function GripGauge({ pct }: { pct: number | null | undefined }) {
  const value = pct ?? 0;
  const color = gripColor(pct);
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full bg-steel/10 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-300 ${
            value >= 85 ? 'bg-acid-green/70' :
            value >= 70 ? 'bg-yellow-400/70' :
            value >= 50 ? 'bg-amber-400/70' : 'bg-safety-red/70'
          }`}
          style={{ width: `${Math.min(value, 100)}%` }}
        />
      </div>
      <span className={`text-xs font-mono ${color} min-w-[32px] text-right`}>
        {pct != null ? `${pct.toFixed(0)}%` : '--'}
      </span>
    </div>
  );
}

/* ── Corner Card ──────────────────────────────────────── */

function CornerCard({ corner, expanded, onToggle, rank }: {
  corner: CornerData;
  expanded: boolean;
  onToggle: () => void;
  rank: number | null;
}) {
  const entryKmh = mpsToKmh(corner.entry_speed_actual);
  const entryTheory = mpsToKmh(corner.entry_speed_theory);
  const apexKmh = mpsToKmh(corner.apex_speed_actual);
  const apexTheory = mpsToKmh(corner.apex_speed_theory);
  const exitKmh = mpsToKmh(corner.exit_speed_actual);
  const exitTheory = mpsToKmh(corner.exit_speed_theory);
  const lossMs = timeLossMs(corner.time_loss_total_s);

  return (
    <div className={`rounded-lg border transition-colors ${
      expanded ? 'border-steel/30 bg-concrete' : 'border-steel/10 bg-concrete/80 hover:border-steel/20'
    } ${!corner.available ? 'opacity-50' : ''}`}>
      {/* Header — always visible */}
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 text-left"
      >
        {/* Corner number + direction */}
        <div className="flex items-center gap-2 min-w-[80px]">
          <span className="text-lg font-monument text-chalk">C{corner.corner_id}</span>
          {corner.direction && (
            <span className={`text-[10px] font-telemetry uppercase ${dirColor(corner.direction)}`}>
              {dirLabel(corner.direction)}
            </span>
          )}
        </div>

        {/* Quick stats strip */}
        <div className="flex-1 flex items-center gap-4 overflow-hidden">
          <div className="flex items-center gap-1.5">
            <span className="text-[9px] font-telemetry text-steel/60 uppercase">Apex</span>
            <span className="text-xs font-mono text-chalk">{fmtKmh(apexKmh)} km/h</span>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="text-[9px] font-telemetry text-steel/60 uppercase">Grip</span>
            <span className={`text-xs font-mono ${gripColor(corner.grip_utilisation_pct)}`}>
              {corner.grip_utilisation_pct != null ? `${corner.grip_utilisation_pct.toFixed(0)}%` : '--'}
            </span>
          </div>

          {/* Time loss badge */}
          <div className={`px-2 py-0.5 rounded ${timeLossBg(lossMs)}`}>
            <span className={`text-xs font-mono ${timeLossColor(lossMs)}`}>
              {lossMs != null ? `+${lossMs}ms` : '--'}
            </span>
          </div>

          {/* Priority rank badge */}
          {rank != null && rank <= 3 && (
            <span className="text-[9px] font-telemetry uppercase tracking-wider text-safety-red bg-safety-red/10 px-1.5 py-0.5 rounded">
              #{rank} priority
            </span>
          )}
        </div>

        {/* Expand arrow */}
        <svg
          className={`w-4 h-4 text-steel transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Expanded detail panel */}
      {expanded && (
        <div className="px-4 pb-4 border-t border-steel/10 pt-3">
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_1fr] gap-6">
            {/* Left: Speed comparison bars */}
            <div>
              <h4 className="text-[10px] font-telemetry uppercase tracking-wider text-steel mb-3">
                Speed Analysis (actual / theoretical) km/h
              </h4>
              <SpeedBar label="Entry" actual={entryKmh} theory={entryTheory} />
              <SpeedBar label="Apex" actual={apexKmh} theory={apexTheory} />
              <SpeedBar label="Exit" actual={exitKmh} theory={exitTheory} />

              <div className="mt-3">
                <h4 className="text-[10px] font-telemetry uppercase tracking-wider text-steel mb-2">
                  Grip Utilization
                </h4>
                <GripGauge pct={corner.grip_utilisation_pct} />
              </div>
            </div>

            {/* Right: Time loss + coaching */}
            <div>
              {/* Time loss */}
              <h4 className="text-[10px] font-telemetry uppercase tracking-wider text-steel mb-2">
                Time Loss Breakdown
              </h4>
              <div className="flex items-baseline gap-2 mb-3">
                <span className={`text-2xl font-monument ${timeLossColor(lossMs)}`}>
                  {lossMs != null ? `+${lossMs}` : '--'}
                </span>
                <span className="text-xs text-steel font-telemetry">ms total</span>
              </div>

              {/* Primary cause */}
              {corner.primary_cause && (
                <div className="mb-3 px-3 py-2 rounded bg-amber-400/5 border border-amber-400/20">
                  <span className="text-[10px] font-telemetry uppercase tracking-wider text-amber-400/60">Primary Cause</span>
                  <p className="text-sm text-amber-400 font-body mt-0.5">{corner.primary_cause}</p>
                </div>
              )}

              {/* Coaching hint */}
              {corner.coaching_hint && (
                <div className="px-3 py-2 rounded bg-acid-green/5 border border-acid-green/20">
                  <span className="text-[10px] font-telemetry uppercase tracking-wider text-acid-green/60">Coaching</span>
                  <p className="text-sm text-acid-green/90 font-body mt-0.5 leading-relaxed">
                    {corner.coaching_hint}
                  </p>
                </div>
              )}

              {!corner.coaching_hint && !corner.primary_cause && corner.available && (
                <p className="text-xs text-steel/50 font-telemetry italic">
                  No coaching data generated for this corner.
                </p>
              )}
              {!corner.available && (
                <p className="text-xs text-steel/50 font-telemetry italic">
                  Theoretical data unavailable — coaching not computed.
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Summary Stats Row ────────────────────────────────── */

function SummaryStats({ corners }: { corners: CornerData[] }) {
  const available = corners.filter((c) => c.available);
  const totalLossMs = available.reduce((sum, c) => sum + (timeLossMs(c.time_loss_total_s) ?? 0), 0);
  const avgGrip = available.length > 0
    ? available.reduce((sum, c) => sum + (c.grip_utilisation_pct ?? 0), 0) / available.length
    : null;
  const worstCorner = available.length > 0
    ? available.reduce((worst, c) =>
        (timeLossMs(c.time_loss_total_s) ?? 0) > (timeLossMs(worst.time_loss_total_s) ?? 0) ? c : worst
      )
    : null;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
      <div className="bg-concrete rounded-lg border border-steel/10 px-4 py-3">
        <p className="text-[10px] font-telemetry uppercase tracking-wider text-steel/60 mb-1">Corners</p>
        <p className="text-lg font-monument text-chalk">{corners.length}</p>
        <p className="text-[10px] font-telemetry text-steel/60">{available.length} with data</p>
      </div>
      <div className="bg-concrete rounded-lg border border-steel/10 px-4 py-3">
        <p className="text-[10px] font-telemetry uppercase tracking-wider text-steel/60 mb-1">Total Time Lost</p>
        <p className={`text-lg font-monument ${timeLossColor(totalLossMs)}`}>
          {totalLossMs > 0 ? `+${totalLossMs}ms` : '--'}
        </p>
        <p className="text-[10px] font-telemetry text-steel/60">across all corners</p>
      </div>
      <div className="bg-concrete rounded-lg border border-steel/10 px-4 py-3">
        <p className="text-[10px] font-telemetry uppercase tracking-wider text-steel/60 mb-1">Avg Grip</p>
        <p className={`text-lg font-monument ${gripColor(avgGrip)}`}>
          {avgGrip != null ? `${avgGrip.toFixed(0)}%` : '--'}
        </p>
        <p className="text-[10px] font-telemetry text-steel/60">utilization</p>
      </div>
      <div className="bg-concrete rounded-lg border border-steel/10 px-4 py-3">
        <p className="text-[10px] font-telemetry uppercase tracking-wider text-steel/60 mb-1">Biggest Loss</p>
        <p className={`text-lg font-monument ${timeLossColor(timeLossMs(worstCorner?.time_loss_total_s))}`}>
          {worstCorner ? `C${worstCorner.corner_id}` : '--'}
        </p>
        <p className="text-[10px] font-telemetry text-steel/60">
          {worstCorner ? `+${timeLossMs(worstCorner.time_loss_total_s)}ms` : ''}
        </p>
      </div>
    </div>
  );
}

/* ── Main Component ──────────────────────────────────── */

export function CoachingTable({ corners }: CoachingTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('time_loss_total_s');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [expandAll, setExpandAll] = useState(false);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir(key === 'time_loss_total_s' ? 'desc' : 'asc');
    }
  };

  // Rank corners by time loss (for priority badges)
  const ranked = useMemo(() => {
    const withLoss = corners
      .filter((c) => c.time_loss_total_s != null && c.time_loss_total_s > 0)
      .sort((a, b) => (b.time_loss_total_s ?? 0) - (a.time_loss_total_s ?? 0));
    const rankMap = new Map<number, number>();
    withLoss.forEach((c, i) => rankMap.set(c.corner_id, i + 1));
    return rankMap;
  }, [corners]);

  const sorted = useMemo(() => {
    return [...corners].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [corners, sortKey, sortDir]);

  if (corners.length === 0) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/10 p-6 text-center">
        <p className="text-steel font-telemetry text-xs">No corners selected.</p>
      </div>
    );
  }

  return (
    <div>
      {/* Summary stats */}
      <SummaryStats corners={corners} />

      {/* Sort + expand controls */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-telemetry uppercase tracking-wider text-steel/60">Sort by</span>
          <button
            type="button"
            onClick={() => handleSort('corner_id')}
            className={`text-[10px] font-telemetry px-2 py-1 rounded transition-colors ${
              sortKey === 'corner_id' ? 'bg-steel/10 text-chalk' : 'text-steel hover:text-chalk'
            }`}
          >
            Corner #{sortKey === 'corner_id' ? (sortDir === 'asc' ? ' \u2191' : ' \u2193') : ''}
          </button>
          <button
            type="button"
            onClick={() => handleSort('time_loss_total_s')}
            className={`text-[10px] font-telemetry px-2 py-1 rounded transition-colors ${
              sortKey === 'time_loss_total_s' ? 'bg-steel/10 text-chalk' : 'text-steel hover:text-chalk'
            }`}
          >
            Time Loss{sortKey === 'time_loss_total_s' ? (sortDir === 'asc' ? ' \u2191' : ' \u2193') : ''}
          </button>
        </div>
        <button
          type="button"
          onClick={() => {
            setExpandAll(!expandAll);
            setExpandedId(null);
          }}
          className="text-[10px] font-telemetry text-pit-orange hover:text-pit-orange/80 transition-colors"
        >
          {expandAll ? 'Collapse All' : 'Expand All'}
        </button>
      </div>

      {/* Corner cards */}
      <div className="space-y-2">
        {sorted.map((c) => (
          <CornerCard
            key={c.corner_id}
            corner={c}
            expanded={expandAll || expandedId === c.corner_id}
            onToggle={() => {
              if (expandAll) return;
              setExpandedId(expandedId === c.corner_id ? null : c.corner_id);
            }}
            rank={ranked.get(c.corner_id) ?? null}
          />
        ))}
      </div>
    </div>
  );
}
