'use client';

import { useScrollProgress } from '@/hooks/useScrollProgress';
import { useMemo } from 'react';

function formatTimecode(progress: number): string {
  const totalMs = progress * 4 * 60 * 1000; // 0 -> 4:00.000
  const mins = Math.floor(totalMs / 60000);
  const secs = Math.floor((totalMs % 60000) / 1000);
  const ms = Math.floor(totalMs % 1000);
  return `T+ ${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

function formatDistance(progress: number): string {
  const km = progress * 4.2;
  return `D ${km.toFixed(2)} km`;
}

function AnimatedDigits({ text }: { text: string }) {
  return (
    <span className="inline-flex">
      {text.split('').map((char, i) => (
        <span
          key={`${i}-${char}`}
          className="inline-block transition-transform duration-200"
          style={{ width: /\d/.test(char) ? '0.65em' : 'auto' }}
        >
          {char}
        </span>
      ))}
    </span>
  );
}

export function TimecodeCounter() {
  const progress = useScrollProgress();
  const timecode = useMemo(() => formatTimecode(progress), [progress]);
  const distance = useMemo(() => formatDistance(progress), [progress]);

  return (
    <div
      className="fixed top-4 right-4 font-telemetry text-[11px] tracking-[0.12em] text-steel text-right"
      style={{ zIndex: 'var(--z-timecode)' as unknown as number }}
    >
      <div><AnimatedDigits text={timecode} /></div>
      <div><AnimatedDigits text={distance} /></div>
    </div>
  );
}
