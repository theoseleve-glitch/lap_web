'use client';

import { useState, useRef, useCallback, useEffect, type ReactNode } from 'react';

interface SplitPaneProps {
  leftContent: ReactNode;
  rightContent: ReactNode;
  defaultLeftWidth?: number; // percentage, default 60
  minPanelWidth?: number; // pixels, default 200
}

export function SplitPane({
  leftContent,
  rightContent,
  defaultLeftWidth = 60,
  minPanelWidth = 200,
}: SplitPaneProps) {
  const [leftPercent, setLeftPercent] = useState(defaultLeftWidth);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!dragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const totalWidth = rect.width;
      const x = e.clientX - rect.left;

      // Enforce min width
      const minPercent = (minPanelWidth / totalWidth) * 100;
      const maxPercent = 100 - minPercent;
      const newPercent = Math.max(minPercent, Math.min(maxPercent, (x / totalWidth) * 100));
      setLeftPercent(newPercent);
    };

    const handleMouseUp = () => {
      if (dragging.current) {
        dragging.current = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      }
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [minPanelWidth]);

  return (
    <div ref={containerRef} className="flex h-full w-full overflow-hidden">
      {/* Left panel */}
      <div
        className="h-full overflow-auto"
        style={{ width: `${leftPercent}%` }}
      >
        {leftContent}
      </div>

      {/* Divider */}
      <div
        onMouseDown={handleMouseDown}
        className="w-1 shrink-0 cursor-col-resize bg-steel/30 hover:bg-acid-green transition-colors"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize panels"
      />

      {/* Right panel */}
      <div
        className="h-full overflow-auto"
        style={{ width: `${100 - leftPercent}%` }}
      >
        {rightContent}
      </div>
    </div>
  );
}
