'use client';

import type { TooltipData } from '@/hooks/useInteractiveCanvas';

interface ChartTooltipProps {
  tooltip: (TooltipData & { x: number; y: number }) | null;
}

export function ChartTooltip({ tooltip }: ChartTooltipProps) {
  if (!tooltip) return null;

  // Position tooltip to the right of cursor, flip if near right edge
  const style: React.CSSProperties = {
    left: tooltip.x + 12,
    top: tooltip.y - 10,
    pointerEvents: 'none' as const,
  };

  return (
    <div
      className="absolute z-50 bg-carbon/95 border border-steel/30 rounded-md px-3 py-2 shadow-lg backdrop-blur-sm"
      style={style}
    >
      {tooltip.header && (
        <div className="text-chalk font-telemetry text-xs font-semibold mb-1 border-b border-steel/20 pb-1">
          {tooltip.header}
        </div>
      )}
      {tooltip.lines.map((line, i) => (
        <div key={i} className="flex items-center gap-2 py-0.5">
          {line.color && (
            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: line.color }} />
          )}
          <span className="text-steel font-telemetry text-[10px]">{line.label}:</span>
          <span className="text-chalk font-telemetry text-[10px] font-medium">{line.value}</span>
        </div>
      ))}
    </div>
  );
}
