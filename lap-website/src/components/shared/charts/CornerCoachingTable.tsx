/**
 * CornerCoachingTable.tsx — Per-corner coaching ranked by time loss.
 *
 * Fetches theoretical corner analysis and displays a table with:
 *   - Corner number, time loss, root cause badge, coaching text
 *   - Brake point delta, apex speed delta, exit throttle delta
 *
 * Gracefully handles 404 when the theoretical engine hasn't run yet.
 */
'use client';

import { useEffect, useState, useRef } from 'react';
import { apiFetch, ApiError } from '@/lib/api-client';

interface CornerCoachingData {
  corner_id: number;
  time_loss_s: number;
  root_cause: string;
  coaching_text: string;
  brake_point_delta_m: number;
  apex_speed_delta_kph: number;
  exit_throttle_delta_pct: number;
}

interface CornerCoachingResponse {
  corners: CornerCoachingData[];
}

interface CornerCoachingTableProps {
  sessionId: string;
  className?: string;
}

const ROOT_CAUSE_STYLES: Record<string, string> = {
  braked_late: 'bg-marshal-yellow/10 text-marshal-yellow border border-marshal-yellow/30',
  braked_early: 'bg-marshal-yellow/10 text-marshal-yellow border border-marshal-yellow/30',
  apex_speed_low: 'bg-safety-red/10 text-safety-red border border-safety-red/30',
  throttle_late: 'bg-acid-green/10 text-acid-green border border-acid-green/30',
  clean: 'bg-steel/10 text-steel border border-steel/30',
};

function getRootCauseStyle(cause: string): string {
  return ROOT_CAUSE_STYLES[cause] ?? ROOT_CAUSE_STYLES['clean']!;
}

function formatRootCause(cause: string): string {
  return cause.replace(/_/g, ' ');
}

export function CornerCoachingTable({
  sessionId,
  className = '',
}: CornerCoachingTableProps) {
  const [corners, setCorners] = useState<CornerCoachingData[] | null>(null);
  const [notAvailable, setNotAvailable] = useState(false);
  const fetchVersionRef = useRef(0);

  useEffect(() => {
    const ver = ++fetchVersionRef.current;
    setNotAvailable(false);
    setCorners(null);
    (async () => {
      try {
        const data = await apiFetch<CornerCoachingResponse>(
          `/sessions/${encodeURIComponent(sessionId)}/theoretical/corners`,
        );
        if (ver !== fetchVersionRef.current) return;
        if (!data.corners || data.corners.length === 0) {
          setNotAvailable(true);
        } else {
          // Sort by time loss descending (biggest losses first)
          const sorted = [...data.corners].sort((a, b) => b.time_loss_s - a.time_loss_s);
          setCorners(sorted);
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

  if (notAvailable) {
    return (
      <div className={`bg-concrete rounded-xl border border-steel/10 p-4 ${className}`}>
        <h3 className="text-sm font-monument text-chalk mb-3">Corner Coaching</h3>
        <p className="text-steel text-sm text-center py-4">
          Theoretical corner coaching not yet available
        </p>
      </div>
    );
  }

  if (!corners) {
    // Still loading — show card shell without spinner per spec
    return (
      <div className={`bg-concrete rounded-xl border border-steel/10 p-4 ${className}`}>
        <h3 className="text-sm font-monument text-chalk mb-3">Corner Coaching</h3>
        <div className="h-40" />
      </div>
    );
  }

  return (
    <div className={`bg-concrete rounded-xl border border-steel/10 p-4 ${className}`}>
      <h3 className="text-sm font-monument text-chalk mb-3">Corner Coaching</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-steel/10">
              <th className="font-monument text-sm text-chalk pb-2 pr-3">#</th>
              <th className="font-monument text-sm text-chalk pb-2 pr-3">Time Loss</th>
              <th className="font-monument text-sm text-chalk pb-2 pr-3">Root Cause</th>
              <th className="font-monument text-sm text-chalk pb-2 pr-3">Coaching</th>
              <th className="font-monument text-sm text-chalk pb-2 pr-3">Brake Delta</th>
              <th className="font-monument text-sm text-chalk pb-2 pr-3">Apex Speed</th>
              <th className="font-monument text-sm text-chalk pb-2">Exit Throttle</th>
            </tr>
          </thead>
          <tbody>
            {corners.map((c) => (
              <tr key={c.corner_id} className="border-b border-steel/5 last:border-b-0">
                <td className="font-telemetry text-sm text-chalk py-2 pr-3">
                  {c.corner_id}
                </td>
                <td className={`font-telemetry text-sm py-2 pr-3 ${c.time_loss_s > 0 ? 'text-safety-red' : 'text-acid-green'}`}>
                  {c.time_loss_s > 0 ? '+' : ''}{c.time_loss_s.toFixed(3)}s
                </td>
                <td className="py-2 pr-3">
                  <span className={`inline-block font-telemetry text-xs px-2 py-0.5 rounded-full ${getRootCauseStyle(c.root_cause)}`}>
                    {formatRootCause(c.root_cause)}
                  </span>
                </td>
                <td className="text-steel font-body text-xs py-2 pr-3 max-w-[240px]">
                  {c.coaching_text}
                </td>
                <td className="font-telemetry text-sm text-chalk py-2 pr-3">
                  {c.brake_point_delta_m > 0 ? '+' : ''}{c.brake_point_delta_m.toFixed(0)}m
                </td>
                <td className="font-telemetry text-sm text-chalk py-2 pr-3">
                  {c.apex_speed_delta_kph > 0 ? '+' : ''}{c.apex_speed_delta_kph.toFixed(0)} km/h
                </td>
                <td className="font-telemetry text-sm text-chalk py-2">
                  {c.exit_throttle_delta_pct > 0 ? '+' : ''}{c.exit_throttle_delta_pct.toFixed(0)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
