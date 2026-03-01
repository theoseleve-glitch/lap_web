'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { type ReactNode } from 'react';

const navGroups = [
  {
    label: 'OVERVIEW',
    items: [
      { href: '/app/race-control', label: 'Health', icon: '\u25C9' },
    ],
  },
  {
    label: 'OPERATIONS',
    items: [
      { href: '/app/race-control/users', label: 'Users', icon: '\u25C8' },
      { href: '/app/race-control/jobs', label: 'Jobs', icon: '\u25CE' },
      { href: '/app/race-control/entitlements', label: 'Entitlements', icon: '\u2630' },
    ],
  },
  {
    label: 'REVENUE',
    items: [
      { href: '/app/race-control/billing', label: 'Billing', icon: '\u2605' },
      { href: '/app/race-control/billing/webhooks', label: 'Webhooks', icon: '\u2193' },
      { href: '/app/race-control/billing/reconciliation', label: 'Reconciliation', icon: '\u27FA' },
    ],
  },
  {
    label: 'COMMUNICATIONS',
    items: [
      { href: '/app/race-control/email', label: 'Email', icon: '\u25A3' },
    ],
  },
  {
    label: 'SECURITY',
    items: [
      { href: '/app/race-control/security', label: 'Events', icon: '\u229E' },
      { href: '/app/race-control/security/audit-log', label: 'Audit Log', icon: '\u2661' },
      { href: '/app/race-control/incidents', label: 'Incidents', icon: '\u2691' },
    ],
  },
  {
    label: 'INFRASTRUCTURE',
    items: [
      { href: '/app/race-control/infra', label: 'Servers & Storage', icon: '\u25B2' },
    ],
  },
  {
    label: 'MONITORING',
    items: [
      { href: '/app/race-control/monitoring/training', label: 'Training', icon: '\u2699' },
      { href: '/app/race-control/monitoring/resources', label: 'User Resources', icon: '\u25A4' },
    ],
  },
];

export default function RaceControlLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="-mx-6 -my-6 flex min-h-[calc(100vh-0px)]">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 border-r border-red-500/20 bg-concrete p-4 overflow-y-auto">
        <div className="mb-6">
          <span className="text-xs font-bold tracking-widest text-red-400">
            RACE CONTROL
          </span>
        </div>

        <nav aria-label="Race Control navigation">
          {navGroups.map((group) => (
            <div key={group.label} className="mb-4">
              <p className="mb-1 px-3 text-[10px] font-semibold tracking-widest text-steel/60">
                {group.label}
              </p>
              {group.items.map((item) => {
                const isActive =
                  item.href === '/app/race-control'
                    ? pathname === '/app/race-control'
                    : pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors ${
                      isActive
                        ? 'bg-red-500/10 text-red-400'
                        : 'text-chalk/50 hover:bg-white/5 hover:text-chalk/80'
                    }`}
                  >
                    <span className="text-xs" aria-hidden="true">{item.icon}</span>
                    {item.label}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto p-6">
        {children}
      </main>
    </div>
  );
}
