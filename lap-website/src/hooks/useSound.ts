'use client';

import { useState, useCallback, useRef } from 'react';

export function useSound() {
  const [enabled, setEnabled] = useState(false);
  const howlsRef = useRef<Record<string, { play: () => void }>>({});

  const toggle = useCallback(() => setEnabled((p) => !p), []);

  const play = useCallback(
    async (name: string) => {
      if (!enabled) return;

      // Lazy load Howler
      if (!howlsRef.current[name]) {
        const { Howl } = await import('howler');
        howlsRef.current[name] = new Howl({
          src: [`/audio/${name}.mp3`],
          volume: 0.3,
        });
      }
      howlsRef.current[name].play();
    },
    [enabled],
  );

  return { enabled, toggle, play };
}
