'use client';

import { useState, useEffect, useRef } from 'react';

export function useFpsMonitor(threshold = 40, windowMs = 2000) {
  const [isLowFps, setIsLowFps] = useState(false);
  const frames = useRef<number[]>([]);
  const rafId = useRef<number>(0);

  useEffect(() => {
    let lastTime = performance.now();

    function tick() {
      const now = performance.now();
      const dt = now - lastTime;
      lastTime = now;
      if (dt > 0) frames.current.push(1000 / dt);

      // Keep only last windowMs of samples
      while (frames.current.length > 120) {
        frames.current.shift();
      }

      // Check average
      if (frames.current.length >= 30) {
        const avg = frames.current.reduce((a, b) => a + b, 0) / frames.current.length;
        setIsLowFps(avg < threshold);
      }

      rafId.current = requestAnimationFrame(tick);
    }

    rafId.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId.current);
  }, [threshold, windowMs]);

  return { isLowFps };
}
