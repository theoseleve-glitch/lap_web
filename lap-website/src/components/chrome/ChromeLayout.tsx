'use client';

import { type ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { GsapProvider } from '@/components/providers/GsapProvider';
import { PerformanceProvider } from '@/lib/performance-context';
import { SiteHeader } from '@/components/site/SiteHeader';
import { SiteFooter } from '@/components/site/SiteFooter';

export function ChromeLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isHome = pathname === '/';

  // On the home page, ExperienceShell provides its own SiteHeader + chrome.
  // Just pass children through to avoid duplicate nav/footer.
  if (isHome) {
    return <>{children}</>;
  }

  return (
    <PerformanceProvider>
      <GsapProvider>
        <SiteHeader />
        {children}
        <SiteFooter />
      </GsapProvider>
    </PerformanceProvider>
  );
}
