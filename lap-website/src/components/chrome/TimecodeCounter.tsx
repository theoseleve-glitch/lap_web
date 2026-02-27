'use client';

import { useScrollProgress } from '@/hooks/useScrollProgress';
import { useMemo } from 'react';

function formatTimecode(progress: number): string {
  // 0 → 6:29.090 (389 090 ms) — real session total
  const totalMs = progress * 389090;
  const mins = Math.floor(totalMs / 60000);
  const secs = Math.floor((totalMs % 60000) / 1000);
  const cs = Math.floor((totalMs % 1000) / 10); // centiseconds
  return `T+ ${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(cs).padStart(2, '0')}`;
}

function formatDistance(progress: number): string {
  // 0 → 20.832 km — real session distance
  const km = progress * 20.832;
  return `D ${km.toFixed(3)} km`;
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
      className="fixed top-[72px] right-4 md:right-6 font-telemetry text-[14px] md:text-base tracking-[0.12em] text-steel text-right"
      style={{ zIndex: 'var(--z-timecode)' as unknown as number }}
    >
      <div className="bg-concrete/70 border border-steel/30 px-4 py-2.5">
        <div><AnimatedDigits text={timecode} /></div>
        <div className="text-chalk"><AnimatedDigits text={distance} /></div>
      </div>
    </div>
  );
}
