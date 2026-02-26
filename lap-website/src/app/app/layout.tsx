'use client';

import { type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { QueryProvider } from '@/providers/query-provider';

const navItems = [
  { href: '/app/dashboard', label: 'Dashboard', icon: '◉' },
  { href: '/app/sessions', label: 'Sessions', icon: '◎' },
  { href: '/app/tracks', label: 'Tracks', icon: '◌' },
  { href: '/app/drivers', label: 'Drivers', icon: '◈' },
  { href: '/app/analyze', label: 'Analyze', icon: '▲' },
  { href: '/app/compare', label: 'Compare', icon: '⟺' },
  { href: '/app/race-strategy', label: 'Strategy', icon: '⚑' },
  { href: '/app/leaderboard', label: 'Leaderboard', icon: '★' },
  { href: '/app/analytics', label: 'Analytics', icon: '◆' },
  { href: '/app/karts', label: 'Karts', icon: '⊞' },
  { href: '/app/weekends', label: 'Weekends', icon: '▣' },
  { href: '/app/annotations', label: 'Annotations', icon: '✎' },
  { href: '/app/dev-plans', label: 'Dev Plans', icon: '☰' },
  { href: '/app/exports', label: 'Exports', icon: '↓' },
  { href: '/app/data-health', label: 'Data Health', icon: '♡' },
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
          {navItems.map((item) => {
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
        </nav>
        <div className="p-4 border-t border-steel/20">
          <Link
            href="/"
            className="text-xs text-steel hover:text-chalk transition-colors font-telemetry"
          >
            ← Back to lap.racing
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
