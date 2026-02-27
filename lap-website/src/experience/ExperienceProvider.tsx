'use client';

import { type ReactNode, useState, useEffect, lazy, Suspense } from 'react';
import { usePathname } from 'next/navigation';

// Lazy-load ExperienceShell to keep R3F out of SSR bundle
const ExperienceShellLazy = lazy(() =>
  import('./ExperienceShell').then((m) => ({ default: m.ExperienceShell })),
);

export function ExperienceProvider({ children }: { children: ReactNode }) {
  const [mounted, setMounted] = useState(false);
  const pathname = usePathname();
  const isHome = pathname === '/';

  useEffect(() => {
    setMounted(true);
  }, []);

  // SSR and non-home pages: render children directly (no kernel)
  if (!mounted || !isHome) {
    return <>{children}</>;
  }

  return (
    <Suspense fallback={<div className="min-h-screen bg-asphalt" />}>
      <ExperienceShellLazy>{children}</ExperienceShellLazy>
    </Suspense>
  );
}
