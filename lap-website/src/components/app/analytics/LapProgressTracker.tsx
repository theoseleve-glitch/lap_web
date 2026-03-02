'use client';

import { useEffect, useRef, useId } from 'react';
import { useVanillaChart } from '@/components/shared/charts/useVanillaChart';

interface LapProgressTrackerProps {
  sessionId: string;
  apiBase?: string;
  className?: string;
}

/**
 * LapProgressTracker — Vanilla JS wrapper for lap_progress.js.
 *
 * Renders running PB line, pace zones, flow state highlights,
 * rolling CV, and momentum summary.
 *
 * The vanilla module creates all DOM internally — we only need to
 * provide a container div with a unique id.
 */
export function LapProgressTracker({ sessionId, apiBase, className = '' }: LapProgressTrackerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cleanedUpRef = useRef(false);
  const reactId = useId();
  const containerId = `lap-progress-${reactId.replace(/:/g, '')}`;

  const { ready, error } = useVanillaChart({
    sessionId,
    apiBase,
    scripts: ['/js/lap_progress.js'],
  });

  useEffect(() => {
    if (!ready || !containerRef.current) return;
    cleanedUpRef.current = false;

    if (window.LapProgress) {
      const initFn = (window.LapProgress as Record<string, unknown>).init as
        | ((cid: string, sid: string) => void)
        | undefined;
      if (initFn) initFn(containerId, sessionId);
    }

    return () => {
      if (cleanedUpRef.current) return;
      cleanedUpRef.current = true;
      const el = containerRef.current;
      if (el) while (el.firstChild) el.removeChild(el.firstChild);
    };
  }, [ready, containerId, sessionId]);

  if (error) {
    return (
      <div className={`text-red-400 p-4 ${className}`}>
        Failed to load lap progress: {error}
      </div>
    );
  }

  return (
    <div ref={containerRef} id={containerId} className={`relative ${className}`}>
      <div className="flex items-center justify-center p-8 text-gray-500">
        <div className="text-sm">Loading progress data...</div>
      </div>
    </div>
  );
}
