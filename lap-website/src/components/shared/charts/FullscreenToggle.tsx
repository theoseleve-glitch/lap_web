'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

interface FullscreenToggleProps {
  children: React.ReactNode;
  className?: string;
  /** Label shown when fullscreen toggle button is hovered */
  label?: string;
}

/**
 * Wraps a chart component and adds a fullscreen toggle button.
 *
 * Uses the browser Fullscreen API. On mobile, this makes the chart
 * fill the entire viewport for easier touch interaction.
 * On non-supporting browsers the button is hidden.
 */
export function FullscreenToggle({
  children,
  className = '',
  label = 'Fullscreen',
}: FullscreenToggleProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [supported, setSupported] = useState(false);

  useEffect(() => {
    setSupported(!!document.fullscreenEnabled);

    const handleChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener('fullscreenchange', handleChange);
    return () => document.removeEventListener('fullscreenchange', handleChange);
  }, []);

  const toggle = useCallback(() => {
    if (!containerRef.current) return;
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    } else {
      containerRef.current.requestFullscreen().catch(() => {});
    }
  }, []);

  if (!supported) {
    return <div className={className}>{children}</div>;
  }

  return (
    <div
      ref={containerRef}
      className={`group/fs relative ${isFullscreen ? 'bg-carbon p-4 overflow-auto' : ''} ${className}`}
    >
      {children}
      <button
        type="button"
        onClick={toggle}
        title={isFullscreen ? 'Exit fullscreen' : label}
        className="absolute top-2 right-2 z-10 p-1.5 rounded bg-asphalt/80 border border-steel/20
          text-steel hover:text-chalk hover:border-acid-green/40 transition-colors
          opacity-0 group-hover/fs:opacity-100 focus:opacity-100 md:opacity-0 touch:opacity-100"
        aria-label={isFullscreen ? 'Exit fullscreen' : `Enter fullscreen: ${label}`}
      >
        {isFullscreen ? (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M6 2v4H2M10 14v-4h4M14 2l-4 4M2 14l4-4" />
          </svg>
        ) : (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M2 6V2h4M14 10v4h-4M2 2l4 4M14 14l-4-4" />
          </svg>
        )}
      </button>
    </div>
  );
}
