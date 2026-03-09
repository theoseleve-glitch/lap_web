'use client';

import { useState, useEffect } from 'react';

interface PromoCountdownProps {
  /** ISO date string for when the promotion ends */
  endsAt: string;
  /** Promotion label */
  label?: string;
  className?: string;
}

function pad(n: number): string {
  return n.toString().padStart(2, '0');
}

export function PromoCountdown({ endsAt, label = 'Offer ends in', className = '' }: PromoCountdownProps) {
  const [remaining, setRemaining] = useState<{ d: number; h: number; m: number; s: number } | null>(null);

  useEffect(() => {
    const target = new Date(endsAt).getTime();
    function tick() {
      const diff = target - Date.now();
      if (diff <= 0) {
        setRemaining(null);
        return;
      }
      const s = Math.floor(diff / 1000);
      setRemaining({
        d: Math.floor(s / 86400),
        h: Math.floor((s % 86400) / 3600),
        m: Math.floor((s % 3600) / 60),
        s: s % 60,
      });
    }
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [endsAt]);

  if (!remaining) return null;

  return (
    <div className={`flex items-center justify-center gap-3 py-3 px-4 bg-pit-orange/10 border border-pit-orange/30 rounded-lg ${className}`}>
      <span className="font-telemetry text-[10px] tracking-[0.12em] uppercase text-pit-orange">{label}</span>
      <div className="flex gap-1.5">
        {remaining.d > 0 && (
          <span className="font-monument text-sm text-chalk bg-concrete px-2 py-1 rounded">{remaining.d}d</span>
        )}
        <span className="font-monument text-sm text-chalk bg-concrete px-2 py-1 rounded">{pad(remaining.h)}h</span>
        <span className="font-monument text-sm text-chalk bg-concrete px-2 py-1 rounded">{pad(remaining.m)}m</span>
        <span className="font-monument text-sm text-chalk bg-concrete px-2 py-1 rounded">{pad(remaining.s)}s</span>
      </div>
    </div>
  );
}
