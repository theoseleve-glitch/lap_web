'use client';

import { useEffect, useRef } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { topNavLinks } from '@/data/navigation';
import { trackNavRouteClick } from '@/lib/analytics';
import { LapMonogram } from '@/components/shared/LapMonogram';
import { useTranslation } from '@/i18n';

const navLabelKey: Record<string, string> = {
  Product: 'nav.product',
  Pricing: 'nav.pricing',
  Demo: 'nav.demo',
  Contact: 'nav.contact',
};

interface MobileDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function MobileDrawer({ open, onClose }: MobileDrawerProps) {
  const pathname = usePathname();
  const { t } = useTranslation();
  const drawerRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  // Focus trap + escape key
  useEffect(() => {
    if (!open) return;

    previousFocusRef.current = document.activeElement as HTMLElement;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      if (e.key !== 'Tab' || !drawerRef.current) return;

      const focusable = drawerRef.current.querySelectorAll<HTMLElement>(
        'a, button, [tabindex]:not([tabindex="-1"])'
      );
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    // Focus the first link after a tick
    requestAnimationFrame(() => {
      const first = drawerRef.current?.querySelector<HTMLElement>('a, button');
      first?.focus();
    });

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      previousFocusRef.current?.focus();
    };
  }, [open, onClose]);

  // Close on route change
  useEffect(() => {
    onClose();
  }, [pathname, onClose]);

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-[99] bg-asphalt/80 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer */}
      <div
        ref={drawerRef}
        role="dialog"
        aria-modal="true"
        aria-label="Navigation menu"
        className="fixed inset-y-0 right-0 z-[100] w-full max-w-sm bg-concrete border-l border-chalk/10 flex flex-col"
      >
        {/* Close button */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-chalk/10">
          <span className="flex items-center gap-2">
            <LapMonogram size={24} color="currentColor" className="text-chalk" />
            <span className="font-monument text-xl text-chalk">LAP</span>
          </span>
          <button
            type="button"
            onClick={onClose}
            className="min-h-[44px] min-w-[44px] flex items-center justify-center text-steel hover:text-chalk transition-colors cursor-pointer"
            aria-label="Close menu"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M4 4l12 12M16 4L4 16" />
            </svg>
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto px-6 py-6" aria-label="Mobile navigation">
          <ul className="space-y-1">
            {topNavLinks.map((link) => {
              const active = pathname === link.href;
              return (
                <li key={link.href + link.label}>
                  <Link
                    href={link.href}
                    className={`flex items-center min-h-[44px] px-3 font-body text-base transition-colors cursor-pointer ${
                      active
                        ? 'text-chalk border-l-2 border-pit-orange bg-asphalt/50'
                        : 'text-steel hover:text-chalk'
                    }`}
                    onClick={() => trackNavRouteClick(link.href, 'mobile-drawer')}
                  >
                    {t(navLabelKey[link.label] ?? '', link.label)}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* Auth section */}
        <div className="px-6 py-4 border-t border-chalk/10 space-y-2">
          <Link
            href="/register?source=mobile-nav"
            className="flex items-center justify-center min-h-[44px] w-full font-telemetry text-xs tracking-[0.12em] uppercase bg-pit-orange border border-pit-orange text-white hover:bg-[#D4B35A] transition-colors cursor-pointer"
            onClick={() => trackNavRouteClick('/register', 'mobile-drawer')}
          >
            {t('cta.startFreeReport')}
          </Link>
          <Link
            href="/login"
            className="flex items-center justify-center min-h-[44px] w-full font-telemetry text-xs tracking-[0.12em] uppercase border border-chalk/30 text-chalk hover:border-chalk transition-colors cursor-pointer"
            onClick={() => trackNavRouteClick('/login', 'mobile-drawer')}
          >
            {t('nav.login')}
          </Link>
        </div>
      </div>
    </>
  );
}
