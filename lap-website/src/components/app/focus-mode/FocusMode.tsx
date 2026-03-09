'use client';

import { useEffect, useCallback, useMemo } from 'react';
import { SpeedTraceZoom, GpsTrace, GGExplorer } from '@/components/app/charts';
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

  // Sync store tools into useToolDock if available
  const storeTools = store.activeTools[activeTab];
  const defaultSplit = store.splitSizes[activeTab] ?? 60;

  // Get the ordered array of active tool ids
  const activeToolIds = useMemo(() => {
    // Prefer store state if it has tools for this tab, else fall back to useToolDock set
    if (storeTools && storeTools.length > 0) {
      return storeTools.filter((t) => toolState.has(t));
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

  const renderToolPanel = (toolId: ToolId) => (
    <div key={toolId} className="h-full bg-concrete rounded-lg border border-steel/10 p-3 flex flex-col">
      <h3 className="text-[10px] font-monument text-steel mb-1.5 uppercase tracking-wider shrink-0">
        {toolId.replace(/-/g, ' ')}
      </h3>
      <div className="flex-1 min-h-0">
        <ToolRenderer
          toolId={toolId}
          sessionId={sessionId}
          apiBase={apiBase}
          gpsLaps={gpsLaps}
          bestLap={bestLap}
        />
      </div>
    </div>
  );

  // Build main content area based on number of active tools
  let mainContent: React.ReactNode;
  if (toolIds.length === 1) {
    mainContent = (
      <div className="h-full p-2">
        {renderToolPanel(toolIds[0])}
      </div>
    );
  } else if (toolIds.length === 2) {
    mainContent = (
      <SplitPane
        leftContent={
          <div className="h-full p-2 pr-1">
            {renderToolPanel(toolIds[0])}
          </div>
        }
        rightContent={
          <div className="h-full p-2 pl-1">
            {renderToolPanel(toolIds[1])}
          </div>
        }
        defaultLeftWidth={defaultSplit}
      />
    );
  } else {
    // 3+ tools: top split pane + bottom grid
    const [first, second, ...rest] = toolIds;
    mainContent = (
      <div className="h-full flex flex-col">
        <div className="flex-1 min-h-0">
          <SplitPane
            leftContent={
              <div className="h-full p-2 pr-1">
                {renderToolPanel(first)}
              </div>
            }
            rightContent={
              <div className="h-full p-2 pl-1">
                {renderToolPanel(second)}
              </div>
            }
            defaultLeftWidth={defaultSplit}
          />
        </div>
        <div
          className="shrink-0 grid gap-2 p-2 pt-0"
          style={{
            height: '35%',
            gridTemplateColumns: `repeat(${rest.length}, 1fr)`,
          }}
        >
          {rest.map((id) => renderToolPanel(id))}
        </div>
      </div>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-asphalt/98 flex flex-col"
      role="dialog"
      aria-modal="true"
      aria-label="Focus Mode"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-steel/10 shrink-0">
        <div className="flex items-center gap-4">
          <h2 className="text-lg font-monument text-chalk">Focus Mode</h2>
          <div className="hidden sm:flex items-center gap-2 text-[10px] font-telemetry text-steel/60">
            <kbd className="px-1.5 py-0.5 rounded bg-asphalt border border-steel/20">Esc</kbd>
            <span>close</span>
            <kbd className="px-1.5 py-0.5 rounded bg-asphalt border border-steel/20 ml-2">S</kbd>
            <span>sidebar</span>
            <kbd className="px-1.5 py-0.5 rounded bg-asphalt border border-steel/20 ml-2">R</kbd>
            <span>reset</span>
            <kbd className="px-1.5 py-0.5 rounded bg-asphalt border border-steel/20 ml-2">1-9</kbd>
            <span>tools</span>
          </div>
        </div>
        <button
          onClick={onClose}
          className="px-3 py-1.5 bg-concrete border border-steel/20 rounded text-sm text-chalk font-body hover:bg-steel/10 transition-colors"
          aria-label="Close focus mode"
        >
          Exit Focus
        </button>
      </div>

      {/* Corner nav bar */}
      <CornerNavBar sessionId={sessionId} />

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
