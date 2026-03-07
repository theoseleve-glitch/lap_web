'use client';

import { type ReactNode, useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { QueryProvider } from '@/providers/query-provider';
import { AppFooter } from '@/components/ui/AppFooter';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { DiagnosticsOverlay } from '@/components/dev/DiagnosticsOverlay';
import { BillingStateBanner } from '@/components/billing/BillingStateBanner';
import { OfflineBanner } from '@/components/shared/OfflineBanner';

const SIDEBAR_KEY = 'lap-sidebar-collapsed';

interface NavItem { href: string; label: string; icon: string; }
interface NavGroup { label: string; items: NavItem[]; }

const navGroups: NavGroup[] = [
  {
    label: 'COACH',
    items: [
      { href: '/app/dashboard', label: 'Dashboard', icon: '◉' },
      { href: '/app/sessions', label: 'Sessions', icon: '◎' },
      { href: '/app/compare', label: 'Compare', icon: '⟺' },
      { href: '/app/visualize', label: 'Visualization', icon: '◆' },
      { href: '/app/development', label: 'Dev Plans', icon: '◧' },
    ],
  },
  {
    label: 'STRATEGY',
    items: [
      { href: '/app/race-strategy', label: 'Race Strategy', icon: '⚑' },
      { href: '/app/leaderboard', label: 'Leaderboard', icon: '★' },
    ],
  },
  {
    label: 'COACHING',
    items: [
      { href: '/app/analytics', label: 'Analytics Hub', icon: '◇' },
      { href: '/app/exports', label: 'Exports', icon: '↓' },
      { href: '/app/tracks', label: 'Tracks', icon: '◌' },
      { href: '/app/drivers', label: 'Drivers', icon: '◈' },
      { href: '/app/karts', label: 'Karts', icon: '⊞' },
      { href: '/app/weekends', label: 'Weekends', icon: '▣' },
    ],
  },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(SIDEBAR_KEY);
    if (stored === '1') setCollapsed(true);
  }, []);

  const toggle = () => {
    setCollapsed((prev) => {
      localStorage.setItem(SIDEBAR_KEY, prev ? '0' : '1');
      return !prev;
    });
  };

  return (
    <div className="flex min-h-screen">
      {/* Skip to content — visible on focus for keyboard users */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:px-4 focus:py-2 focus:bg-gold focus:text-carbon focus:font-telemetry focus:text-sm focus:rounded"
      >
        Skip to content
      </a>

      {/* Sidebar */}
      <aside
        className={`${collapsed ? 'w-14' : 'w-60'} bg-concrete border-r border-steel/20 flex flex-col shrink-0 overflow-hidden transition-all duration-300`}
      >
        <div className="p-4 border-b border-steel/20 flex items-center justify-between gap-2">
          {!collapsed && (
            <Link href="/" className="font-monument text-2xl text-chalk tracking-tight">
              LAP
            </Link>
          )}
          <button
            onClick={toggle}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="text-steel hover:text-chalk transition-colors text-lg shrink-0"
          >
            {collapsed ? '▸' : '◂'}
          </button>
        </div>
        <nav aria-label="Main navigation" className="flex-1 py-2 overflow-y-auto">
          {navGroups.map((group) => (
            <div key={group.label} role="group" aria-label={group.label}>
              {!collapsed && (
                <p className="px-4 py-2 font-telemetry text-[10px] tracking-[0.12em] uppercase text-steel/60">{group.label}</p>
              )}
              {group.items.map((item) => {
                const isActive = pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    title={collapsed ? item.label : undefined}
                    aria-current={isActive ? 'page' : undefined}
                    className={`flex items-center ${collapsed ? 'justify-center px-2' : 'gap-3 px-4'} py-2.5 text-sm transition-colors ${
                      isActive
                        ? 'text-acid-green bg-asphalt/50 border-r-2 border-acid-green'
                        : 'text-steel hover:text-chalk hover:bg-asphalt/30'
                    }`}
                  >
                    <span className="w-5 text-center font-telemetry shrink-0" aria-hidden="true">{item.icon}</span>
                    {!collapsed && <span className="font-body whitespace-nowrap">{item.label}</span>}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="border-t border-steel/10 py-2">
          <Link
            href="/help"
            title={collapsed ? 'Help' : undefined}
            className={`flex items-center ${collapsed ? 'justify-center px-2' : 'gap-3 px-4'} py-2.5 text-sm transition-colors text-steel hover:text-chalk hover:bg-asphalt/30`}
          >
            <span className="w-5 text-center font-telemetry shrink-0" aria-hidden="true">?</span>
            {!collapsed && <span className="font-body">Help</span>}
          </Link>
          <Link
            href="/changelog"
            title={collapsed ? 'Changelog' : undefined}
            className={`flex items-center ${collapsed ? 'justify-center px-2' : 'gap-3 px-4'} py-2.5 text-sm transition-colors text-steel hover:text-chalk hover:bg-asphalt/30`}
          >
            <span className="w-5 text-center font-telemetry shrink-0" aria-hidden="true">{'\u2261'}</span>
            {!collapsed && <span className="font-body">Changelog</span>}
          </Link>
          <Link
            href="/app/account"
            title={collapsed ? 'Account' : undefined}
            aria-current={pathname.startsWith('/app/account') ? 'page' : undefined}
            className={`flex items-center ${collapsed ? 'justify-center px-2' : 'gap-3 px-4'} py-2.5 text-sm transition-colors ${
              pathname.startsWith('/app/account')
                ? 'text-acid-green bg-asphalt/50 border-r-2 border-acid-green'
                : 'text-steel hover:text-chalk hover:bg-asphalt/30'
            }`}
          >
            <span className="w-5 text-center font-telemetry shrink-0" aria-hidden="true">{'\u25C9'}</span>
            {!collapsed && <span className="font-body">Account</span>}
          </Link>
        </div>
      </aside>

      {/* Main content */}
      <QueryProvider>
        <AuthGuard>
          <main id="main-content" className="flex-1 flex flex-col overflow-y-auto bg-asphalt">
            <OfflineBanner />
            <div className="max-w-7xl mx-auto px-6 py-6">
              <BillingStateBanner />
              {children}
            </div>
            <AppFooter />
          </main>
        </AuthGuard>
        {process.env.NODE_ENV === 'development' && <DiagnosticsOverlay />}
      </QueryProvider>
    </div>
  );
}
