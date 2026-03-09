'use client';

import { useChartHoverStore } from '@/lib/chart-hover-store';

export function ChartSyncToggle() {
  const syncEnabled = useChartHoverStore((s) => s.syncEnabled);
  const toggleSync = useChartHoverStore((s) => s.toggleSync);

  return (
    <button
      type="button"
      onClick={toggleSync}
      className={`inline-flex items-center gap-1.5 px-2 py-1 rounded border text-xs font-telemetry transition-colors ${
        syncEnabled
          ? 'border-acid-green/40 text-acid-green bg-acid-green/5'
          : 'border-steel/20 text-steel hover:border-steel/40'
      }`}
      title={syncEnabled ? 'Chart crosshair sync is on — click to disable' : 'Chart crosshair sync is off — click to enable'}
    >
      <span aria-hidden="true">{syncEnabled ? '⟺' : '⟺'}</span>
      <span className="hidden sm:inline">Sync {syncEnabled ? 'On' : 'Off'}</span>
    </button>
  );
}
