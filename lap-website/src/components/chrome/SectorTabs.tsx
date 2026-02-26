'use client';

import { useActiveRoom } from '@/hooks/useActiveRoom';
import { useAccentColor } from '@/hooks/useAccentColor';
import { sectorTabs } from '@/lib/tokens';

export function SectorTabs() {
  const activeRoom = useActiveRoom();
  const accentColor = useAccentColor(activeRoom);

  const handleClick = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' });
  };

  return (
    <>
      {/* Desktop: vertical tabs on left */}
      <nav
        className="fixed left-4 top-1/2 -translate-y-1/2 hidden md:flex flex-col gap-3"
        style={{ zIndex: 'var(--z-sector)' as unknown as number }}
        aria-label="Section navigation"
      >
        {sectorTabs.map((tab) => {
          const isActive = activeRoom === tab.id ||
            (tab.label === 'S1' && (activeRoom === 's1-pain' || activeRoom === 's1-deep')) ||
            (tab.label === 'S2' && (activeRoom === 's2-pipeline' || activeRoom === 's2-proof'));

          return (
            <button
              key={tab.id}
              onClick={() => handleClick(tab.id)}
              className="font-telemetry text-[11px] tracking-[0.12em] uppercase text-left pl-3 py-1 transition-all duration-[420ms]"
              style={{
                borderLeft: isActive ? `3px solid ${accentColor}` : '3px solid transparent',
                color: isActive ? accentColor : 'var(--steel)',
              }}
            >
              {tab.label}
            </button>
          );
        })}
      </nav>

      {/* Mobile: dots on right */}
      <nav
        className="fixed right-3 top-1/2 -translate-y-1/2 flex md:hidden flex-col gap-2"
        style={{ zIndex: 'var(--z-sector)' as unknown as number }}
        aria-label="Section navigation"
      >
        {sectorTabs.map((tab) => {
          const isActive = activeRoom === tab.id ||
            (tab.label === 'S1' && (activeRoom === 's1-pain' || activeRoom === 's1-deep')) ||
            (tab.label === 'S2' && (activeRoom === 's2-pipeline' || activeRoom === 's2-proof'));

          return (
            <button
              key={tab.id}
              onClick={() => handleClick(tab.id)}
              className="w-2 h-2 rounded-full transition-all duration-[420ms]"
              style={{ background: isActive ? accentColor : 'var(--steel)' }}
              aria-label={`Go to ${tab.label}`}
            />
          );
        })}
      </nav>
    </>
  );
}
