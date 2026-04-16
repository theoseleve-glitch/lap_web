'use client';

/**
 * FocusMode — fullscreen telemetry analysis console.
 *
 * Premium motorsport analysis UI. Three zones:
 *   - Top command bar: mode identity, session controls, actions
 *   - Left tool rail: grouped instrument selector
 *   - Main workspace: chart panels in configurable layout
 *
 * Every panel is a framed instrument module with a typed header label.
 * The overall feel should be MoTeC/ATLAS-grade but cleaner.
 */

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
import { ReferenceOverlayProvider, ReferenceFAB } from '@/components/app/reference';

/* ── Panel label map ──────────────────────────────────────── */

const PANEL_LABELS: Record<ToolId, { title: string; sub?: string }> = {
  'speed-trace': { title: 'Speed Trace', sub: 'km/h vs distance' },
  'track-map':   { title: 'Track Map',   sub: 'GPS racing line' },
  'gg-diagram':  { title: 'G-G Diagram', sub: 'grip envelope' },
  'lap-overlay': { title: 'Time Delta',  sub: 'cumulative vs ref' },
  'lap-progress':    { title: 'Lap Progress' },
  'lap-distribution': { title: 'Distribution' },
  'brake-analysis':  { title: 'Brakes' },
  'corner-analysis': { title: 'Corner Mastery' },
  'stint-chart':     { title: 'Stints' },
  fingerprint:       { title: 'Fingerprint' },
};

/* ── Types ──────────────────────────────────────────────── */

interface FocusModeProps {
  sessionId: string;
  isOpen: boolean;
  onClose: () => void;
  gpsLaps: number[];
  bestLap: number | null;
  activeTab?: string;
}

/* ── ToolRenderer (unchanged logic, just rendering) ──────── */

function ToolRenderer({
  toolId,
  sessionId,
  apiBase,
  gpsLaps,
  bestLap,
  distRange,
  onDistRangeChange,
  trackColorMode,
  onTrackColorModeChange,
}: {
  toolId: ToolId;
  sessionId: string;
  apiBase: string;
  gpsLaps: number[];
  bestLap: number | null;
  distRange?: [number, number] | null;
  onDistRangeChange?: (range: [number, number] | null) => void;
  trackColorMode?: 'speed' | 'grip';
  onTrackColorModeChange?: (mode: 'speed' | 'grip') => void;
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
            distRange={distRange}
            onDistRangeChange={onDistRangeChange}
            showPhysicsCeiling
          />
        </ChartErrorBoundary>
      );
    case 'track-map':
      return (
        <ChartErrorBoundary chartName="GpsTrace" minHeight="200px">
          {onTrackColorModeChange && (
            <div className="absolute top-7 right-2 z-10 flex items-center gap-0.5">
              {(['speed', 'grip'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => onTrackColorModeChange(m)}
                  className={`px-1.5 py-0.5 text-[9px] font-telemetry uppercase tracking-wider rounded transition-colors ${
                    trackColorMode === m
                      ? 'text-chalk bg-steel/15'
                      : 'text-steel/50 hover:text-chalk'
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          )}
          <GpsTrace
            sessionId={sessionId}
            apiBase={apiBase}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            controlledLap
            className="w-full h-full"
            distRange={distRange}
            colorMode={trackColorMode}
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
            distRange={distRange}
          />
        </ChartErrorBoundary>
      );
    case 'lap-progress':
      return (
        <ChartErrorBoundary chartName="LapProgress" minHeight="200px">
          <LapProgressChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} controlledLap className="w-full h-full" />
        </ChartErrorBoundary>
      );
    case 'lap-distribution':
      return (
        <ChartErrorBoundary chartName="LapDistribution" minHeight="200px">
          <LapDistributionChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} controlledLap className="w-full h-full" />
        </ChartErrorBoundary>
      );
    case 'brake-analysis':
      return (
        <ChartErrorBoundary chartName="BrakeAnalysis" minHeight="200px">
          <BrakeAnalysisChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} controlledLap className="w-full h-full" />
        </ChartErrorBoundary>
      );
    case 'corner-analysis':
      return (
        <ChartErrorBoundary chartName="CornerAnalysis" minHeight="200px">
          <CornerAnalysisChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} controlledLap className="w-full h-full" />
        </ChartErrorBoundary>
      );
    case 'stint-chart':
      return (
        <ChartErrorBoundary chartName="StintChart" minHeight="200px">
          <StintChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} controlledLap className="w-full h-full" />
        </ChartErrorBoundary>
      );
    case 'fingerprint':
      return (
        <ChartErrorBoundary chartName="Fingerprint" minHeight="200px">
          <FingerprintChart sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} controlledLap className="w-full h-full" />
        </ChartErrorBoundary>
      );
    default:
      return (
        <div className="flex items-center justify-center h-full text-steel/50 font-body text-sm">
          <p className="font-monument text-xs uppercase tracking-wider">{toolId.replace(/-/g, ' ')}</p>
        </div>
      );
  }
}

/* ── Component ──────────────────────────────────────────── */

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
  const [distRange, setDistRange] = useState<[number, number] | null>(null);
  const [trackColorMode, setTrackColorMode] = useState<'speed' | 'grip'>('speed');

  useEffect(() => {
    if (!store.activeTools[activeTab] || store.activeTools[activeTab].length === 0) {
      store.open(activeTab);
    }
  }, [activeTab, store]);

  const storeTools = store.activeTools[activeTab];
  const defaultSplit = store.splitSizes[activeTab] ?? 60;

  const activeToolIds = useMemo(() => {
    if (storeTools && storeTools.length > 0) return storeTools;
    return ['track-map', 'gg-diagram', 'speed-trace'] as ToolId[];
  }, [storeTools]);

  // Keyboard shortcuts
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!isOpen) return;
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      switch (e.key) {
        case 'Escape': onClose(); break;
        case 'r': case 'R':
          if (!e.ctrlKey && !e.metaKey) { reset(); store.resetLayout(activeTab); }
          break;
        case 's': case 'S':
          if (!e.ctrlKey && !e.metaKey) store.toggleDock();
          break;
        case 'z': case 'Z':
          if (!e.ctrlKey && !e.metaKey) setDistRange(null);
          break;
        default: {
          const num = parseInt(e.key, 10);
          if (!isNaN(num) && num >= 0 && num <= 9) toggleByShortcut(num);
        }
      }
    },
    [isOpen, onClose, reset, store, activeTab, toggleByShortcut],
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  useEffect(() => {
    if (!isOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [isOpen]);

  useEffect(() => {
    if (isOpen) store.setActiveTools(activeTab, Array.from(toolState) as ToolId[]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toolState, activeTab, isOpen]);

  if (!isOpen) return null;

  const toolIds = activeToolIds.length > 0 ? activeToolIds : ['speed-trace' as ToolId];

  // ── Panel: a framed instrument module ─────────────────────
  const renderPanel = (toolId: ToolId) => {
    const meta = PANEL_LABELS[toolId] ?? { title: toolId.replace(/-/g, ' ') };
    return (
      <div key={toolId} className="h-full w-full relative overflow-hidden flex flex-col bg-concrete/60 rounded-lg">
        {/* Panel header — thin, typed, unobtrusive */}
        <div className="flex items-baseline justify-between px-3 pt-2 pb-1 shrink-0">
          <div className="flex items-baseline gap-2">
            <span className="text-[10px] font-monument text-steel/70 uppercase tracking-[0.15em]">
              {meta.title}
            </span>
            {meta.sub && (
              <span className="text-[9px] font-telemetry text-steel/40">
                {meta.sub}
              </span>
            )}
          </div>
        </div>
        {/* Chart body — fills remaining space */}
        <div className="flex-1 min-h-0 relative">
          <ToolRenderer
            toolId={toolId}
            sessionId={sessionId}
            apiBase={apiBase}
            gpsLaps={gpsLaps}
            bestLap={activeLap}
            distRange={distRange}
            onDistRangeChange={setDistRange}
            trackColorMode={trackColorMode}
            onTrackColorModeChange={setTrackColorMode}
          />
        </div>
      </div>
    );
  };

  // ── Layout: 1, 2, or 3+ panels ────────────────────────────
  let mainContent: React.ReactNode;
  if (toolIds.length === 1) {
    mainContent = (
      <div className="h-full p-1.5">
        {renderPanel(toolIds[0])}
      </div>
    );
  } else if (toolIds.length === 2) {
    mainContent = (
      <div className="h-full p-1.5">
        <SplitPane
          leftContent={<div className="h-full">{renderPanel(toolIds[0])}</div>}
          rightContent={<div className="h-full">{renderPanel(toolIds[1])}</div>}
          defaultLeftWidth={defaultSplit}
        />
      </div>
    );
  } else {
    const [first, ...stacked] = toolIds;
    mainContent = (
      <div className="h-full flex gap-1.5 p-1.5">
        {/* Primary panel — 42% width */}
        <div className="h-full" style={{ width: '42%' }}>
          {renderPanel(first)}
        </div>
        {/* Stacked secondaries */}
        <div className="flex-1 min-w-0 flex flex-col gap-1.5">
          {stacked.map((id) => (
            <div key={id} className="flex-1 min-h-0">
              {renderPanel(id)}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <ReferenceOverlayProvider sessionId={sessionId} primaryLap={activeLap}>
      <div
        className="fixed inset-0 z-50 bg-asphalt flex flex-col overflow-hidden"
        role="dialog"
        aria-modal="true"
        aria-label="Focus Mode — Fullscreen Analysis"
      >
        {/* ═══ TOP COMMAND BAR ═══════════════════════════════════ */}
        <header className="flex items-center justify-between px-4 py-2 border-b border-steel/10 bg-concrete/50 shrink-0">
          {/* Left zone: mode + keyboard hints */}
          <div className="flex items-center gap-4">
            <h2 className="text-[11px] font-monument text-chalk uppercase tracking-[0.2em]">
              Analysis
            </h2>
            <div className="hidden lg:flex items-center gap-1 text-[8px] font-telemetry text-steel/35">
              {['Esc', 'S', 'R', 'Z', '1-9'].map((k) => (
                <kbd
                  key={k}
                  className="px-1.5 py-0.5 rounded border border-steel/10 bg-asphalt/40 leading-none"
                >
                  {k}
                </kbd>
              ))}
            </div>
          </div>

          {/* Center zone: lap selector (the identity of what we're looking at) */}
          <div className="flex items-center gap-3">
            {gpsLaps.length > 1 && (
              <div className="flex items-center gap-2 bg-asphalt/60 border border-steel/12 rounded-lg px-3 py-1">
                <span className="text-[9px] font-telemetry text-gold uppercase tracking-[0.2em]">
                  Lap
                </span>
                <select
                  value={activeLap ?? ''}
                  onChange={(e) => setFocusLap(Number(e.target.value))}
                  className="bg-transparent text-[12px] font-telemetry text-chalk focus:outline-none cursor-pointer appearance-none pr-3"
                  style={{
                    backgroundImage:
                      "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='8' height='5'%3E%3Cpath d='M0 0l4 5 4-5z' fill='%23C9A84C'/%3E%3C/svg%3E\")",
                    backgroundRepeat: 'no-repeat',
                    backgroundPosition: 'right 0 center',
                  }}
                >
                  {gpsLaps.map((lap) => (
                    <option
                      key={lap}
                      value={lap}
                      style={{ backgroundColor: '#141414', color: '#F0EDE5' }}
                    >
                      {lap}{lap === bestLap ? ' (Best)' : ''}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {/* Right zone: actions */}
          <div className="flex items-center gap-2">
            <ReferenceFAB sessionId={sessionId} />
            {distRange && (
              <button
                type="button"
                onClick={() => setDistRange(null)}
                className="flex items-center gap-1 px-2 py-1 text-[10px] font-telemetry text-acid-green border border-acid-green/25 rounded-lg hover:bg-acid-green/8 transition-colors"
              >
                <span>{Math.round(distRange[0])}–{Math.round(distRange[1])}m</span>
                <span className="text-steel/40 ml-0.5">×</span>
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1 text-[10px] font-telemetry text-steel/60 uppercase tracking-[0.15em] hover:text-chalk border border-steel/10 rounded-lg hover:border-steel/20 transition-colors"
              aria-label="Close focus mode"
            >
              Exit
            </button>
          </div>
        </header>

        {/* ═══ WORKSPACE: rail + panels ═══════════════════════════ */}
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
          <div className="flex-1 min-h-0 overflow-hidden bg-asphalt">
            {mainContent}
          </div>
        </div>
      </div>
    </ReferenceOverlayProvider>
  );
}
