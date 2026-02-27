'use client';

import { type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { QueryProvider } from '@/providers/query-provider';

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
      { href: '/app/dev-plans', label: 'Coaching Plans', icon: '☰' },
      { href: '/app/analytics', label: 'Visualization', icon: '◆' },
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
    label: 'OPERATIONS',
    items: [
      { href: '/app/tracks', label: 'Tracks', icon: '◌' },
      { href: '/app/drivers', label: 'Drivers', icon: '◈' },
      { href: '/app/karts', label: 'Karts', icon: '⊞' },
      { href: '/app/weekends', label: 'Weekends', icon: '▣' },
      { href: '/app/exports', label: 'Exports', icon: '↓' },
      { href: '/app/data-health', label: 'Data Health', icon: '♡' },
    ],
  },
];

export default function AppLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="w-60 bg-concrete border-r border-steel/20 flex flex-col shrink-0">
        <div className="p-4 border-b border-steel/20">
          <Link href="/" className="font-monument text-2xl text-chalk tracking-tight">
            LAP
          </Link>
        </div>
        <nav className="flex-1 py-2 overflow-y-auto">
          {navGroups.map((group) => (
            <div key={group.label}>
              <p className="px-4 py-2 font-telemetry text-[10px] tracking-[0.12em] uppercase text-steel/60">{group.label}</p>
              {group.items.map((item) => {
                const isActive = pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                      isActive
                        ? 'text-acid-green bg-asphalt/50 border-r-2 border-acid-green'
                        : 'text-steel hover:text-chalk hover:bg-asphalt/30'
                    }`}
                  >
                    <span className="w-5 text-center font-telemetry">{item.icon}</span>
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
            className={`flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
              pathname.startsWith('/app/account')
                ? 'text-acid-green bg-asphalt/50 border-r-2 border-acid-green'
                : 'text-steel hover:text-chalk hover:bg-asphalt/30'
            }`}
          >
            <span className="w-5 text-center font-telemetry">{'\u25C9'}</span>
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
        <main className="flex-1 overflow-y-auto bg-asphalt">
          <div className="max-w-7xl mx-auto px-6 py-6">
            {children}
          </div>
        </main>
      </QueryProvider>
    </div>
  );
}
