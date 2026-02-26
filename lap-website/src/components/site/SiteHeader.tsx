'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { topNavLinks } from '@/data/navigation';
import { trackNavRouteClick } from '@/lib/analytics';
import { LocaleSwitcher } from '@/components/site/LocaleSwitcher';

interface SiteHeaderProps {
  showIndexToggle?: boolean;
  onIndexToggle?: () => void;
}

export function SiteHeader({ showIndexToggle = false, onIndexToggle }: SiteHeaderProps) {
  const pathname = usePathname();
  const [persona, setPersona] = useState('drivers');

  useEffect(() => {
    const cookie = document.cookie
      .split(';')
      .map((part) => part.trim())
      .find((part) => part.startsWith('lap_persona='));
    if (!cookie) return;
    const value = cookie.split('=').slice(1).join('=');
    if (value) setPersona(value);
  }, []);

  const personaCta =
    persona === 'circuits' || persona === 'teams' || persona === 'endurance'
      ? { label: 'Book B2B Demo', href: '/demo?audience=b2b' }
      : { label: 'Start Free Report', href: '/register?source=header-demo' };

  return (
    <header className="sticky top-0 z-50 border-b border-steel/20 bg-asphalt/95 backdrop-blur">
      <div className="mx-auto max-w-6xl px-4 py-3 flex flex-wrap items-center justify-between gap-3">
        <Link
          href="/"
          className="group relative font-monument text-3xl border-2 border-chalk/70 px-3.5 py-1.5 leading-none tracking-tight"
          style={{
            textShadow: '0 0 20px rgba(243,240,232,0.2), 0 0 36px rgba(255,106,0,0.18)',
            boxShadow: 'inset 0 0 0 1px rgba(243,240,232,0.15), 0 0 0 1px rgba(255,106,0,0.16)',
            transform: 'rotate(-0.7deg)',
          }}
          onClick={() => trackNavRouteClick('/', 'header')}
        >
          <span className="text-chalk group-hover:text-pit-orange transition-colors duration-[420ms]">LAP</span>
        </Link>

        <nav aria-label="Primary" className="flex flex-wrap items-center gap-2">
          {showIndexToggle && onIndexToggle && (
            <button
              type="button"
              className="px-3 py-1 border border-steel/40 text-xs font-telemetry tracking-[0.12em] uppercase text-steel hover:text-chalk hover:border-pit-orange transition-colors duration-[420ms]"
              onClick={onIndexToggle}
              aria-label="Open section index"
            >
              Index
            </button>
          )}
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
          <Link
            href={personaCta.href}
            className="px-3 py-1 border border-pit-orange text-xs font-telemetry tracking-[0.12em] uppercase text-chalk hover:bg-pit-orange hover:text-asphalt transition-colors duration-[420ms]"
            onClick={() => trackNavRouteClick(personaCta.href, 'header_persona_cta')}
          >
            {personaCta.label}
          </Link>
          <LocaleSwitcher />
        </nav>
      </div>
    </header>
  );
}
