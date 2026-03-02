'use client';

import { useState, useCallback, type ReactNode } from 'react';

export type ToolId =
  | 'speed-trace'
  | 'gg-diagram'
  | 'track-map'
  | 'lap-progress'
  | 'lap-overlay'
  | 'lap-distribution'
  | 'brake-analysis'
  | 'corner-analysis'
  | 'stint-chart'
  | 'fingerprint';

interface Tool {
  id: ToolId;
  label: string;
  shortcut: number; // 1-9 key
  icon: ReactNode;
}

const TOOLS: Tool[] = [
  {
    id: 'speed-trace',
    label: 'Speed Trace',
    shortcut: 1,
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <polyline points="2,14 5,8 8,11 11,4 14,9 16,6" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    id: 'track-map',
    label: 'Track Map',
    shortcut: 2,
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M3,14 C3,6 8,3 9,3 C10,3 15,6 15,14" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx="9" cy="9" r="2" />
      </svg>
    ),
  },
  {
    id: 'gg-diagram',
    label: 'GG Diagram',
    shortcut: 3,
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="9" cy="9" r="6" />
        <line x1="9" y1="3" x2="9" y2="15" />
        <line x1="3" y1="9" x2="15" y2="9" />
        <circle cx="11" cy="7" r="1.5" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
  {
    id: 'lap-overlay',
    label: 'Lap Overlay',
    shortcut: 4,
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <polyline points="2,12 6,6 10,10 14,4 16,6" strokeLinejoin="round" strokeLinecap="round" />
        <polyline points="2,14 6,8 10,12 14,6 16,8" strokeLinejoin="round" strokeLinecap="round" opacity="0.4" />
      </svg>
    ),
  },
  {
    id: 'lap-progress',
    label: 'Lap Progress',
    shortcut: 5,
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="3" y="10" width="3" height="6" rx="0.5" fill="currentColor" opacity="0.3" />
        <rect x="7.5" y="6" width="3" height="10" rx="0.5" fill="currentColor" opacity="0.5" />
        <rect x="12" y="3" width="3" height="13" rx="0.5" fill="currentColor" opacity="0.8" />
      </svg>
    ),
  },
  {
    id: 'lap-distribution',
    label: 'Lap Distribution',
    shortcut: 6,
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M2,15 Q5,15 7,10 Q9,3 11,10 Q13,15 16,15" />
      </svg>
    ),
  },
  {
    id: 'brake-analysis',
    label: 'Brake Analysis',
    shortcut: 7,
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="4" y="3" width="10" height="12" rx="2" />
        <line x1="7" y1="7" x2="11" y2="7" />
        <line x1="7" y1="10" x2="11" y2="10" />
      </svg>
    ),
  },
  {
    id: 'corner-analysis',
    label: 'Corner Mastery',
    shortcut: 8,
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M3,15 L3,9 Q3,3 9,3 L15,3" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx="6" cy="6" r="1.5" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
  {
    id: 'stint-chart',
    label: 'Stint Analysis',
    shortcut: 9,
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="2" y="4" width="4" height="10" rx="1" />
        <rect x="7" y="6" width="4" height="8" rx="1" />
        <rect x="12" y="3" width="4" height="11" rx="1" />
      </svg>
    ),
  },
  {
    id: 'fingerprint',
    label: 'Driver Fingerprint',
    shortcut: 0,
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <polygon points="9,2 12,6 16,7 13,11 14,16 9,13 4,16 5,11 2,7 6,6" />
      </svg>
    ),
  },
];

/** Smart defaults: when a tool is first activated, also show these companions */
const SMART_DEFAULTS: Partial<Record<ToolId, ToolId[]>> = {
  'speed-trace': ['speed-trace', 'track-map'],
  'track-map': ['track-map', 'speed-trace'],
  'gg-diagram': ['gg-diagram', 'track-map'],
  'lap-overlay': ['lap-overlay', 'speed-trace'],
  'lap-progress': ['lap-progress', 'lap-distribution'],
  'lap-distribution': ['lap-distribution', 'lap-progress'],
  'brake-analysis': ['brake-analysis', 'speed-trace'],
  'corner-analysis': ['corner-analysis', 'gg-diagram'],
  'stint-chart': ['stint-chart', 'lap-progress'],
  fingerprint: ['fingerprint', 'gg-diagram'],
};

interface ToolDockProps {
  activeTools: Set<ToolId>;
  onToggle: (toolId: ToolId) => void;
  onReset: () => void;
  dockVisible: boolean;
}

export function ToolDock({ activeTools, onToggle, onReset, dockVisible }: ToolDockProps) {
  if (!dockVisible) return null;

  return (
    <div className="flex flex-col items-center py-3 gap-1 w-12 bg-concrete border-r border-steel/20 shrink-0">
      {TOOLS.map((tool) => {
        const isActive = activeTools.has(tool.id);
        return (
          <button
            key={tool.id}
            onClick={() => onToggle(tool.id)}
            className={`w-9 h-9 flex items-center justify-center rounded-md transition-colors relative ${
              isActive
                ? 'bg-acid-green/20 text-acid-green'
                : 'text-steel hover:text-chalk hover:bg-asphalt/50'
            }`}
            title={`${tool.label} (${tool.shortcut})`}
            aria-label={tool.label}
            aria-pressed={isActive}
          >
            {tool.icon}
            <span className="absolute -top-0.5 -right-0.5 text-[8px] font-telemetry text-steel/60">
              {tool.shortcut}
            </span>
          </button>
        );
      })}

      {/* Separator */}
      <div className="w-6 border-t border-steel/20 my-1" />

      {/* Reset layout */}
      <button
        onClick={onReset}
        className="w-9 h-9 flex items-center justify-center rounded-md text-steel hover:text-chalk hover:bg-asphalt/50 transition-colors"
        title="Reset layout (R)"
        aria-label="Reset layout"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M2,8 A6,6 0 1,1 8,14" />
          <polyline points="2,4 2,8 6,8" />
        </svg>
      </button>
    </div>
  );
}

/** Hook to manage multi-tool state with smart defaults */
export function useToolDock(defaultTool: ToolId = 'speed-trace') {
  const defaults = SMART_DEFAULTS[defaultTool] ?? [defaultTool];
  const [activeTools, setActiveTools] = useState<Set<ToolId>>(new Set(defaults));

  const toggle = useCallback((toolId: ToolId) => {
    setActiveTools((prev) => {
      const next = new Set(prev);
      if (next.has(toolId)) {
        next.delete(toolId);
        // Don't allow empty — if last tool removed, keep it
        if (next.size === 0) return prev;
      } else {
        // If no tools are active, use smart defaults
        if (prev.size === 0) {
          return new Set(SMART_DEFAULTS[toolId] ?? [toolId]);
        }
        next.add(toolId);
      }
      return next;
    });
  }, []);

  const reset = useCallback(() => {
    setActiveTools(new Set(defaults));
  }, [defaults]);

  const toggleByShortcut = useCallback((num: number) => {
    const tool = TOOLS.find((t) => t.shortcut === num);
    if (tool) toggle(tool.id);
  }, [toggle]);

  return { activeTools, toggle, reset, toggleByShortcut };
}

export { TOOLS };
