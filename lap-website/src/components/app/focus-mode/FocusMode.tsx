'use client';

import { useEffect, useCallback, useMemo, useState } from 'react';
import { SpeedTraceZoom, GpsTrace, GGExplorer } from '@/components/app/charts';
import {
  DeltaTimeChart,
  BrakeAnalysisChart,
  LapProgressChart,
  LapDistributionChart,
  StintChart,
  FingerprintChart,
  CornerAnalysisChart,
} from '@/components/shared/charts';
import { ChartErrorBoundary } from '@/components/shared/ChartErrorBoundary';
import { BACKEND_URL } from '@/lib/api-client';
import { SplitPane } from './SplitPane';
import { ToolDock, useToolDock, type ToolId } from './ToolDock';
import { CornerNavBar } from './CornerNavBar';
import { useFocusModeStore } from '@/stores/focus-mode-store';

interface FocusModeProps {
  sessionId: string;
  isOpen: boolean;
  onClose: () => void;
  gpsLaps: number[];
  bestLap: number | null;
  activeTab?: string;
}

/** Render a chart tool by its ToolId */
function ToolRenderer({
  toolId,
  sessionId,
  apiBase,
  gpsLaps,
  bestLap,
}: {
  toolId: ToolId;
  sessionId: string;
  apiBase: string;
  gpsLaps: number[];
  bestLap: number | null;
}) {
  switch (toolId) {
    case 'speed-trace':
      return (
        <ChartErrorBoundary chartName="SpeedTrace" minHeight="200px">
          <SpeedTraceZoom
            sessionId={sessionId}
            apiBase={apiBase}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            controlledLap
            className="w-full h-full"
          />
        </ChartErrorBoundary>
      );
    case 'track-map':
      return (
        <ChartErrorBoundary chartName="GpsTrace" minHeight="200px">
          <GpsTrace
            sessionId={sessionId}
            apiBase={apiBase}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            controlledLap
            className="w-full h-full"
          />
        </ChartErrorBoundary>
      );
    case 'gg-diagram':
      return (
        <ChartErrorBoundary chartName="GGExplorer" minHeight="200px">
          <GGExplorer
            sessionId={sessionId}
            apiBase={apiBase}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            controlledLap
            className="w-full h-full"
          />
        </ChartErrorBoundary>
      );
    case 'lap-overlay':
      return (
        <ChartErrorBoundary chartName="DeltaTime" minHeight="200px">
          <DeltaTimeChart
            sessionId={sessionId}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            controlledLap
            className="w-full h-full"
          />
        </ChartErrorBoundary>
      );
    case 'lap-progress':
      return (
        <ChartErrorBoundary chartName="LapProgress" minHeight="200px">
          <LapProgressChart
            sessionId={sessionId}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            controlledLap
            className="w-full h-full"
          />
        </ChartErrorBoundary>
      );
    case 'lap-distribution':
      return (
        <ChartErrorBoundary chartName="LapDistribution" minHeight="200px">
          <LapDistributionChart
            sessionId={sessionId}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            controlledLap
            className="w-full h-full"
          />
        </ChartErrorBoundary>
      );
    case 'brake-analysis':
      return (
        <ChartErrorBoundary chartName="BrakeAnalysis" minHeight="200px">
          <BrakeAnalysisChart
            sessionId={sessionId}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            controlledLap
            className="w-full h-full"
          />
        </ChartErrorBoundary>
      );
    case 'corner-analysis':
      return (
        <ChartErrorBoundary chartName="CornerAnalysis" minHeight="200px">
          <CornerAnalysisChart
            sessionId={sessionId}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            controlledLap
            className="w-full h-full"
          />
        </ChartErrorBoundary>
      );
    case 'stint-chart':
      return (
        <ChartErrorBoundary chartName="StintChart" minHeight="200px">
          <StintChart
            sessionId={sessionId}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            controlledLap
            className="w-full h-full"
          />
        </ChartErrorBoundary>
      );
    case 'fingerprint':
      return (
        <ChartErrorBoundary chartName="Fingerprint" minHeight="200px">
          <FingerprintChart
            sessionId={sessionId}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            controlledLap
            className="w-full h-full"
          />
        </ChartErrorBoundary>
      );
    default:
      return (
        <div className="flex items-center justify-center h-full text-steel/60 font-body text-sm">
          <div className="text-center">
            <p className="text-lg font-monument text-steel/50 mb-1 capitalize">
              {toolId.replace(/-/g, ' ')}
            </p>
            <p>Coming soon</p>
          </div>
        </div>
      );
  }
}

export function FocusMode({
  sessionId,
  isOpen,
  onClose,
  gpsLaps,
  bestLap,
  activeTab = 'overview',
}: FocusModeProps) {
  const store = useFocusModeStore();
  const { activeTools: toolState, toggle, reset, toggleByShortcut } = useToolDock('speed-trace');

  const apiBase = BACKEND_URL;
  const [focusLap, setFocusLap] = useState<number | null>(null);
  const activeLap = focusLap ?? bestLap ?? gpsLaps[0] ?? null;

  // Sync store tools into useToolDock if available
  const storeTools = store.activeTools[activeTab];
  const defaultSplit = store.splitSizes[activeTab] ?? 60;

  // Get the ordered array of active tool ids
  const activeToolIds = useMemo(() => {
    // Prefer store state (persisted defaults) over useToolDock set
    if (storeTools && storeTools.length > 0) {
      return storeTools;
    }
    return Array.from(toolState);
  }, [storeTools, toolState]);

  // Keyboard shortcuts
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!isOpen) return;
      // Don't capture when typing in inputs
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement
      ) {
        return;
      }

      switch (e.key) {
        case 'Escape':
          onClose();
          break;
        case 'r':
        case 'R':
          if (!e.ctrlKey && !e.metaKey) {
            reset();
            store.resetLayout(activeTab);
          }
          break;
        case 's':
        case 'S':
          if (!e.ctrlKey && !e.metaKey) {
            store.toggleDock();
          }
          break;
        default: {
          // Number keys 0-9 toggle tools
          const num = parseInt(e.key, 10);
          if (!isNaN(num) && num >= 0 && num <= 9) {
            toggleByShortcut(num);
          }
          break;
        }
      }
    },
    [isOpen, onClose, reset, store, activeTab, toggleByShortcut]
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  // Lock body scroll when focus mode is open
  useEffect(() => {
    if (!isOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [isOpen]);

  // Persist active tools to store when they change
  useEffect(() => {
    if (isOpen) {
      store.setActiveTools(activeTab, Array.from(toolState) as ToolId[]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toolState, activeTab, isOpen]);

  if (!isOpen) return null;

  // Build the content panels from active tools
  const toolIds = activeToolIds.length > 0 ? activeToolIds : ['speed-trace' as ToolId];

  // Minimal panel: no border/padding chrome — chart fills edge-to-edge
  const renderToolPanel = (toolId: ToolId) => (
    <div key={toolId} className="h-full w-full relative">
      <span className="absolute top-1 left-2 z-10 text-[9px] font-monument text-steel/40 uppercase tracking-wider pointer-events-none">
        {toolId.replace(/-/g, ' ')}
      </span>
      <ToolRenderer
        toolId={toolId}
        sessionId={sessionId}
        apiBase={apiBase}
        gpsLaps={gpsLaps}
        bestLap={activeLap}
      />
    </div>
  );

  // Build main content area based on number of active tools
  let mainContent: React.ReactNode;
  if (toolIds.length === 1) {
    mainContent = (
      <div className="h-full">
        {renderToolPanel(toolIds[0])}
      </div>
    );
  } else if (toolIds.length === 2) {
    mainContent = (
      <SplitPane
        leftContent={
          <div className="h-full">
            {renderToolPanel(toolIds[0])}
          </div>
        }
        rightContent={
          <div className="h-full">
            {renderToolPanel(toolIds[1])}
          </div>
        }
        defaultLeftWidth={defaultSplit}
      />
    );
  } else {
    // 3+ tools: VRS-style — left column (first tool full height) + right column (stacked)
    const [first, ...stacked] = toolIds;
    mainContent = (
      <div className="h-full flex">
        {/* Left: first tool takes ~40% width, full height */}
        <div className="h-full" style={{ width: '38%' }}>
          {renderToolPanel(first)}
        </div>
        <div className="w-px bg-steel/15 shrink-0" />
        {/* Right: remaining tools stacked vertically */}
        <div className="flex-1 min-w-0 flex flex-col">
          {stacked.map((id, i) => (
            <div key={id} className="flex-1 min-h-0">
              {i > 0 && <div className="h-px bg-steel/15" />}
              {renderToolPanel(id)}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-asphalt flex flex-col overflow-hidden"
      role="dialog"
      aria-modal="true"
      aria-label="Focus Mode"
    >
      {/* Compact header — minimal chrome, max chart space */}
      <div className="flex items-center justify-between px-3 py-1 border-b border-steel/15 shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="text-xs font-monument text-steel/60 uppercase tracking-wider">Focus</h2>
          <div className="hidden sm:flex items-center gap-1.5 text-[9px] font-telemetry text-steel/40">
            <kbd className="px-1 py-0.5 rounded bg-asphalt/60 border border-steel/15">Esc</kbd>
            <kbd className="px-1 py-0.5 rounded bg-asphalt/60 border border-steel/15 ml-1">S</kbd>
            <kbd className="px-1 py-0.5 rounded bg-asphalt/60 border border-steel/15 ml-1">R</kbd>
            <kbd className="px-1 py-0.5 rounded bg-asphalt/60 border border-steel/15 ml-1">1-9</kbd>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {gpsLaps.length > 1 && (
            <div className="flex items-center gap-1.5">
              <span className="text-[9px] font-telemetry text-steel/40 uppercase">Lap</span>
              <div className="flex gap-0.5">
                {gpsLaps.map((lap) => (
                  <button
                    key={lap}
                    type="button"
                    onClick={() => setFocusLap(lap)}
                    className={`px-1.5 py-0.5 text-[10px] font-telemetry rounded transition-colors ${
                      lap === activeLap
                        ? 'bg-acid-green/20 text-acid-green border border-acid-green/40'
                        : 'text-steel/50 hover:text-chalk'
                    }`}
                  >
                    {lap}
                    {lap === bestLap && <span className="ml-0.5 text-[8px] text-acid-green">B</span>}
                  </button>
                ))}
              </div>
            </div>
          )}
          <button
            type="button"
            onClick={onClose}
            className="px-2 py-0.5 text-[10px] text-steel/60 font-telemetry uppercase tracking-wider hover:text-chalk transition-colors"
            aria-label="Close focus mode"
          >
            Exit
          </button>
        </div>
      </div>

      {/* Main workspace: ToolDock + content */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        <ToolDock
          activeTools={toolState}
          onToggle={toggle}
          onReset={() => {
            reset();
            store.resetLayout(activeTab);
          }}
          dockVisible={store.dockVisible}
        />
        <div className="flex-1 min-h-0 overflow-hidden">
          {mainContent}
        </div>
      </div>
    </div>
  );
}
