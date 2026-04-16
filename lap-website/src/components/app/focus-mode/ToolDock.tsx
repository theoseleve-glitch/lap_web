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
  shortcut: number;
  icon: ReactNode;
  group: 'primary' | 'secondary' | 'meta';
}

const TOOLS: Tool[] = [
  /* ── Primary: the three core analysis views ── */
  {
    id: 'speed-trace',
    label: 'Speed Trace',
    shortcut: 1,
    group: 'primary',
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
    group: 'primary',
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M3,14 C3,6 8,3 9,3 C10,3 15,6 15,14" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx="9" cy="9" r="2" />
      </svg>
    ),
  },
  {
    id: 'gg-diagram',
    label: 'G-G Diagram',
    shortcut: 3,
    group: 'primary',
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="9" cy="9" r="6" />
        <line x1="9" y1="3" x2="9" y2="15" />
        <line x1="3" y1="9" x2="15" y2="9" />
        <circle cx="11" cy="7" r="1.5" fill="currentColor" stroke="none" />
      </svg>
    ),
  },

  /* ── Secondary: delta, comparison, and diagnostic ── */
  {
    id: 'lap-overlay',
    label: 'Lap Overlay',
    shortcut: 4,
    group: 'secondary',
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
    group: 'secondary',
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
    label: 'Distribution',
    shortcut: 6,
    group: 'secondary',
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
    group: 'secondary',
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="4" y="3" width="10" height="12" rx="2" />
        <line x1="7" y1="7" x2="11" y2="7" />
        <line x1="7" y1="10" x2="11" y2="10" />
      </svg>
    ),
  },

  /* ── Meta: session-level views ── */
  {
    id: 'corner-analysis',
    label: 'Corner Mastery',
    shortcut: 8,
    group: 'meta',
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
    group: 'meta',
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
    label: 'Fingerprint',
    shortcut: 0,
    group: 'meta',
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <polygon points="9,2 12,6 16,7 13,11 14,16 9,13 4,16 5,11 2,7 6,6" />
      </svg>
    ),
  },
];

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

function GroupDivider() {
  return <div className="w-5 h-px bg-steel/12 my-1.5" />;
}

export function ToolDock({ activeTools, onToggle, onReset, dockVisible }: ToolDockProps) {
  if (!dockVisible) return null;

  const groups = ['primary', 'secondary', 'meta'] as const;
  const groupedTools = groups.map((g) => TOOLS.filter((t) => t.group === g));

  return (
    <nav
      className="flex flex-col items-center py-4 gap-0.5 w-14 bg-concrete/80 border-r border-steel/10 shrink-0"
      aria-label="Analysis tools"
    >
      {groupedTools.map((group, gi) => (
        <div key={gi} className="flex flex-col items-center gap-0.5">
          {gi > 0 && <GroupDivider />}
          {group.map((tool) => {
            const isActive = activeTools.has(tool.id);
            return (
              <button
                type="button"
                key={tool.id}
                onClick={() => onToggle(tool.id)}
                className={`
                  w-10 h-10 flex items-center justify-center rounded-lg transition-all relative group
                  ${isActive
                    ? 'bg-gold/12 text-gold border-l-2 border-gold/60 rounded-l-none'
                    : 'text-steel/70 hover:text-chalk hover:bg-steel/8 border-l-2 border-transparent'
                  }
                `}
                title={`${tool.label} (${tool.shortcut})`}
                aria-label={tool.label}
                aria-pressed={isActive}
              >
                {tool.icon}
                {/* Shortcut: visible on hover only, positioned bottom-right */}
                <span className="absolute bottom-0.5 right-1 text-[7px] font-telemetry text-steel/40 opacity-0 group-hover:opacity-100 transition-opacity">
                  {tool.shortcut}
                </span>
              </button>
            );
          })}
        </div>
      ))}

      {/* Spacer pushes reset to the bottom */}
      <div className="flex-1" />

      <button
        type="button"
        onClick={onReset}
        className="w-10 h-10 flex items-center justify-center rounded-lg text-steel/50 hover:text-chalk hover:bg-steel/8 transition-colors"
        title="Reset layout (R)"
        aria-label="Reset layout"
      >
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M2,8 A6,6 0 1,1 8,14" />
          <polyline points="2,4 2,8 6,8" />
        </svg>
      </button>
    </nav>
  );
}

export function useToolDock(defaultTool: ToolId = 'speed-trace') {
  const defaults = SMART_DEFAULTS[defaultTool] ?? [defaultTool];
  const [activeTools, setActiveTools] = useState<Set<ToolId>>(new Set(defaults));

  const toggle = useCallback((toolId: ToolId) => {
    setActiveTools((prev) => {
      const next = new Set(prev);
      if (next.has(toolId)) {
        next.delete(toolId);
        if (next.size === 0) return prev;
      } else {
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
