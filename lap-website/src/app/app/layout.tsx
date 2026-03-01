'use client';

import { type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { QueryProvider } from '@/providers/query-provider';
import { AuthGuard } from '@/components/auth/AuthGuard';

interface NavItem { href: string; label: string; icon: string; }
interface NavGroup { label: string; items: NavItem[]; }

const navGroups: NavGroup[] = [
  {
    label: 'ENGINEER',
    items: [
      { href: '/app/dashboard', label: 'Dashboard', icon: '◉' },
      { href: '/app/sessions', label: 'Sessions', icon: '◎' },
      { href: '/app/analyze', label: 'Analyze', icon: '▲' },
      { href: '/app/compare', label: 'Compare', icon: '⟺' },
      { href: '/app/visualize', label: 'Visualization', icon: '◆' },
    ],
  },
  {
    label: 'STRATEGIST',
    items: [
      { href: '/app/race-strategy', label: 'Race Strategy', icon: '⚑' },
      { href: '/app/leaderboard', label: 'Leaderboard', icon: '★' },
    ],
  },
  {
    label: 'TOOLS & ANALYTICS',
    items: [
      { href: '/app/analytics', label: 'Analytics Hub', icon: '◇' },
      { href: '/app/exports', label: 'Exports', icon: '↓' },
    ],
  },
  {
    label: 'OPERATIONS',
    items: [
      { href: '/app/tracks', label: 'Tracks', icon: '◌' },
      { href: '/app/drivers', label: 'Drivers', icon: '◈' },
      { href: '/app/karts', label: 'Karts', icon: '⊞' },
      { href: '/app/weekends', label: 'Weekends', icon: '▣' },
    ],
  },
];

export default function AppLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen">
      {/* Skip to content — visible on focus for keyboard users */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:px-4 focus:py-2 focus:bg-acid-green focus:text-carbon focus:font-telemetry focus:text-sm focus:rounded"
      >
        Skip to content
      </a>

      {/* Sidebar */}
      <aside className="w-60 bg-concrete border-r border-steel/20 flex flex-col shrink-0">
        <div className="p-4 border-b border-steel/20">
          <Link href="/" className="font-monument text-2xl text-chalk tracking-tight">
            LAP
          </Link>
        </div>
        <nav aria-label="Main navigation" className="flex-1 py-2 overflow-y-auto">
          {navGroups.map((group) => (
            <div key={group.label} role="group" aria-label={group.label}>
              <p className="px-4 py-2 font-telemetry text-[10px] tracking-[0.12em] uppercase text-steel/60">{group.label}</p>
              {group.items.map((item) => {
                const isActive = pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={isActive ? 'page' : undefined}
                    className={`flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                      isActive
                        ? 'text-acid-green bg-asphalt/50 border-r-2 border-acid-green'
                        : 'text-steel hover:text-chalk hover:bg-asphalt/30'
                    }`}
                  >
                    <span className="w-5 text-center font-telemetry" aria-hidden="true">{item.icon}</span>
                    <span className="font-body">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="border-t border-steel/10 py-2">
          <Link
            href="/app/account"
            aria-current={pathname.startsWith('/app/account') ? 'page' : undefined}
            className={`flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
              pathname.startsWith('/app/account')
                ? 'text-acid-green bg-asphalt/50 border-r-2 border-acid-green'
                : 'text-steel hover:text-chalk hover:bg-asphalt/30'
            }`}
          >
            <span className="w-5 text-center font-telemetry" aria-hidden="true">{'\u25C9'}</span>
            <span className="font-body">Account</span>
          </Link>
        </div>
        <div className="p-4 border-t border-steel/20">
          <Link
            href="/"
            className="text-xs text-steel hover:text-chalk transition-colors font-telemetry"
          >
            &larr; Back to lap-coach.racing
          </Link>
        </div>
      </aside>

      {/* Main content */}
      <QueryProvider>
        <AuthGuard>
          <main id="main-content" className="flex-1 overflow-y-auto bg-asphalt">
            <div className="max-w-7xl mx-auto px-6 py-6">
              {children}
            </div>
          </main>
        </AuthGuard>
      </QueryProvider>
    </div>
  );
}
