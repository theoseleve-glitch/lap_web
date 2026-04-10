/**
 * CornerCoachingV4.tsx — Per-corner aggregate coaching ranked by time loss.
 *
 * Fetches the v4 corner-coaching endpoint (multi-session proven envelope)
 * and displays:
 *   - Summary card: total time loss, narrative, session count
 *   - Per-corner cards: speed comparison, root cause badges, narrative
 *
 * Filters out corners with time_loss_s < 0.03 (noise floor).
 * Gracefully handles 404 when not enough sessions are available.
 */
'use client';

import { useEffect, useState, useRef } from 'react';
import { apiFetch, ApiError } from '@/lib/api-client';

/* ── Types ────────────────────────────────────────────────────────── */

interface SpeedSnapshot {
  entry_kph: number;
  apex_kph: number;
  exit_kph: number;
  brake_point_m: number;
}

interface CornerV4 {
  corner_id: number;
  corner_name: string;
  direction: string;
  radius_m: number;
  time_loss_s: number;
  proven: SpeedSnapshot;
  actual: SpeedSnapshot;
  root_causes: string[];
  narrative: string;
  aggregate_sessions: number;
  grip_headroom_pct: number;
}

interface SummaryV4 {
  total_time_loss_s: number;
  top_3_corners: number[];
  aggregate_sessions: number;
  narrative: string;
}

interface CornerCoachingV4Response {
  corners: CornerV4[];
  summary: SummaryV4;
}

interface CornerCoachingV4Props {
  sessionId: string;
  className?: string;
}

/* ── Root-cause badge styling ─────────────────────────────────────── */

const ROOT_CAUSE_STYLES: Record<string, string> = {
  early_brake:
    'bg-marshal-yellow/10 text-marshal-yellow border border-marshal-yellow/30',
  late_brake:
    'bg-marshal-yellow/10 text-marshal-yellow border border-marshal-yellow/30',
  apex_deficit:
    'bg-safety-red/10 text-safety-red border border-safety-red/30',
  entry_too_hot:
    'bg-safety-red/10 text-safety-red border border-safety-red/30',
  exit_under_application:
    'bg-acid-green/10 text-acid-green border border-acid-green/30',
};

const DEFAULT_BADGE_STYLE = 'bg-steel/10 text-steel border border-steel/30';

function getBadgeStyle(cause: string): string {
  return ROOT_CAUSE_STYLES[cause] ?? DEFAULT_BADGE_STYLE;
}

function formatCause(cause: string): string {
  return cause.replace(/_/g, ' ');
}

/* ── Helpers ──────────────────────────────────────────────────────── */

function directionArrow(dir: string): string {
  if (dir === 'L') return '\u21B0';
  if (dir === 'R') return '\u21B1';
  return '';
}

/** Render a single speed-comparison row (Entry / Apex / Exit). */
function SpeedRow({
  label,
  actual,
  proven,
}: {
  label: string;
  actual: number;
  proven: number;
}) {
  const delta = actual - proven;
  const deltaColor =
    delta >= 0 ? 'text-acid-green' : 'text-safety-red';
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="font-telemetry text-steel w-12">{label}</span>
      <span className="font-telemetry text-chalk">
        {actual.toFixed(0)}
      </span>
      <span className="text-steel mx-1">vs</span>
      <span className="font-telemetry text-chalk">
        {proven.toFixed(0)}
      </span>
      <span className={`font-telemetry ${deltaColor} w-16 text-right`}>
        {delta >= 0 ? '+' : ''}
        {delta.toFixed(0)} km/h
      </span>
    </div>
  );
}

/* ── Skeleton loader ──────────────────────────────────────────────── */

function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div className={`bg-concrete rounded-xl border border-steel/10 p-5 ${className}`}>
      <div className="h-4 w-48 bg-steel/10 rounded mb-4 animate-pulse" />
      <div className="h-3 w-full bg-steel/10 rounded mb-3 animate-pulse" />
      <div className="h-3 w-3/4 bg-steel/10 rounded mb-6 animate-pulse" />
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-28 bg-steel/5 rounded-lg animate-pulse" />
        ))}
      </div>
    </div>
  );
}

/* ── Main component ───────────────────────────────────────────────── */

const TIME_LOSS_NOISE_FLOOR = 0.03;

export function CornerCoachingV4({
  sessionId,
  className = '',
}: CornerCoachingV4Props) {
  const [data, setData] = useState<CornerCoachingV4Response | null>(null);
  const [notAvailable, setNotAvailable] = useState(false);
  const fetchVersionRef = useRef(0);

  useEffect(() => {
    const ver = ++fetchVersionRef.current;
    setNotAvailable(false);
    setData(null);

    (async () => {
      try {
        const res = await apiFetch<CornerCoachingV4Response>(
          `/sessions/${encodeURIComponent(sessionId)}/corner-coaching-v4`,
        );
        if (ver !== fetchVersionRef.current) return;
        if (!res.corners || res.corners.length === 0) {
          setNotAvailable(true);
        } else {
          setData(res);
        }
      } catch (err) {
        if (ver !== fetchVersionRef.current) return;
        if (err instanceof ApiError && err.status === 404) {
          setNotAvailable(true);
        } else {
          setNotAvailable(true);
        }
      }
    })();
  }, [sessionId]);

  /* ── 404 / empty fallback ── */
  if (notAvailable) {
    return (
      <div className={`bg-concrete rounded-xl border border-steel/10 p-5 ${className}`}>
        <h3 className="text-sm font-monument text-chalk mb-3">
          Corner Coaching (Aggregate)
        </h3>
        <p className="text-steel text-sm text-center py-6">
          Upload more sessions on this track to unlock aggregate corner coaching.
        </p>
      </div>
    );
  }

  /* ── Loading ── */
  if (!data) {
    return <Skeleton className={className} />;
  }

  const { summary, corners } = data;

  const ranked = [...corners]
    .filter((c) => c.time_loss_s >= TIME_LOSS_NOISE_FLOOR)
    .sort((a, b) => b.time_loss_s - a.time_loss_s);

  return (
    <div className={`space-y-4 ${className}`}>
      {/* ── Summary card ── */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-monument text-chalk">
            Corner Coaching (Aggregate)
          </h3>
          <span className="font-telemetry text-xs bg-steel/10 text-steel border border-steel/30 px-2 py-0.5 rounded-full">
            {summary.aggregate_sessions} sessions
          </span>
        </div>
        <p className="font-telemetry text-2xl text-safety-red mb-2">
          {summary.total_time_loss_s.toFixed(2)}s lost
        </p>
        <p className="font-body text-chalk/80 text-sm leading-relaxed">
          {summary.narrative}
        </p>
      </div>

      {/* ── Per-corner cards ── */}
      {ranked.map((c) => (
        <div
          key={c.corner_id}
          className="bg-concrete rounded-xl border border-steel/10 p-4"
        >
          {/* Header row */}
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="font-monument text-chalk text-base">
                {c.corner_name}
              </span>
              <span className="font-telemetry text-steel text-xs">
                {directionArrow(c.direction)} {c.radius_m.toFixed(0)}m
              </span>
            </div>
            <span className="font-telemetry text-safety-red text-sm">
              +{c.time_loss_s.toFixed(2)}s
            </span>
          </div>

          {/* Root cause badges */}
          {c.root_causes.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {c.root_causes.map((cause) => (
                <span
                  key={cause}
                  className={`inline-block font-telemetry text-xs px-2 py-0.5 rounded-full ${getBadgeStyle(cause)}`}
                >
                  {formatCause(cause)}
                </span>
              ))}
            </div>
          )}

          {/* Speed comparison grid */}
          <div className="bg-asphalt/40 rounded-lg p-3 mb-3 space-y-1.5">
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="font-telemetry text-steel w-12" />
              <span className="font-telemetry text-steel">Actual</span>
              <span className="text-steel mx-1" />
              <span className="font-telemetry text-steel">Proven</span>
              <span className="font-telemetry text-steel w-16 text-right">
                Delta
              </span>
            </div>
            <SpeedRow
              label="Entry"
              actual={c.actual.entry_kph}
              proven={c.proven.entry_kph}
            />
            <SpeedRow
              label="Apex"
              actual={c.actual.apex_kph}
              proven={c.proven.apex_kph}
            />
            <SpeedRow
              label="Exit"
              actual={c.actual.exit_kph}
              proven={c.proven.exit_kph}
            />
          </div>

          {/* Narrative */}
          <p className="font-body text-chalk/80 text-xs leading-relaxed">
            {c.narrative}
          </p>
        </div>
      ))}

      {ranked.length === 0 && (
        <div className="bg-concrete rounded-xl border border-steel/10 p-4 text-center">
          <p className="text-acid-green text-sm font-telemetry">
            All corners within noise floor -- nice driving.
          </p>
        </div>
      )}
    </div>
  );
}
