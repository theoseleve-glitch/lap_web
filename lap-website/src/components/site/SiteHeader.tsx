'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { topNavLinks } from '@/data/navigation';
import { trackNavRouteClick } from '@/lib/analytics';
import { LocaleSwitcher } from '@/components/site/LocaleSwitcher';
import { MobileDrawer } from '@/components/site/MobileDrawer';
import { useTranslation } from '@/i18n';

const navLabelKey: Record<string, string> = {
  Product: 'nav.product',
  Pricing: 'nav.pricing',
  'For Venues': 'nav.venues',
  Demo: 'nav.demo',
  Contact: 'nav.contact',
};

export function SiteHeader() {
  const pathname = usePathname();
  const { t } = useTranslation();
  const [visible, setVisible] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const lastScrollY = useRef(0);

  useEffect(() => {
    const handleScroll = () => {
      const y = window.scrollY;
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

  // Lock body scroll when drawer is open
  useEffect(() => {
    if (drawerOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [drawerOpen]);

  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  return (
    <>
      <header
        className="sticky top-0 z-[60] border-b border-chalk/15 bg-asphalt/95 backdrop-blur transition-transform duration-300"
        style={{ transform: visible || drawerOpen ? 'translateY(0)' : 'translateY(-100%)' }}
      >
        <div className="mx-auto max-w-6xl px-4 py-2 flex items-center justify-between gap-3">
          {/* Logo */}
          <Link
            href="/"
            className="group relative font-monument text-2xl border-2 border-chalk/70 px-3 py-1.5 leading-none tracking-tight hover:border-pit-orange transition-colors duration-200 min-h-[44px] flex items-center"
            onClick={() => trackNavRouteClick('/', 'header')}
          >
            <span className="text-chalk group-hover:text-pit-orange transition-colors duration-200">LAP</span>
          </Link>

          {/* Desktop nav — hidden on mobile */}
          <nav aria-label="Primary" className="hidden lg:flex items-center gap-1">
            {topNavLinks.map((link) => {
              const active = pathname === link.href || (link.href.startsWith('/contact?') && pathname === '/contact');
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`inline-flex items-center min-h-[44px] px-3 py-2 border text-xs font-telemetry tracking-[0.12em] uppercase transition-colors duration-200 cursor-pointer ${
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

            <span className="w-px h-5 bg-steel/30 mx-1" aria-hidden="true" />

            <Link
              href="/login"
              className={`inline-flex items-center min-h-[44px] px-3 py-2 border text-xs font-telemetry tracking-[0.12em] uppercase transition-colors duration-200 cursor-pointer ${
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
              className="inline-flex items-center min-h-[44px] px-3 py-2 border text-xs font-telemetry tracking-[0.12em] uppercase bg-pit-orange border-pit-orange text-asphalt hover:bg-[#D4B35A] transition-colors duration-200 cursor-pointer"
              onClick={() => trackNavRouteClick('/register', 'header')}
            >
              {t('nav.signup')}
            </Link>
          </nav>

          {/* Mobile: CTA + hamburger */}
          <div className="flex lg:hidden items-center gap-2">
            <Link
              href="/register?source=mobile-header"
              className="inline-flex items-center min-h-[44px] px-3 py-2 font-telemetry text-[10px] tracking-[0.12em] uppercase bg-pit-orange border border-pit-orange text-asphalt hover:bg-[#D4B35A] transition-colors duration-200 cursor-pointer"
              onClick={() => trackNavRouteClick('/register', 'header-mobile')}
            >
              {t('nav.signup')}
            </Link>
            <button
              onClick={() => setDrawerOpen((prev) => !prev)}
              className="min-h-[44px] min-w-[44px] flex items-center justify-center border border-chalk/20 text-steel hover:text-chalk hover:border-steel transition-colors duration-200 cursor-pointer"
              aria-label={drawerOpen ? 'Close menu' : 'Open menu'}
              aria-expanded={drawerOpen}
            >
              {drawerOpen ? (
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <path d="M3 3l12 12M15 3L3 15" />
                </svg>
              ) : (
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <path d="M2 4h14M2 9h14M2 14h14" />
                </svg>
              )}
            </button>
          </div>
        </div>
      </header>

      <MobileDrawer open={drawerOpen} onClose={closeDrawer} />
    </>
  );
}
