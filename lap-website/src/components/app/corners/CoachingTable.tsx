'use client';

import { useState, useMemo } from 'react';
import type { CornerData } from './CornersTab';

interface CoachingTableProps {
  corners: CornerData[];
}

type SortKey = 'corner_id' | 'time_loss_total_s' | 'grip_utilisation_pct';
type SortDir = 'asc' | 'desc';

function mpsToKmh(mps: number | null | undefined): string {
  if (mps == null) return '--';
  return (mps * 3.6).toFixed(1);
}

function timeLossMs(seconds: number | null | undefined): number | null {
  if (seconds == null) return null;
  return Math.round(seconds * 1000);
}

function timeLossColor(ms: number | null): string {
  if (ms == null) return 'text-steel';
  if (ms < 100) return 'text-green-400';
  if (ms <= 300) return 'text-yellow-400';
  return 'text-red-400';
}

function directionBadge(dir?: 'L' | 'R') {
  if (!dir) return null;
  const color = dir === 'L' ? 'text-blue-400 bg-blue-400/10' : 'text-orange-400 bg-orange-400/10';
  return (
    <span className={`ml-1 text-[9px] px-1 py-0.5 rounded font-telemetry ${color}`}>
      {dir}
    </span>
  );
}

export function CoachingTable({ corners }: CoachingTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('corner_id');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

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

  const sortArrow = (key: SortKey) => {
    if (sortKey !== key) return null;
    return (
      <span className="ml-0.5" aria-hidden="true">
        {sortDir === 'asc' ? '\u2191' : '\u2193'}
      </span>
    );
  };

  const thClass =
    'text-left px-3 py-2.5 text-steel font-telemetry text-[10px] uppercase tracking-wider cursor-pointer hover:text-chalk select-none whitespace-nowrap';

  if (corners.length === 0) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/10 p-6 text-center">
        <p className="text-steel font-telemetry text-xs">No corners selected.</p>
      </div>
    );
  }

  return (
    <div className="bg-concrete rounded-lg border border-steel/10 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-steel/10">
              <th
                className={thClass}
                onClick={() => handleSort('corner_id')}
                aria-sort={sortKey === 'corner_id' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
              >
                Corner {sortArrow('corner_id')}
              </th>
              <th className="text-left px-3 py-2.5 text-steel font-telemetry text-[10px] uppercase tracking-wider whitespace-nowrap">
                Entry km/h
              </th>
              <th className="text-left px-3 py-2.5 text-steel font-telemetry text-[10px] uppercase tracking-wider whitespace-nowrap">
                Apex km/h
              </th>
              <th className="text-left px-3 py-2.5 text-steel font-telemetry text-[10px] uppercase tracking-wider whitespace-nowrap">
                Exit km/h
              </th>
              <th className="text-left px-3 py-2.5 text-steel font-telemetry text-[10px] uppercase tracking-wider whitespace-nowrap">
                Grip %
              </th>
              <th
                className={thClass}
                onClick={() => handleSort('time_loss_total_s')}
                aria-sort={sortKey === 'time_loss_total_s' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
              >
                Time Loss {sortArrow('time_loss_total_s')}
              </th>
              <th className="text-left px-3 py-2.5 text-steel font-telemetry text-[10px] uppercase tracking-wider whitespace-nowrap">
                Coaching
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((c) => {
              const lossMs = timeLossMs(c.time_loss_total_s);
              return (
                <tr
                  key={c.corner_id}
                  className={`border-b border-steel/5 last:border-0 ${
                    !c.available ? 'opacity-40' : ''
                  }`}
                >
                  {/* Corner # + direction */}
                  <td className="px-3 py-2 text-chalk font-mono text-xs whitespace-nowrap">
                    C{c.corner_id}
                    {directionBadge(c.direction)}
                  </td>

                  {/* Entry speed: actual / theoretical */}
                  <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">
                    <span className="text-chalk">{mpsToKmh(c.entry_speed_actual)}</span>
                    <span className="text-steel/40 mx-0.5">/</span>
                    <span className="text-steel">{mpsToKmh(c.entry_speed_theory)}</span>
                  </td>

                  {/* Apex speed */}
                  <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">
                    <span className="text-chalk">{mpsToKmh(c.apex_speed_actual)}</span>
                    <span className="text-steel/40 mx-0.5">/</span>
                    <span className="text-steel">{mpsToKmh(c.apex_speed_theory)}</span>
                  </td>

                  {/* Exit speed */}
                  <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">
                    <span className="text-chalk">{mpsToKmh(c.exit_speed_actual)}</span>
                    <span className="text-steel/40 mx-0.5">/</span>
                    <span className="text-steel">{mpsToKmh(c.exit_speed_theory)}</span>
                  </td>

                  {/* Grip utilisation */}
                  <td className="px-3 py-2 font-mono text-xs text-chalk">
                    {c.grip_utilisation_pct != null
                      ? `${c.grip_utilisation_pct.toFixed(0)}%`
                      : '--'}
                  </td>

                  {/* Time loss */}
                  <td className={`px-3 py-2 font-mono text-xs ${timeLossColor(lossMs)}`}>
                    {lossMs != null ? `${lossMs} ms` : '--'}
                  </td>

                  {/* Coaching hint */}
                  <td className="px-3 py-2 text-steel text-xs max-w-[180px] truncate">
                    {c.coaching_hint ?? '--'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
