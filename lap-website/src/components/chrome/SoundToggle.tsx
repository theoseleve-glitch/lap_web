'use client';

import { useState, useCallback } from 'react';
import { soundManager } from '@/lib/sound-manager';

export function SoundToggle() {
  const [muted, setMuted] = useState(soundManager.muted);

  const toggle = useCallback(() => {
    const nowMuted = soundManager.toggleMute();
    setMuted(nowMuted);
  }, []);

  return (
    <button
      type="button"
      onClick={toggle}
      className="fixed bottom-4 right-4 z-[60] w-10 h-10 flex items-center justify-center border border-steel/20 bg-concrete/80 backdrop-blur text-steel hover:text-chalk hover:border-steel transition-colors duration-200"
      aria-label={muted ? 'Unmute sound' : 'Mute sound'}
      title={muted ? 'Sound off' : 'Sound on'}
    >
      <span className="font-telemetry text-[8px] tracking-[0.12em] uppercase">
        {muted ? 'OFF' : 'ON'}
      </span>
    </button>
  );
}
