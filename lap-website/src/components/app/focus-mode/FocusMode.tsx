'use client';

import { useEffect, useCallback } from 'react';
import { SplitPane } from './SplitPane';
import { ToolDock, useToolDock, type ToolId } from './ToolDock';
import {
  SpeedTrace,
  GGDiagram,
  TrackMap,
  BrakeScatter,
  CornerMastery,
  LapProgress,
} from '@/components/app/charts';

interface FocusModeProps {
  sessionId: string;
  isOpen: boolean;
  onClose: () => void;
}

/** Map tool IDs to their chart components */
function ToolVisualization({ toolId, sessionId }: { toolId: ToolId; sessionId: string }) {
  switch (toolId) {
    case 'speed-trace':
      return (
        <div className="p-4">
          <SpeedTrace sessionId={sessionId} />
        </div>
      );
    case 'gg-diagram':
      return (
        <div className="p-4">
          <GGDiagram sessionId={sessionId} />
        </div>
      );
    case 'track-map':
      return (
        <div className="p-4">
          <TrackMap sessionId={sessionId} />
        </div>
      );
    case 'lap-table':
      return (
        <div className="p-4">
          <LapProgress sessionId={sessionId} />
        </div>
      );
    case 'brake-analysis':
      return (
        <div className="p-4">
          <BrakeScatter sessionId={sessionId} />
        </div>
      );
    case 'corner-analysis':
      return (
        <div className="p-4">
          <CornerMastery sessionId={sessionId} />
        </div>
      );
    default:
      return (
        <div className="flex items-center justify-center h-full">
          <p className="text-steel font-telemetry text-sm">Select a tool</p>
        </div>
      );
  }
}

/** Secondary panel shows a complementary visualization */
function SecondaryVisualization({ primaryTool, sessionId }: { primaryTool: ToolId; sessionId: string }) {
  // Show a complementary chart based on the primary selection
  const secondaryMap: Record<ToolId, ToolId> = {
    'speed-trace': 'track-map',
    'gg-diagram': 'track-map',
    'track-map': 'speed-trace',
    'lap-table': 'speed-trace',
    'brake-analysis': 'speed-trace',
    'corner-analysis': 'gg-diagram',
  };
  const secondaryId = secondaryMap[primaryTool];

  return <ToolVisualization toolId={secondaryId} sessionId={sessionId} />;
}

export function FocusMode({ sessionId, isOpen, onClose }: FocusModeProps) {
  const { activeTool, setActiveTool } = useToolDock('speed-trace');

  // Escape key to close
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    },
    [onClose],
  );

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      // Prevent body scroll
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [isOpen, handleKeyDown]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex"
      role="dialog"
      aria-modal="true"
      aria-label="Focus Mode"
    >
      {/* Dark overlay background */}
      <div className="absolute inset-0 bg-asphalt/95" />

      {/* Close button */}
      <button
        onClick={onClose}
        className="absolute top-4 right-4 z-10 w-8 h-8 flex items-center justify-center rounded-md bg-concrete border border-steel/20 text-steel hover:text-chalk hover:border-steel/40 transition-colors"
        aria-label="Close focus mode"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="2" y1="2" x2="12" y2="12" />
          <line x1="12" y1="2" x2="2" y2="12" />
        </svg>
      </button>

      {/* Focus mode content */}
      <div className="relative flex w-full h-full">
        {/* Tool dock sidebar */}
        <ToolDock activeTool={activeTool} onToolSelect={setActiveTool} />

        {/* Split pane area */}
        <div className="flex-1 min-w-0 p-3">
          <SplitPane
            leftContent={
              <div className="h-full bg-concrete rounded-lg border border-steel/20 overflow-hidden">
                <div className="px-4 py-2 border-b border-steel/10">
                  <span className="text-steel font-telemetry text-[10px] uppercase tracking-wider">
                    {activeTool.replace('-', ' ')}
                  </span>
                </div>
                <ToolVisualization toolId={activeTool} sessionId={sessionId} />
              </div>
            }
            rightContent={
              <div className="h-full bg-concrete rounded-lg border border-steel/20 overflow-hidden ml-3">
                <div className="px-4 py-2 border-b border-steel/10">
                  <span className="text-steel font-telemetry text-[10px] uppercase tracking-wider">
                    Secondary
                  </span>
                </div>
                <SecondaryVisualization primaryTool={activeTool} sessionId={sessionId} />
              </div>
            }
          />
        </div>
      </div>
    </div>
  );
}
