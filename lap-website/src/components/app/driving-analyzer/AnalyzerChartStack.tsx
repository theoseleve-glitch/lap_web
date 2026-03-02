'use client';

import type { AnalyzerTrace, ChartConfig } from './types';
import { AnalyzerChart } from './AnalyzerChart';

interface AnalyzerChartStackProps {
  trace: AnalyzerTrace;
  overlayTrace: AnalyzerTrace | null;
  charts: ChartConfig[];
  currentDistance: number;
  sectionRange: { min: number; max: number } | null;
  onScrub: (distance: number) => void;
}

export function AnalyzerChartStack({
  trace,
  overlayTrace,
  charts,
  currentDistance,
  sectionRange,
  onScrub,
}: AnalyzerChartStackProps) {
  if (charts.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-steel font-telemetry text-xs">
        No charts visible. Press keyboard shortcuts to toggle.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {charts.map((config) => (
        <div key={config.type} className="flex-1 min-h-0 border-b border-steel/5 last:border-b-0">
          <AnalyzerChart
            trace={trace}
            overlayTrace={overlayTrace}
            config={config}
            currentDistance={currentDistance}
            sectionRange={sectionRange}
            onScrub={onScrub}
          />
        </div>
      ))}
    </div>
  );
}
