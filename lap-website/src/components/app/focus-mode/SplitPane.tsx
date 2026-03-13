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

  const applyResize = useCallback((clientX: number) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const totalWidth = rect.width;
    const x = clientX - rect.left;

    const minPercent = (minPanelWidth / totalWidth) * 100;
    const maxPercent = 100 - minPercent;
    const newPercent = Math.max(minPercent, Math.min(maxPercent, (x / totalWidth) * 100));
    setLeftPercent(newPercent);
  }, [minPanelWidth]);

  const startDrag = useCallback(() => {
    dragging.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, []);

  const stopDrag = useCallback(() => {
    if (dragging.current) {
      dragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    startDrag();
  }, [startDrag]);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    startDrag();
    if (e.touches[0]) applyResize(e.touches[0].clientX);
  }, [startDrag, applyResize]);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      applyResize(e.clientX);
    };
    const handleTouchMove = (e: TouchEvent) => {
      if (!dragging.current || !e.touches[0]) return;
      e.preventDefault(); // prevent scroll during drag
      applyResize(e.touches[0].clientX);
    };
    const handleEnd = () => stopDrag();

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleEnd);
    document.addEventListener('touchmove', handleTouchMove, { passive: false });
    document.addEventListener('touchend', handleEnd);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleEnd);
      document.removeEventListener('touchmove', handleTouchMove);
      document.removeEventListener('touchend', handleEnd);
    };
  }, [applyResize, stopDrag]);

  return (
    <div ref={containerRef} className="flex h-full w-full overflow-hidden">
      {/* Left panel */}
      <div
        className="h-full overflow-hidden"
        style={{ width: `${leftPercent}%` }}
      >
        {leftContent}
      </div>

      {/* Divider */}
      <div
        onMouseDown={handleMouseDown}
        onTouchStart={handleTouchStart}
        className="w-1 shrink-0 cursor-col-resize bg-steel/30 hover:bg-gold transition-colors touch-none"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize panels"
      />

      {/* Right panel */}
      <div
        className="h-full overflow-hidden"
        style={{ width: `${100 - leftPercent}%` }}
      >
        {rightContent}
      </div>
    </div>
  );
}
