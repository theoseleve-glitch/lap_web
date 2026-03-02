'use client';

import { useState, useMemo } from 'react';
import { CoachingTable } from './CoachingTable';
import { CornerSelection } from './CornerSelection';
import { CornerReplay } from './CornerReplay';
import { BrakePrecisionChart } from './BrakePrecisionChart';
import { CornerMasteryCard } from './CornerMasteryCard';
import { ThrottleOnsetMap } from './ThrottleOnsetMap';
import { ConsistencyHeatmap } from './ConsistencyHeatmap';

export interface CornerData {
  corner_id: number;
  s_start: number;
  s_end: number;
  s_apex?: number;
  direction?: 'L' | 'R';
  available: boolean;
  entry_speed_actual?: number | null;
  entry_speed_theory?: number | null;
  apex_speed_actual?: number | null;
  apex_speed_theory?: number | null;
  exit_speed_actual?: number | null;
  exit_speed_theory?: number | null;
  time_loss_total_s?: number | null;
  grip_utilisation_pct?: number | null;
  primary_cause?: string | null;
  coaching_hint?: string | null;
}

interface CornersTabProps {
  corners: CornerData[];
  sessionId: string;
}

export function CornersTab({ corners, sessionId }: CornersTabProps) {
  const [selectedCorners, setSelectedCorners] = useState<Set<number>>(
    () => new Set(corners.map((c) => c.corner_id)),
  );

  const filtered = useMemo(
    () => corners.filter((c) => selectedCorners.has(c.corner_id)),
    [corners, selectedCorners],
  );

  if (corners.length === 0) {
    return (
      <div className="flex items-center justify-center py-20">
        <p className="text-steel font-telemetry text-sm">
          No corners detected for this session.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Corner Replay — full width */}
      <CornerReplay sessionId={sessionId} corners={filtered} />

      {/* Coaching Table + Corner Selection */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_240px] gap-4">
        <CoachingTable corners={filtered} />
        <CornerSelection
          corners={corners}
          selected={selectedCorners}
          onChange={setSelectedCorners}
          sessionId={sessionId}
        />
      </div>

      {/* 2x2 chart grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <BrakePrecisionChart sessionId={sessionId} />
        <CornerMasteryCard sessionId={sessionId} />
        <ThrottleOnsetMap sessionId={sessionId} />
        <ConsistencyHeatmap sessionId={sessionId} />
      </div>
    </div>
  );
}
