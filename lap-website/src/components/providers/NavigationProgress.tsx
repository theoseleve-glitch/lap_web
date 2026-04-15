'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { usePathname } from 'next/navigation';

/**
 * Page transition system: gold progress bar + full-page wipe on navigation.
 * Exit: gold bar fills + content fades out (300ms).
 * Enter: content fades in (400ms).
 */
export function NavigationProgress() {
  const pathname = usePathname();
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [phase, setPhase] = useState<'idle' | 'exit' | 'enter'>('idle');
  const prevPathRef = useRef(pathname);

  const start = useCallback(() => {
    setLoading(true);
    setProgress(20);
    setPhase('exit');
  }, []);

  const finish = useCallback(() => {
    setProgress(100);
    setPhase('enter');
    const timer = setTimeout(() => {
      setLoading(false);
      setProgress(0);
      setPhase('idle');
    }, 500);
    return () => clearTimeout(timer);
  }, []);

  // Intercept link clicks to detect navigation start
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      const anchor = (e.target as HTMLElement).closest('a');
      if (!anchor) return;
      const href = anchor.getAttribute('href');
      if (!href || href.startsWith('http') || href.startsWith('#') || href === pathname) return;
      start();
    };
    document.addEventListener('click', handleClick, true);
    return () => document.removeEventListener('click', handleClick, true);
  }, [pathname, start]);

  // Finish on route change
  useEffect(() => {
    if (pathname !== prevPathRef.current) {
      prevPathRef.current = pathname;
      finish();
    }
  }, [pathname, finish]);

  // Trickle progress while loading
  useEffect(() => {
    if (!loading) return;
    const timer = setInterval(() => {
      setProgress((p) => {
        if (p >= 90) return p;
        return Math.min(p + Math.random() * 8, 90);
      });
    }, 400);
    return () => clearInterval(timer);
  }, [loading]);

  return (
    <>
      {/* Progress bar */}
      {(loading || progress > 0) && (
        <div
          className="fixed top-0 left-0 right-0 z-[9999] h-0.5 pointer-events-none"
          role="progressbar"
          aria-valuenow={Math.round(progress)}
        >
          <div
            className="h-full bg-gold transition-all duration-300 ease-out"
            style={{ width: `${progress}%`, opacity: progress >= 100 ? 0 : 1 }}
          />
        </div>
      )}

      {/* Page content fade — applied via CSS class on <main> */}
      <style>{`
        @media (prefers-reduced-motion: no-preference) {
          .page-transition-exit main {
            opacity: 0.4;
            filter: blur(4px);
            transform: translateY(-8px);
            transition: all 300ms cubic-bezier(0.16, 1, 0.3, 1);
          }
          .page-transition-enter main {
            animation: pageEnter 400ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
          }
          @keyframes pageEnter {
            from {
              opacity: 0;
              filter: blur(4px);
              transform: translateY(16px);
            }
            to {
              opacity: 1;
              filter: blur(0px);
              transform: translateY(0);
            }
          }
        }
      `}</style>

      {/* Apply class to body for transition phases */}
      <TransitionClassApplier phase={phase} />
    </>
  );
}

function TransitionClassApplier({ phase }: { phase: 'idle' | 'exit' | 'enter' }) {
  useEffect(() => {
    const body = document.body;
    body.classList.remove('page-transition-exit', 'page-transition-enter');
    if (phase === 'exit') body.classList.add('page-transition-exit');
    if (phase === 'enter') body.classList.add('page-transition-enter');
    return () => {
      body.classList.remove('page-transition-exit', 'page-transition-enter');
    };
  }, [phase]);

  return null;
}
