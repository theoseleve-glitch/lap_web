'use client';

import type { ReactNode } from 'react';

interface FallbackShellProps {
  children: ReactNode;
}

export function FallbackShell({ children }: FallbackShellProps) {
  return (
    <div className="texture-grain min-h-screen">
      {children}
    </div>
  );
}
