'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { topNavLinks } from '@/data/navigation';
import { trackNavRouteClick } from '@/lib/analytics';

export function SiteHeader() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 border-b border-steel/20 bg-asphalt/95 backdrop-blur">
      <div className="mx-auto max-w-6xl px-4 py-3 flex flex-wrap items-center justify-between gap-3">
        <Link
          href="/"
          className="font-monument text-2xl border border-chalk px-3 py-1"
          onClick={() => trackNavRouteClick('/', 'header')}
        >
          LAP
        </Link>

        <nav aria-label="Primary" className="flex flex-wrap gap-2">
          {topNavLinks.map((link) => {
            const active = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`px-3 py-1 border text-xs font-telemetry tracking-[0.12em] uppercase ${
                  active
                    ? 'border-pit-orange text-chalk'
                    : 'border-steel/30 text-steel hover:text-chalk hover:border-steel'
                }`}
                onClick={() => trackNavRouteClick(link.href, 'header')}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
