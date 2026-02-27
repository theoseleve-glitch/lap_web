'use client';

import { useKernelStore } from '@/experience/state/store';
import { colors } from '@/lib/tokens';

export function DrsLabel() {
  const active = useKernelStore((s) => s.drs.active);

  return (
    <div
      className="fixed left-4 top-[calc(50%+140px)] hidden md:block pointer-events-none"
      style={{ zIndex: 'var(--z-drs)' as unknown as number }}
      aria-hidden="true"
    >
      <span
        className="font-telemetry text-[13px] tracking-[0.2em] uppercase transition-opacity"
        style={{
          color: colors.racingPurple,
          opacity: active ? 1 : 0,
          transitionDuration: active ? '300ms' : '200ms',
        }}
      >
        DRS
      </span>
    </div>
  );
}
