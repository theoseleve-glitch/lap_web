'use client';

import { type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

const accountNav = [
  { href: '/app/account/profile', label: 'Profile', icon: '\u25C9' },
  { href: '/app/account/security', label: 'Security', icon: '\u25C8' },
  { href: '/app/account/billing', label: 'Plan & Billing', icon: '\u25C6' },
  { href: '/app/account/usage', label: 'Usage & Limits', icon: '\u25C7' },
  { href: '/app/account/data', label: 'Data & Privacy', icon: '\u25CE' },
  { href: '/app/account/support', label: 'Support', icon: '\u25CC' },
];

export default function AccountLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-full -mx-6 -my-6">
      {/* Account sidebar */}
      <aside className="w-56 bg-concrete border-r border-steel/10 flex flex-col shrink-0">
        <div className="p-4">
          <Link
            href="/app/dashboard"
            className="text-xs text-steel hover:text-chalk transition-colors font-telemetry"
          >
            &larr; Back to Dashboard
          </Link>
          <h2 className="font-monument text-xl text-chalk mt-3 tracking-tight">Account</h2>
        </div>
        <nav className="flex-1 py-1">
          {accountNav.map((item) => {
            const isActive =
              pathname === item.href || pathname.startsWith(item.href + '/');
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                  isActive
                    ? 'text-acid-green bg-acid-green/10'
                    : 'text-steel hover:bg-chalk/5 hover:text-chalk'
                }`}
              >
                <span className="w-5 text-center font-telemetry">{item.icon}</span>
                <span className="font-body">{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </aside>

      {/* Main content area */}
      <div className="flex-1 p-6 lg:p-8">
        <div className="max-w-3xl mx-auto">{children}</div>
      </div>
    </div>
  );
}
