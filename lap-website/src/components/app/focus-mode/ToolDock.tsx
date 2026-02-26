'use client';

import { useState, type ReactNode } from 'react';

export type ToolId =
  | 'speed-trace'
  | 'gg-diagram'
  | 'track-map'
  | 'lap-table'
  | 'brake-analysis'
  | 'corner-analysis';

interface Tool {
  id: ToolId;
  label: string;
  icon: ReactNode;
}

const tools: Tool[] = [
  {
    id: 'speed-trace',
    label: 'Speed Trace',
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <polyline points="2,14 5,8 8,11 11,4 14,9 16,6" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    id: 'gg-diagram',
    label: 'GG Diagram',
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
    id: 'track-map',
    label: 'Track Map',
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M3,14 C3,6 8,3 9,3 C10,3 15,6 15,14" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx="9" cy="9" r="2" />
      </svg>
    ),
  },
  {
    id: 'lap-table',
    label: 'Lap Table',
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="2" y="2" width="14" height="14" rx="1" />
        <line x1="2" y1="7" x2="16" y2="7" />
        <line x1="2" y1="12" x2="16" y2="12" />
        <line x1="7" y1="2" x2="7" y2="16" />
      </svg>
    ),
  },
  {
    id: 'brake-analysis',
    label: 'Brake Analysis',
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="4" y="3" width="10" height="12" rx="2" />
        <line x1="7" y1="7" x2="11" y2="7" />
        <line x1="7" y1="10" x2="11" y2="10" />
        <line x1="9" y1="13" x2="9" y2="15" />
      </svg>
    ),
  },
  {
    id: 'corner-analysis',
    label: 'Corner Analysis',
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M3,15 L3,9 Q3,3 9,3 L15,3" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx="6" cy="6" r="1.5" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
];

interface ToolDockProps {
  onToolSelect: (toolId: ToolId) => void;
  activeTool: ToolId;
}

export function ToolDock({ onToolSelect, activeTool }: ToolDockProps) {
  return (
    <div className="flex flex-col items-center py-3 gap-1 w-12 bg-concrete border-r border-steel/20 shrink-0">
      {tools.map((tool) => {
        const isActive = activeTool === tool.id;
        return (
          <button
            key={tool.id}
            onClick={() => onToolSelect(tool.id)}
            className={`w-9 h-9 flex items-center justify-center rounded-md transition-colors ${
              isActive
                ? 'bg-acid-green/20 text-acid-green'
                : 'text-steel hover:text-chalk hover:bg-asphalt/50'
            }`}
            title={tool.label}
            aria-label={tool.label}
            aria-pressed={isActive}
          >
            {tool.icon}
          </button>
        );
      })}
    </div>
  );
}

/** Hook to manage active tool state */
export function useToolDock(defaultTool: ToolId = 'speed-trace') {
  const [activeTool, setActiveTool] = useState<ToolId>(defaultTool);
  return { activeTool, setActiveTool };
}
