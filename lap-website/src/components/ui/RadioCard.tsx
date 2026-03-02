'use client';

import { useState, useCallback, useMemo, useRef, useLayoutEffect, type ReactNode } from 'react';

interface RadioCardProps {
  label: string;
  children: ReactNode;
  className?: string;
  sender?: string;
  receiver?: string;
  accentColor?: string;
}

/** Generate deterministic waveform bar heights from label content */
function generateWaveform(label: string, bars: number): number[] {
  let seed = 0;
  for (let i = 0; i < label.length; i++) {
    seed = ((seed << 5) - seed + label.charCodeAt(i)) | 0;
  }
  const heights: number[] = [];
  for (let i = 0; i < bars; i++) {
    seed = ((seed * 1103515245 + 12345) & 0x7fffffff);
    heights.push(0.2 + (seed % 100) / 125);
  }
  return heights;
}

/**
 * RadioCard — F1 broadcast-style explanation card.
 *
 * Compact: accent left border + RADIO badge + label.
 * Expanded: header bar (sender → receiver), quoted content, waveform bars.
 *
 * Color spec: card bg #231f20, header = accentColor, text = chalk.
 */
export function RadioCard({
  label,
  children,
  className = '',
  sender = 'ENGINEER',
  receiver = 'DRIVER',
  accentColor = '#C9A84C',
}: RadioCardProps) {
  const [expanded, setExpanded] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const [contentHeight, setContentHeight] = useState(0);
  const waveform = useMemo(() => generateWaveform(label, 20), [label]);

  const toggle = useCallback(() => {
    setExpanded((prev) => !prev);
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        toggle();
      }
    },
    [toggle],
  );

  useLayoutEffect(() => {
    if (contentRef.current) {
      setContentHeight(contentRef.current.scrollHeight);
    }
  }, [children]);

  return (
    <div
      className={`relative overflow-hidden cursor-pointer select-none transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] ${className}`}
      style={{ backgroundColor: '#141414' }}
      onClick={toggle}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
      aria-expanded={expanded}
    >
      {/* Compact header */}
      <div
        className="flex items-center gap-2.5 px-3 py-2.5"
        style={{ borderLeft: expanded ? 'none' : `3px solid ${accentColor}` }}
      >
        <span
          className="shrink-0 font-telemetry text-[9px] tracking-[0.15em] uppercase px-1.5 py-0.5 "
          style={{ backgroundColor: `${accentColor}20`, color: accentColor }}
        >
          RADIO
        </span>
        <span className="font-telemetry text-[11px] tracking-[0.12em] uppercase text-chalk truncate">
          {label}
        </span>
      </div>

      {/* Expanded: header bar + content + waveform */}
      {expanded && (
        <div
          className="px-3 py-1.5 flex items-center justify-between"
          style={{ backgroundColor: accentColor }}
        >
          <span className="font-telemetry text-[10px] tracking-[0.15em] uppercase text-white/90">
            {sender} → {receiver}
          </span>
          <button
            onClick={(e) => { e.stopPropagation(); setExpanded(false); }}
            className="text-white/60 hover:text-white text-xs"
            aria-label="Collapse radio card"
          >
            ✕
          </button>
        </div>
      )}

      <div
        className="overflow-hidden transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]"
        style={{
          maxHeight: expanded ? `${contentHeight + 40}px` : '0px',
          opacity: expanded ? 1 : 0,
        }}
      >
        <div
          ref={contentRef}
          className="px-3 pb-3 pt-2 font-body text-sm text-steel leading-relaxed"
          style={{ borderLeft: `2px solid ${accentColor}40`, marginLeft: '10px' }}
        >
          {children}
        </div>

        {/* Waveform bars */}
        <div className="flex items-end gap-[2px] mx-3 mb-3 h-3" aria-hidden="true">
          {waveform.map((h, i) => (
            <div
              key={i}
              className="flex-1 "
              style={{
                height: `${h * 100}%`,
                backgroundColor: `${accentColor}60`,
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
