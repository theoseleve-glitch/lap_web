'use client';

import { useState, useRef, useCallback, useId, type ReactNode } from 'react';

interface TooltipProps {
  content: string;
  children: ReactNode;
  position?: 'top' | 'bottom';
  className?: string;
}

export function Tooltip({
  content,
  children,
  position = 'top',
  className = '',
}: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>();
  const tooltipId = useId();

  const show = useCallback(() => {
    timeoutRef.current = setTimeout(() => setVisible(true), 300);
  }, []);

  const hide = useCallback(() => {
    clearTimeout(timeoutRef.current);
    setVisible(false);
  }, []);

  const toggle = useCallback(() => setVisible((v) => !v), []);

  const positionClass = position === 'top' ? 'bottom-full mb-2' : 'top-full mt-2';

  return (
    <span
      className={`relative inline-block ${className}`}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      onTouchStart={toggle}
      aria-describedby={visible ? tooltipId : undefined}
    >
      {children}
      {visible && (
        <span
          id={tooltipId}
          className={`
            absolute left-1/2 -translate-x-1/2 ${positionClass}
            bg-asphalt text-chalk border border-steel
            px-3 py-2 max-w-[280px] whitespace-normal
            font-telemetry text-[11px] tracking-[0.12em] uppercase
            pointer-events-none z-[var(--z-overlay)]
          `}
          role="tooltip"
        >
          {content}
          <span
            aria-hidden="true"
            className={`
              absolute left-1/2 -translate-x-1/2
              w-0 h-0
              ${position === 'top'
                ? 'top-full border-l-[6px] border-r-[6px] border-t-[6px] border-l-transparent border-r-transparent border-t-steel'
                : 'bottom-full border-l-[6px] border-r-[6px] border-b-[6px] border-l-transparent border-r-transparent border-b-steel'
              }
            `}
          />
        </span>
      )}
    </span>
  );
}
