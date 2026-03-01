'use client';

import { SpeedTraceZoom, GpsTrace, GGExplorer } from '@/components/app/charts';
import { BACKEND_URL } from '@/lib/api-client';

interface FocusModeProps {
  sessionId: string;
  isOpen: boolean;
  onClose: () => void;
  gpsLaps: number[];
  bestLap: number | null;
}

export function FocusMode({ sessionId, isOpen, onClose, gpsLaps, bestLap }: FocusModeProps) {
  if (!isOpen) return null;

  const apiBase = BACKEND_URL;

  return (
    <div
      className="fixed inset-0 z-50 bg-asphalt/98 overflow-auto"
      role="dialog"
      aria-modal="true"
      aria-label="Focus Mode"
    >
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-steel/10">
        <h2 className="text-lg font-monument text-chalk">Focus Mode</h2>
        <button
          onClick={onClose}
          className="px-3 py-1.5 bg-concrete border border-steel/20 rounded text-sm text-chalk font-body hover:bg-steel/10 transition-colors"
          aria-label="Close focus mode"
        >
          Exit Focus
        </button>
      </div>

      {/* Chart grid */}
      <div className="p-4 grid grid-cols-1 lg:grid-cols-2 gap-4" style={{ height: 'calc(100vh - 60px)' }}>
        <div className="bg-concrete rounded-xl border border-steel/10 p-4 overflow-hidden">
          <h3 className="text-xs font-monument text-steel mb-2">GPS Track Map</h3>
          <GpsTrace
            sessionId={sessionId}
            apiBase={apiBase}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            className="w-full h-full"
          />
        </div>
        <div className="bg-concrete rounded-xl border border-steel/10 p-4 overflow-hidden">
          <h3 className="text-xs font-monument text-steel mb-2">Speed Trace</h3>
          <SpeedTraceZoom
            sessionId={sessionId}
            apiBase={apiBase}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            className="w-full h-full"
          />
        </div>
        <div className="lg:col-span-2 bg-concrete rounded-xl border border-steel/10 p-4 overflow-hidden">
          <h3 className="text-xs font-monument text-steel mb-2">G-G Diagram</h3>
          <GGExplorer
            sessionId={sessionId}
            apiBase={apiBase}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            className="w-full h-full"
          />
        </div>
      </div>
    </div>
  );
}
