'use client';

import { useActiveRoom } from '@/hooks/useActiveRoom';
import { useAccentColor } from '@/hooks/useAccentColor';

interface LapWordmarkProps {
  onIndexToggle: () => void;
}

export function LapWordmark({ onIndexToggle }: LapWordmarkProps) {
  const activeRoom = useActiveRoom();
  const accentColor = useAccentColor(activeRoom);

  return (
    <button
      className="fixed top-4 left-4 font-monument text-2xl px-3 py-1 border-2 border-chalk transition-colors duration-[420ms]"
      style={{
        zIndex: 'var(--z-nav)' as unknown as number,
        transform: 'rotate(-0.8deg)',
      }}
      onClick={onIndexToggle}
      aria-label="Open site navigation"
      onMouseEnter={(e) => (e.currentTarget.style.borderColor = accentColor)}
      onMouseLeave={(e) => (e.currentTarget.style.borderColor = '')}
    >
      LAP
    </button>
  );
}
