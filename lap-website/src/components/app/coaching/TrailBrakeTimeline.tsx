'use client';

import type { TrailBrakeData } from './types';

interface TrailBrakeTimelineProps {
  data?: TrailBrakeData | null;
}

interface Block {
  key: string;
  label: string;
  value: number;
  color: string;
}

export default function TrailBrakeTimeline({ data }: TrailBrakeTimelineProps) {
  if (!data) return null;

  const blocks: Block[] = [
    { key: 'throttle', label: 'Throttle', value: data.throttle_m ?? 0, color: '#10b981' },
    { key: 'straight_brake', label: 'Brake', value: data.straight_brake_m ?? 0, color: '#ef4444' },
    { key: 'trail_brake', label: 'Trail', value: data.trail_brake_m ?? 0, color: '#f97316' },
    { key: 'transition', label: 'Transition', value: data.transition_m ?? 0, color: '#3b82f6' },
  ].filter((b) => b.value > 0);

  if (blocks.length === 0) return null;

  const total = blocks.reduce((sum, b) => sum + b.value, 0);
  if (total === 0) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-steel font-telemetry uppercase tracking-wider">Trail Brake</span>
        {data.overlap_m != null && (
          <span className="text-xs font-telemetry text-chalk/50">
            Overlap: {data.overlap_m.toFixed(1)}m
          </span>
        )}
      </div>

      {/* Timeline bar */}
      <div className="flex h-4 rounded-full overflow-hidden">
        {blocks.map((block) => (
          <div
            key={block.key}
            className="h-full relative group"
            style={{
              width: `${(block.value / total) * 100}%`,
              backgroundColor: block.color,
            }}
            title={`${block.label}: ${block.value.toFixed(1)}m`}
          />
        ))}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-3">
        {blocks.map((block) => (
          <span key={block.key} className="flex items-center gap-1 text-[10px] font-telemetry text-chalk/60">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: block.color }} />
            {block.label} {block.value.toFixed(1)}m
          </span>
        ))}
      </div>
    </div>
  );
}
