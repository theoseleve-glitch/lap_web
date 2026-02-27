'use client';

import { useState, useCallback, type ReactNode } from 'react';

interface RadioCardProps {
  label: string;
  children: ReactNode;
  className?: string;
}

export function RadioCard({ label, children, className = '' }: RadioCardProps) {
  const [expanded, setExpanded] = useState(false);

  const toggle = useCallback(() => {
    setExpanded((prev) => !prev);
  }, []);

  return (
    <div
      className={`relative bg-concrete border transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] cursor-pointer select-none ${
        expanded
          ? 'border-l-[3px] border-l-racing-purple border-steel/30'
          : 'border-steel/20 hover:border-steel/40'
      } ${className}`}
      onClick={toggle}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          toggle();
        }
      }}
      role="button"
      tabIndex={0}
      aria-expanded={expanded}
    >
      {/* Compact header */}
      <div className="flex items-center gap-3 px-4 py-3">
        <span className="shrink-0 inline-flex items-center gap-1.5 font-telemetry text-[10px] tracking-[0.14em] uppercase text-racing-purple bg-racing-purple/10 px-2 py-0.5">
          RADIO
        </span>
        <span className="font-telemetry text-[11px] tracking-[0.12em] uppercase text-chalk truncate">
          {label}
        </span>

        {/* Waveform bars — visible when expanded */}
        <div
          className={`ml-auto flex items-end gap-[2px] h-3 transition-opacity duration-300 ${
            expanded ? 'opacity-100' : 'opacity-0'
          }`}
          aria-hidden="true"
        >
          <span className="radio-bar w-[2px] bg-racing-purple" style={{ animationDelay: '0ms' }} />
          <span className="radio-bar w-[2px] bg-racing-purple" style={{ animationDelay: '120ms' }} />
          <span className="radio-bar w-[2px] bg-racing-purple" style={{ animationDelay: '240ms' }} />
          <span className="radio-bar w-[2px] bg-racing-purple" style={{ animationDelay: '60ms' }} />
          <span className="radio-bar w-[2px] bg-racing-purple" style={{ animationDelay: '180ms' }} />
        </div>
      </div>

      {/* Expanded content */}
      <div
        className="overflow-hidden transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]"
        style={{
          maxHeight: expanded ? '500px' : '0px',
          opacity: expanded ? 1 : 0,
        }}
      >
        <div className="px-4 pb-4 pt-1 font-body text-sm text-steel leading-relaxed border-t border-steel/10">
          {children}
        </div>
      </div>

      {/* Waveform animation keyframes */}
      <style jsx>{`
        @keyframes radio-wave {
          0%, 100% { height: 3px; }
          50% { height: 12px; }
        }
        .radio-bar {
          animation: radio-wave 0.8s ease-in-out infinite;
        }
      `}</style>
    </div>
  );
}
