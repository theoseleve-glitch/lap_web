'use client';

import { useKernelStore } from '@/experience/state/store';
import { sectorTabs, colors } from '@/lib/tokens';

const RING_RADIUS = 8;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

function ProgressRing({ progress, color }: { progress: number; color: string }) {
  const dashOffset = RING_CIRCUMFERENCE * (1 - progress);

  return (
    <svg width="22" height="22" viewBox="0 0 22 22" className="flex-shrink-0" aria-hidden="true">
      {/* Background ring */}
      <circle
        cx="11"
        cy="11"
        r={RING_RADIUS}
        fill="none"
        stroke="var(--steel)"
        strokeWidth="2"
        opacity="0.3"
      />
      {/* Progress ring */}
      <circle
        cx="11"
        cy="11"
        r={RING_RADIUS}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeDasharray={RING_CIRCUMFERENCE}
        strokeDashoffset={dashOffset}
        strokeLinecap="round"
        transform="rotate(-90 11 11)"
        className="transition-all duration-[420ms]"
      />
    </svg>
  );
}

export function TimingTower() {
  const sectors = useKernelStore((s) => s.hudTower.sectors);
  const activeSectorIndex = useKernelStore((s) => s.hudTower.activeSectorIndex);
  const safetyCarActive = useKernelStore((s) => s.safetyCar.active);

  const handleClick = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' });
  };

  return (
    <>
      {/* Safety Car indicator */}
      {safetyCarActive && (
        <div
          className="fixed left-4 top-[calc(50%-180px)] hidden md:block pointer-events-none font-telemetry text-[9px] tracking-[0.2em] uppercase"
          style={{ zIndex: 'var(--z-sector)' as unknown as number, color: colors.marshalYellow }}
        >
          SC
        </div>
      )}

      {/* Desktop: vertical left rail */}
      <nav
        className="fixed left-4 top-1/2 -translate-y-1/2 hidden md:flex flex-col gap-2"
        style={{ zIndex: 'var(--z-sector)' as unknown as number }}
        aria-label="Section navigation"
      >
        {sectors.map((sector, index) => {
          const isActive = index === activeSectorIndex;
          const isCompleted = sector.status === 'completed';
          const tab = sectorTabs[index];
          if (!tab) return null;

          return (
            <button
              type="button"
              key={sector.id}
              onClick={() => handleClick(tab.id)}
              className="flex items-center gap-2 py-1 pl-1 pr-3 transition-all duration-[420ms] group"
              aria-label={`Go to ${tab.label}`}
              aria-current={isActive ? 'true' : undefined}
            >
              <ProgressRing progress={sector.progress} color={sector.color} />
              <span
                className="font-telemetry text-[11px] tracking-[0.12em] uppercase transition-all duration-[420ms]"
                style={{
                  color: isCompleted ? colors.racingPurple : isActive ? 'var(--chalk)' : 'var(--steel)',
                  textShadow: isActive ? `0 0 8px ${colors.racingPurple}66` : 'none',
                }}
              >
                {sector.id}
              </span>
            </button>
          );
        })}
      </nav>

      {/* Mobile: dots on right (preserved from SectorTabs) */}
      <nav
        className="fixed right-3 top-1/2 -translate-y-1/2 flex md:hidden flex-col gap-2"
        style={{ zIndex: 'var(--z-sector)' as unknown as number }}
        aria-label="Section navigation"
      >
        {sectors.map((sector, index) => {
          const isActive = index === activeSectorIndex;
          const isCompleted = sector.status === 'completed';
          const tab = sectorTabs[index];
          if (!tab) return null;

          return (
            <button
              type="button"
              key={sector.id}
              onClick={() => handleClick(tab.id)}
              className="w-2 h-2 rounded-full transition-all duration-[420ms]"
              style={{
                background: isCompleted ? colors.racingPurple : isActive ? 'var(--chalk)' : 'var(--steel)',
              }}
              aria-label={`Go to ${tab.label}`}
              aria-current={isActive ? 'true' : undefined}
            />
          );
        })}
      </nav>
    </>
  );
}
