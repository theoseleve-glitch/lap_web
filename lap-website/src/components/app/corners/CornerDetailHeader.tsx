'use client';

import type { CornerData } from './useCornerData';

interface CornerDetailHeaderProps {
  corner: CornerData;
  cornerIndex: number;
  totalCorners: number;
  onBack: () => void;
  onPrev: () => void;
  onNext: () => void;
}

const TYPE_LABELS: Record<string, string> = {
  hairpin: 'HAIRPIN',
  fast_sweeper: 'FAST SWEEPER',
  simple: 'SIMPLE',
  kink: 'KINK',
  double_apex: 'DOUBLE APEX',
  compound: 'COMPOUND',
  chicane: 'CHICANE',
  decreasing_radius: 'DECREASING R',
  increasing_radius: 'INCREASING R',
};

export function CornerDetailHeader({
  corner,
  cornerIndex,
  totalCorners,
  onBack,
  onPrev,
  onNext,
}: CornerDetailHeaderProps) {
  const typeLabel = corner.corner_type
    ? (TYPE_LABELS[corner.corner_type] ?? corner.corner_type.toUpperCase())
    : null;
  const dirLabel = corner.direction === 'L' ? 'LEFT' : corner.direction === 'R' ? 'RIGHT' : null;
  const badge = [dirLabel, typeLabel].filter(Boolean).join(' ');

  return (
    <div className="flex items-center justify-between py-3 px-1 border-b border-steel/20 mb-4">
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="text-steel text-sm hover:text-chalk transition-colors font-body"
        >
          ← Back to track
        </button>
        <span className="font-monument text-lg text-chalk tracking-tight">
          CORNER {corner.corner_id}
        </span>
        {badge && (
          <span className="bg-white/10 text-steel text-[11px] font-telemetry px-2 py-0.5 rounded">
            {badge}
          </span>
        )}
      </div>
      <div className="flex gap-2">
        <button
          onClick={onPrev}
          disabled={cornerIndex === 0}
          className="px-3 py-1.5 bg-concrete border border-steel/20 text-steel text-xs font-telemetry rounded disabled:opacity-30 disabled:cursor-not-allowed hover:border-steel/40 transition-colors"
        >
          ← Prev
        </button>
        <button
          onClick={onNext}
          disabled={cornerIndex === totalCorners - 1}
          className="px-3 py-1.5 bg-concrete border border-steel/20 text-steel text-xs font-telemetry rounded disabled:opacity-30 disabled:cursor-not-allowed hover:border-steel/40 transition-colors"
        >
          Next →
        </button>
      </div>
    </div>
  );
}
