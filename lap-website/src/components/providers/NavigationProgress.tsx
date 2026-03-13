'use client';

import { useEffect, useState, useCallback } from 'react';
import { usePathname } from 'next/navigation';

/**
 * Thin progress bar at the top of the viewport during page navigation.
 * Detects route changes via usePathname() and shows a CSS-animated bar.
 */
export function NavigationProgress() {
  const pathname = usePathname();
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);

  const start = useCallback(() => {
    setLoading(true);
    setProgress(20);
  }, []);

  const finish = useCallback(() => {
    setProgress(100);
    const timer = setTimeout(() => {
      setLoading(false);
      setProgress(0);
    }, 300);
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
    finish();
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

  if (!loading && progress === 0) return null;

  return (
    <div
      className="fixed top-0 left-0 right-0 z-[9999] h-0.5 pointer-events-none"
      role="progressbar"
      aria-valuenow={Math.round(progress)}
    >
      <div
        className="h-full bg-pit-orange transition-all duration-300 ease-out"
        style={{ width: `${progress}%`, opacity: progress >= 100 ? 0 : 1 }}
      />
    </div>
  );
}
