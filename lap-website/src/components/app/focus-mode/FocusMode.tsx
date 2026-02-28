'use client';

import { useEffect, useCallback, useState } from 'react';
import { ToolDock, useToolDock, type ToolId } from './ToolDock';
import {
  SpeedTrace,
  GGDiagram,
  TrackMap,
  BrakeScatter,
  CornerMastery,
  LapProgress,
  LapOverlay,
  LapDistribution,
  StintChart,
  Fingerprint,
} from '@/components/app/charts';

interface FocusModeProps {
  sessionId: string;
  isOpen: boolean;
  onClose: () => void;
}

/** Map tool IDs to chart components — charts with height prop fill container */
function ToolPanel({ toolId, sessionId }: { toolId: ToolId; sessionId: string }) {
  // Charts that accept `height` prop use h-full; others render at natural size
  const chartMap: Record<ToolId, React.ReactNode> = {
    'speed-trace': <SpeedTrace sessionId={sessionId} height="h-full" />,
    'track-map': <TrackMap sessionId={sessionId} height="h-full" />,
    'gg-diagram': <GGDiagram sessionId={sessionId} height="h-full" />,
    'lap-overlay': <LapOverlay sessionId={sessionId} height="h-full" />,
    'lap-progress': <LapProgress sessionId={sessionId} height="h-full" />,
    'lap-distribution': <LapDistribution sessionId={sessionId} height="h-full" />,
    'brake-analysis': <BrakeScatter sessionId={sessionId} />,
    'corner-analysis': <CornerMastery sessionId={sessionId} />,
    'stint-chart': <StintChart sessionId={sessionId} />,
    fingerprint: <Fingerprint sessionId={sessionId} />,
  };

  return (
    <div className="h-full bg-concrete rounded-lg border border-steel/20 overflow-hidden flex flex-col">
      <div className="px-3 py-1.5 border-b border-steel/10 flex items-center justify-between shrink-0">
        <span className="text-steel font-telemetry text-[10px] uppercase tracking-wider">
          {toolId.replace(/-/g, ' ')}
        </span>
      </div>
      <div className="flex-1 min-h-0 p-1">
        {chartMap[toolId]}
      </div>
    </div>
  );
}

/**
 * Smart grid layout based on active panel count:
 * - 1 panel: full
 * - 2 panels: side by side
 * - 3 panels: 2 top + 1 bottom
 * - 4 panels: 2x2
 * - 5+ panels: 3 top + rest bottom
 */
function PanelGrid({ tools, sessionId }: { tools: ToolId[]; sessionId: string }) {
  const n = tools.length;
  if (n === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-steel font-telemetry text-sm">Click tools in the dock to add panels</p>
      </div>
    );
  }

  if (n === 1) {
    return (
      <div className="h-full p-1">
        <ToolPanel toolId={tools[0]} sessionId={sessionId} />
      </div>
    );
  }

  if (n === 2) {
    return (
      <div className="h-full grid grid-cols-2 gap-2 p-1">
        {tools.map((t) => (
          <ToolPanel key={t} toolId={t} sessionId={sessionId} />
        ))}
      </div>
    );
  }

  if (n === 3) {
    return (
      <div className="h-full grid grid-rows-2 gap-2 p-1">
        <div className="grid grid-cols-2 gap-2 min-h-0">
          <ToolPanel toolId={tools[0]} sessionId={sessionId} />
          <ToolPanel toolId={tools[1]} sessionId={sessionId} />
        </div>
        <div className="min-h-0">
          <ToolPanel toolId={tools[2]} sessionId={sessionId} />
        </div>
      </div>
    );
  }

  if (n === 4) {
    return (
      <div className="h-full grid grid-cols-2 grid-rows-2 gap-2 p-1">
        {tools.map((t) => (
          <ToolPanel key={t} toolId={t} sessionId={sessionId} />
        ))}
      </div>
    );
  }

  // 5+ panels: 3 columns top, rest bottom
  const topRow = tools.slice(0, 3);
  const bottomRow = tools.slice(3);
  return (
    <div className="h-full grid grid-rows-2 gap-2 p-1">
      <div className="grid grid-cols-3 gap-2 min-h-0">
        {topRow.map((t) => (
          <ToolPanel key={t} toolId={t} sessionId={sessionId} />
        ))}
      </div>
      <div
        className="grid gap-2 min-h-0"
        style={{ gridTemplateColumns: `repeat(${bottomRow.length}, 1fr)` }}
      >
        {bottomRow.map((t) => (
          <ToolPanel key={t} toolId={t} sessionId={sessionId} />
        ))}
      </div>
    </div>
  );
}

export function FocusMode({ sessionId, isOpen, onClose }: FocusModeProps) {
  const { activeTools, toggle, reset, toggleByShortcut } = useToolDock('speed-trace');
  const [dockVisible, setDockVisible] = useState(true);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      // Don't capture if user is typing in an input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

      switch (e.key) {
        case 'Escape':
          onClose();
          break;
        case 'r':
        case 'R':
          reset();
          break;
        case 's':
        case 'S':
          setDockVisible((v) => !v);
          break;
        case '1': case '2': case '3': case '4': case '5':
        case '6': case '7': case '8': case '9': case '0':
          toggleByShortcut(parseInt(e.key));
          break;
      }
    },
    [onClose, reset, toggleByShortcut],
  );

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [isOpen, handleKeyDown]);

  if (!isOpen) return null;

  const activeToolList = Array.from(activeTools);

  return (
    <div
      className="fixed inset-0 z-50 flex"
      role="dialog"
      aria-modal="true"
      aria-label="Focus Mode"
    >
      {/* Dark overlay background */}
      <div className="absolute inset-0 bg-asphalt/95" />

      {/* Top bar with shortcuts hint + close */}
      <div className="absolute top-0 left-0 right-0 z-10 flex items-center justify-between px-4 py-2 bg-carbon/80 border-b border-steel/10">
        <div className="flex items-center gap-4">
          <span className="text-acid-green font-monument text-sm tracking-wider">FOCUS MODE</span>
          <div className="hidden md:flex items-center gap-3 text-steel/50 text-[10px] font-telemetry">
            <span>ESC close</span>
            <span className="text-steel/20">|</span>
            <span>1-9 toggle tools</span>
            <span className="text-steel/20">|</span>
            <span>S toggle dock</span>
            <span className="text-steel/20">|</span>
            <span>R reset</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-steel/40 text-[10px] font-telemetry">
            {activeToolList.length} panel{activeToolList.length !== 1 ? 's' : ''}
          </span>
          <button
            onClick={onClose}
            className="w-7 h-7 flex items-center justify-center rounded-md bg-concrete border border-steel/20 text-steel hover:text-chalk hover:border-steel/40 transition-colors"
            aria-label="Close focus mode"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="2" y1="2" x2="10" y2="10" />
              <line x1="10" y1="2" x2="2" y2="10" />
            </svg>
          </button>
        </div>
      </div>

      {/* Main content area */}
      <div className="relative flex w-full h-full pt-10">
        {/* Tool dock sidebar */}
        <ToolDock
          activeTools={activeTools}
          onToggle={toggle}
          onReset={reset}
          dockVisible={dockVisible}
        />

        {/* Panel grid */}
        <div className="flex-1 min-w-0">
          <PanelGrid tools={activeToolList} sessionId={sessionId} />
        </div>
      </div>
    </div>
  );
}
