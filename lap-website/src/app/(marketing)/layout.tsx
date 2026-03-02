import type { ReactNode } from 'react';
import { ChromeLayout } from '@/components/chrome/ChromeLayout';
import { ExperienceProvider } from '@/experience/ExperienceProvider';
import { CookieConsentBanner } from '@/components/site/CookieConsentBanner';

export default function MarketingLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-1/2 focus:-translate-x-1/2 focus:z-[200] font-telemetry bg-asphalt text-chalk px-4 py-2 border-2 border-pit-orange min-h-[44px] inline-flex items-center"
      >
        Skip to main content
      </a>
      <ExperienceProvider>
        <ChromeLayout>{children}</ChromeLayout>
      </ExperienceProvider>
      <CookieConsentBanner />
    </>
  );
}
