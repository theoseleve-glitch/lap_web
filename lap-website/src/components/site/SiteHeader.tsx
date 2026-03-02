'use client';

import { useEffect, useState, useRef } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { topNavLinks } from '@/data/navigation';
import { trackNavRouteClick } from '@/lib/analytics';
import { LocaleSwitcher } from '@/components/site/LocaleSwitcher';
import { useTranslation } from '@/i18n';

const navLabelKey: Record<string, string> = {
  Product: 'nav.product',
  Pricing: 'nav.pricing',
  Demo: 'nav.demo',
  Contact: 'nav.contact',
};

export function SiteHeader() {
  const pathname = usePathname();
  const { t } = useTranslation();
  const [visible, setVisible] = useState(true);
  const lastScrollY = useRef(0);

  useEffect(() => {
    const handleScroll = () => {
      const y = window.scrollY;
      // Show when at top or scrolling up, hide when scrolling down
      if (y <= 50 || y < lastScrollY.current) {
        setVisible(true);
      } else if (y > lastScrollY.current) {
        setVisible(false);
      }
      lastScrollY.current = y;
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  return (
    <header
      className="sticky top-0 z-50 border-b-2 border-chalk/15 bg-asphalt/95 backdrop-blur transition-transform duration-300"
      style={{ transform: visible ? 'translateY(0)' : 'translateY(-100%)' }}
    >
      <div className="mx-auto max-w-6xl px-4 py-1.5 flex flex-wrap items-center justify-between gap-2">
        <Link
          href="/"
          className="group relative font-monument text-2xl border-2 border-chalk/70 px-3 py-1 leading-none tracking-tight hover:border-pit-orange transition-colors duration-[420ms]"
          onClick={() => trackNavRouteClick('/', 'header')}
        >
          <span className="text-chalk group-hover:text-pit-orange transition-colors duration-[420ms]">LAP</span>
        </Link>

        <nav aria-label="Primary" className="flex flex-wrap items-center gap-2">
          {topNavLinks.map((link) => {
            const active = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`px-3 py-1 border text-xs font-telemetry tracking-[0.12em] uppercase ${
                  active
                    ? 'border-pit-orange text-chalk'
                    : 'border-chalk/20 text-steel hover:text-chalk hover:border-steel'
                }`}
              onClick={() => trackNavRouteClick(link.href, 'header')}
            >
              {t(navLabelKey[link.label] ?? '', link.label)}
            </Link>
          );
        })}
          <LocaleSwitcher />

          <span className="w-px h-5 bg-steel/30 mx-1 hidden sm:block" />

          <Link
            href="/login"
            className={`px-3 py-1 border text-xs font-telemetry tracking-[0.12em] uppercase ${
              pathname === '/login'
                ? 'border-pit-orange text-chalk'
                : 'border-chalk/20 text-steel hover:text-chalk hover:border-steel'
            }`}
            onClick={() => trackNavRouteClick('/login', 'header')}
          >
            {t('nav.login')}
          </Link>
          <Link
            href="/register"
            className="px-3 py-1 border text-xs font-telemetry tracking-[0.12em] uppercase bg-pit-orange/90 border-pit-orange text-asphalt hover:bg-pit-orange transition-colors duration-[420ms]"
            onClick={() => trackNavRouteClick('/register', 'header')}
          >
            {t('nav.signup')}
          </Link>
        </nav>
      </div>
    </header>
  );
}
