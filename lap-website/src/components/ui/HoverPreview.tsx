'use client';

import { useState, useRef, type ReactNode } from 'react';

interface HoverPreviewProps {
  content: ReactNode;
  children: ReactNode;
  className?: string;
}

export function HoverPreview({ content, children, className = '' }: HoverPreviewProps) {
  const [visible, setVisible] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>();

  const show = () => {
    clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => setVisible(true), 300);
  };

  const hide = () => {
    clearTimeout(timeoutRef.current);
    setVisible(false);
  };

  return (
    <div
      className={`relative ${className}`}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {children}
      {visible && (
        <div className="absolute z-40 bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 bg-concrete border border-steel/20 rounded-lg shadow-xl p-3 pointer-events-none">
          {content}
          <div className="absolute top-full left-1/2 -translate-x-1/2 -mt-px">
            <div className="w-2.5 h-2.5 bg-concrete border-r border-b border-steel/20 rotate-45 -translate-y-1/2" />
          </div>
        </div>
      )}
    </div>
  );
}
