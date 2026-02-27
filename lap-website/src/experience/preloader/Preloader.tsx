'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useKernelStore } from '@/experience/state/store';
import { PRELOADER_AUTO_UNLOCK_MS, PRELOADER_BLACK_MS, PRELOADER_WORDMARK_MS } from './PreloaderTimeline';
import { timing } from '@/lib/tokens';

export function Preloader() {
  const [phase, setPhase] = useState<'black' | 'wordmark' | 'loading' | 'ready' | 'unlocking' | 'done'>('black');
  const loadProgress = useKernelStore((s) => s.loadProgress);
  const setLoadProgress = useKernelStore((s) => s.setLoadProgress);
  const completePreloader = useKernelStore((s) => s.completePreloader);
  const preloaderComplete = useKernelStore((s) => s.preloaderComplete);
  const autoUnlockRef = useRef<ReturnType<typeof setTimeout>>();
  const intervalRef = useRef<ReturnType<typeof setInterval>>();

  // Phase progression
  useEffect(() => {
    const t1 = setTimeout(() => setPhase('wordmark'), PRELOADER_BLACK_MS);
    const t2 = setTimeout(() => {
      setPhase('loading');
      let progress = 0;
      intervalRef.current = setInterval(() => {
        progress += 0.02 + Math.random() * 0.03;
        if (progress >= 1) {
          progress = 1;
          clearInterval(intervalRef.current);
          setPhase('ready');
        }
        setLoadProgress(Math.min(1, progress));
      }, 50);
    }, PRELOADER_BLACK_MS + PRELOADER_WORDMARK_MS);

    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearInterval(intervalRef.current);
    };
  }, [setLoadProgress]);

  const unlock = useCallback(() => {
    if (phase !== 'ready' && phase !== 'loading') return;
    clearTimeout(autoUnlockRef.current);
    clearInterval(intervalRef.current);
    setPhase('unlocking');
    setTimeout(() => {
      setPhase('done');
      completePreloader();
    }, timing.monument * 1000);
  }, [phase, completePreloader]);

  // Auto-unlock after timeout
  useEffect(() => {
    if (phase !== 'ready') return;
    autoUnlockRef.current = setTimeout(() => unlock(), PRELOADER_AUTO_UNLOCK_MS);
    return () => clearTimeout(autoUnlockRef.current);
  }, [phase, unlock]);

  // Handle user interaction to unlock
  useEffect(() => {
    if (phase !== 'ready') return;

    const handler = () => unlock();
    window.addEventListener('click', handler);
    window.addEventListener('touchstart', handler);
    window.addEventListener('wheel', handler);
    window.addEventListener('keydown', handler);

    return () => {
      window.removeEventListener('click', handler);
      window.removeEventListener('touchstart', handler);
      window.removeEventListener('wheel', handler);
      window.removeEventListener('keydown', handler);
    };
  }, [phase, unlock]);

  if (preloaderComplete || phase === 'done') return null;

  return (
    <div
      className="fixed inset-0 z-[9999] flex flex-col items-center justify-center bg-asphalt"
      style={{
        opacity: phase === 'unlocking' ? 0 : 1,
        transition: `opacity ${timing.monument}s var(--ease-inertia)`,
      }}
    >
      {/* Wordmark */}
      <div
        className="font-monument text-chalk transition-opacity"
        style={{
          fontSize: 'clamp(48px, 8vw, 120px)',
          opacity: phase === 'black' ? 0 : 1,
          transitionDuration: `${timing.monument}s`,
          transitionTimingFunction: 'var(--ease-inertia)',
        }}
      >
        LAP
      </div>

      {/* Progress bar */}
      {(phase === 'loading' || phase === 'ready') && (
        <div className="w-48 h-px bg-steel/30 mt-8 overflow-hidden">
          <div
            className="h-full bg-chalk transition-all"
            style={{
              width: `${loadProgress * 100}%`,
              transitionDuration: '100ms',
            }}
          />
        </div>
      )}

      {/* Ready text */}
      {phase === 'ready' && (
        <p
          className="font-telemetry text-steel mt-6 animate-pulse"
          style={{ animationDuration: '2s' }}
        >
          READY — CLICK TO BEGIN
        </p>
      )}
    </div>
  );
}
