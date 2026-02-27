'use client';

import { useState, useEffect, useRef } from 'react';
import { useKernelStore } from '@/experience/state/store';
import { rooms } from '@/lib/tokens';

export function DebugHUD() {
  const [visible, setVisible] = useState(false);
  const [fps, setFps] = useState(0);
  const framesRef = useRef<number[]>([]);

  const state = useKernelStore();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'D') {
        e.preventDefault();
        setVisible((v) => !v);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  useEffect(() => {
    if (!visible) return;
    let rafId: number;
    let lastTime = performance.now();

    function tick() {
      const now = performance.now();
      const dt = now - lastTime;
      lastTime = now;
      if (dt > 0) {
        framesRef.current.push(1000 / dt);
        if (framesRef.current.length > 60) framesRef.current.shift();
        const avg = framesRef.current.reduce((a, b) => a + b, 0) / framesRef.current.length;
        setFps(Math.round(avg));
      }
      rafId = requestAnimationFrame(tick);
    }

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [visible]);

  if (!visible) return null;

  const room = rooms[state.currentChapter] ?? rooms[0];

  return (
    <div
      className="fixed top-20 right-4 z-[9999] bg-asphalt/95 border border-steel/40 p-3 font-telemetry text-[10px] leading-relaxed pointer-events-none select-none"
      style={{ minWidth: 200 }}
      aria-hidden="true"
    >
      <div className="text-acid-green mb-1">DEBUG HUD</div>
      <div>FPS: <span className={fps < 40 ? 'text-safety-red' : 'text-chalk'}>{fps}</span></div>
      <div>Quality: {state.qualityTier} ({state.qualityMode})</div>
      <div>Chapter: {room.id} [{state.currentChapter}]</div>
      <div>Progress: {state.globalProgress.toFixed(3)}</div>
      <div>Ch.Progress: {state.chapterProgress.toFixed(3)}</div>
      <div>Velocity: {state.scrollVelocity.toFixed(3)}</div>
      <div>Pointer: {state.pointerX.toFixed(2)}, {state.pointerY.toFixed(2)}</div>
      <div>Mode: {state.mode}</div>
      <div>WebGL: {state.webglAvailable ? 'yes' : 'no'}</div>
      <div>ReducedMotion: {state.reducedMotion ? 'yes' : 'no'}</div>
      <div>Preloader: {state.preloaderComplete ? 'done' : `${(state.loadProgress * 100).toFixed(0)}%`}</div>
    </div>
  );
}
