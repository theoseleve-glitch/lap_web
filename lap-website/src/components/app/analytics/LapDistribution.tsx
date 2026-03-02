'use client';

import { useEffect, useRef, useId } from 'react';
import { useVanillaChart } from '@/components/shared/charts/useVanillaChart';

interface LapDistributionProps {
  sessionId: string;
  apiBase?: string;
  className?: string;
}

/**
 * LapDistribution — Vanilla JS wrapper for lap_distribution.js.
 *
 * Renders histogram + KDE overlay, box-plot, outlier badges, shape
 * classification, and stats cards.
 *
 * The vanilla module creates all DOM internally — we only need to
 * provide a container div with a unique id.
 */
export function LapDistribution({ sessionId, apiBase, className = '' }: LapDistributionProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cleanedUpRef = useRef(false);
  const reactId = useId();
  const containerId = `lap-distribution-${reactId.replace(/:/g, '')}`;

  const { ready, error } = useVanillaChart({
    sessionId,
    apiBase,
    scripts: ['/js/lap_distribution.js'],
  });

  useEffect(() => {
    if (!ready || !containerRef.current) return;
    cleanedUpRef.current = false;

    if (window.LapDistribution) {
      const initFn = (window.LapDistribution as Record<string, unknown>).init as
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
        Failed to load lap distribution: {error}
      </div>
    );
  }

  return (
    <div ref={containerRef} id={containerId} className={`relative ${className}`}>
      <div className="flex items-center justify-center p-8 text-gray-500">
        <div className="text-sm">Loading distribution data...</div>
      </div>
    </div>
  );
}
