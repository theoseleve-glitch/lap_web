/**
 * ChartLegend — semantic legend for chart series.
 *
 * Symbol shapes match what the canvas draws:
 *  - line:    solid line (most series)
 *  - dashed:  dashed line (reference, theoretical)
 *  - dot:     filled circle (scatter, single point)
 *  - hollow:  hollow circle (cross-session reference scatter)
 *  - bar:     small block (delta bar)
 *
 * Legend lives at the bottom of the chart card and inherits the chalk/steel
 * type colors — never bright bg.
 */

export interface LegendItem {
  label: string;
  color: string;
  symbol?: 'line' | 'dashed' | 'dot' | 'hollow' | 'bar';
  /** Optional additional muted text (e.g. "44.8s") shown after the label. */
  meta?: string;
}

export interface ChartLegendProps {
  items: readonly LegendItem[];
  align?: 'left' | 'center' | 'right';
}

function Symbol({ symbol = 'line', color }: { symbol?: LegendItem['symbol']; color: string }) {
  if (symbol === 'dot') {
    return (
      <span
        className="inline-block w-2 h-2 rounded-full"
        style={{ backgroundColor: color }}
        aria-hidden
      />
    );
  }
  if (symbol === 'hollow') {
    return (
      <span
        className="inline-block w-2 h-2 rounded-full border"
        style={{ borderColor: color }}
        aria-hidden
      />
    );
  }
  if (symbol === 'bar') {
    return (
      <span
        className="inline-block w-3 h-2"
        style={{ backgroundColor: color }}
        aria-hidden
      />
    );
  }
  if (symbol === 'dashed') {
    return (
      <span
        className="inline-block w-4 h-0 border-t-2 border-dashed"
        style={{ borderColor: color }}
        aria-hidden
      />
    );
  }
  // line (default)
  return (
    <span
      className="inline-block w-4 h-0 border-t-2"
      style={{ borderColor: color }}
      aria-hidden
    />
  );
}

const ALIGN: Record<NonNullable<ChartLegendProps['align']>, string> = {
  left: 'justify-start',
  center: 'justify-center',
  right: 'justify-end',
};

export function ChartLegend({ items, align = 'left' }: ChartLegendProps) {
  if (items.length === 0) return null;
  return (
    <div className={`flex flex-wrap items-center gap-x-4 gap-y-1 mt-3 ${ALIGN[align]}`}>
      {items.map((item) => (
        <div key={item.label} className="flex items-center gap-2">
          <Symbol symbol={item.symbol} color={item.color} />
          <span className="text-[10px] font-telemetry text-chalk">
            {item.label}
          </span>
          {item.meta && (
            <span className="text-[10px] font-telemetry text-steel">
              {item.meta}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
