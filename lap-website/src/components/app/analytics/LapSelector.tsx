/**
 * LapSelector — session-level primary + compare lap picker.
 *
 * Two compact dropdowns that drive every chart on the analytics page:
 *   PRIMARY — which lap is the "your data" line (gold)
 *   COMPARE — optional second lap, rendered as the in-session reference
 *
 * Placed in the page controls strip above tier 01. Every chart receives
 * `controlledLap=true` so internal per-chart lap dropdowns disappear —
 * one selection here controls all charts.
 *
 * Cross-session reference lap is a separate concept (the ReferenceFAB).
 */

'use client';

import { useEffect, useMemo, useState } from 'react';
import { api } from '@/lib/api-client';

interface LapData {
  lap_number: number;
  lap_time_s: number | null;
  is_best: number;
  is_valid: number;
}

export interface LapSelectorProps {
  sessionId: string;
  primaryLap: number | null;
  compareLap: number | null;
  onPrimaryChange: (lap: number | null) => void;
  onCompareChange: (lap: number | null) => void;
}

function formatLapTime(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return '—';
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  return m > 0
    ? `${m}:${sec.toFixed(2).padStart(5, '0')}`
    : `${sec.toFixed(2)}s`;
}

function labelFor(lap: LapData): string {
  const time = formatLapTime(lap.lap_time_s);
  const marker = lap.is_best ? '★' : !lap.is_valid ? '✕' : '';
  return `L${lap.lap_number} · ${time}${marker ? ` ${marker}` : ''}`;
}

export function LapSelector({
  sessionId,
  primaryLap,
  compareLap,
  onPrimaryChange,
  onCompareChange,
}: LapSelectorProps) {
  const [laps, setLaps] = useState<LapData[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<{ laps: LapData[] }>(
          `/sessions/${sessionId}/laps`,
        );
        if (!cancelled) setLaps(res.laps ?? []);
      } catch {
        /* silent — dropdowns will show empty */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const orderedLaps = useMemo(
    () => [...laps].sort((a, b) => a.lap_number - b.lap_number),
    [laps],
  );

  if (orderedLaps.length < 2) return null;

  return (
    <div className="flex items-center gap-2 font-telemetry">
      {/* PRIMARY */}
      <div className="flex items-center gap-1.5 bg-concrete border border-gold/40 rounded px-2 py-1">
        <span className="text-[9px] uppercase tracking-[0.2em] text-gold/80">
          Primary
        </span>
        <select
          value={primaryLap ?? ''}
          onChange={(e) => onPrimaryChange(Number(e.target.value) || null)}
          className="bg-transparent text-[11px] text-chalk focus:outline-none cursor-pointer appearance-none pr-4"
          style={{
            backgroundImage:
              "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23C9A84C'/%3E%3C/svg%3E\")",
            backgroundRepeat: 'no-repeat',
            backgroundPosition: 'right 0 center',
          }}
          aria-label="Primary lap"
        >
          {orderedLaps.map((l) => (
            <option
              key={l.lap_number}
              value={l.lap_number}
              style={{ backgroundColor: '#141414', color: '#F0EDE5' }}
            >
              {labelFor(l)}
            </option>
          ))}
        </select>
      </div>

      {/* COMPARE */}
      <div
        className={`flex items-center gap-1.5 bg-concrete border rounded px-2 py-1 transition-colors ${
          compareLap != null
            ? 'border-racing-purple/50'
            : 'border-steel/25'
        }`}
      >
        <span
          className={`text-[9px] uppercase tracking-[0.2em] ${
            compareLap != null ? 'text-racing-purple' : 'text-steel'
          }`}
        >
          Compare
        </span>
        <select
          value={compareLap ?? ''}
          onChange={(e) => {
            const v = e.target.value;
            onCompareChange(v === '' ? null : Number(v));
          }}
          className="bg-transparent text-[11px] text-chalk focus:outline-none cursor-pointer appearance-none pr-4"
          style={{
            backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23${
              compareLap != null ? '8B5CF6' : '949494'
            }'/%3E%3C/svg%3E")`,
            backgroundRepeat: 'no-repeat',
            backgroundPosition: 'right 0 center',
          }}
          aria-label="Compare lap"
        >
          <option value="" style={{ backgroundColor: '#141414', color: '#F0EDE5' }}>
            None
          </option>
          {orderedLaps
            .filter((l) => l.lap_number !== primaryLap)
            .map((l) => (
              <option
                key={l.lap_number}
                value={l.lap_number}
                style={{ backgroundColor: '#141414', color: '#F0EDE5' }}
              >
                {labelFor(l)}
              </option>
            ))}
        </select>
        {compareLap != null && (
          <button
            type="button"
            onClick={() => onCompareChange(null)}
            className="text-steel hover:text-safety-red transition-colors text-xs leading-none -ml-1"
            aria-label="Clear compare lap"
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}
