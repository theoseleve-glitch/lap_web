import type { ReactNode } from 'react';
import { ExperienceShell } from '@/experience/ExperienceShell';
import { CookieConsentBanner } from '@/components/site/CookieConsentBanner';

export default function MarketingLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <a
        href="/pricing"
        className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-1/2 focus:-translate-x-1/2 focus:z-[200] font-telemetry bg-asphalt text-chalk px-4 py-2 border-2 border-chalk"
      >
        Skip to pricing
      </a>
      <ExperienceShell>{children}</ExperienceShell>
      <CookieConsentBanner />
    </>
  );
}
