'use client';

import { useEffect } from 'react';
import type { CornerData } from './CornersTab';

interface CornerSelectionProps {
  corners: CornerData[];
  selected: Set<number>;
  onChange: (s: Set<number>) => void;
  sessionId: string;
}

const STORAGE_PREFIX = 'corner_sel_';

export function CornerSelection({
  corners,
  selected,
  onChange,
  sessionId,
}: CornerSelectionProps) {
  // Load saved selection on mount
  useEffect(() => {
    try {
      const raw = localStorage.getItem(`${STORAGE_PREFIX}${sessionId}`);
      if (raw) {
        const ids: number[] = JSON.parse(raw);
        if (Array.isArray(ids) && ids.length > 0) {
          onChange(new Set(ids));
        }
      }
    } catch {
      // Ignore parse errors — keep default (all selected)
    }
    // Only run on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // Save selection whenever it changes
  useEffect(() => {
    try {
      localStorage.setItem(
        `${STORAGE_PREFIX}${sessionId}`,
        JSON.stringify(Array.from(selected)),
      );
    } catch {
      // localStorage full or unavailable — ignore
    }
  }, [selected, sessionId]);

  const handleToggle = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    onChange(next);
  };

  const selectAll = () => {
    onChange(new Set(corners.map((c) => c.corner_id)));
  };

  const clearAll = () => {
    onChange(new Set());
  };

  const allSelected = corners.length > 0 && corners.every((c) => selected.has(c.corner_id));

  return (
    <div className="bg-concrete rounded-lg border border-steel/10 p-3">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-steel font-telemetry text-[10px] uppercase tracking-wider">
          Corners
        </h3>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={selectAll}
            disabled={allSelected}
            className="text-[10px] font-telemetry text-steel hover:text-chalk disabled:opacity-30 transition-colors px-1"
          >
            All
          </button>
          <span className="text-steel/20 text-[10px]">|</span>
          <button
            type="button"
            onClick={clearAll}
            disabled={selected.size === 0}
            className="text-[10px] font-telemetry text-steel hover:text-chalk disabled:opacity-30 transition-colors px-1"
          >
            Clear
          </button>
        </div>
      </div>

      <div className="space-y-1 max-h-[320px] overflow-y-auto">
        {corners.map((c) => (
          <label
            key={c.corner_id}
            className="flex items-center gap-2 px-1.5 py-1 rounded hover:bg-asphalt/50 cursor-pointer transition-colors"
          >
            <input
              type="checkbox"
              checked={selected.has(c.corner_id)}
              onChange={() => handleToggle(c.corner_id)}
              className="accent-amber-400 w-3 h-3 cursor-pointer"
            />
            <span className="text-xs text-chalk font-mono">
              C{c.corner_id}
            </span>
            {c.direction && (
              <span
                className={`text-[9px] font-telemetry ${
                  c.direction === 'L'
                    ? 'text-blue-400'
                    : 'text-orange-400'
                }`}
              >
                {c.direction}
              </span>
            )}
          </label>
        ))}
      </div>

      <div className="mt-2 pt-2 border-t border-steel/10">
        <p className="text-[10px] text-steel/40 font-telemetry">
          {selected.size}/{corners.length} selected
        </p>
      </div>
    </div>
  );
}
