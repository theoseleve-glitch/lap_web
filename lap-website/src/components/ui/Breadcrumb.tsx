'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { buildBreadcrumbs, routeMap } from '@/data/route-map';

export function Breadcrumb() {
  const pathname = usePathname();
  const crumbs = buildBreadcrumbs(pathname);
  if (crumbs.length === 0) return null;
  const current = routeMap[pathname];

  return (
    <nav aria-label="Breadcrumb" className="mb-[var(--space-1)]">
      <ol className="flex items-center gap-1.5 font-telemetry text-[var(--text-caption)] text-steel">
        {crumbs.map((crumb) => (
          <li key={crumb.href} className="flex items-center gap-1.5">
            <Link href={crumb.href} className="hover:text-chalk transition-colors">{crumb.label}</Link>
            <span aria-hidden="true" className="text-steel/40">&rsaquo;</span>
          </li>
        ))}
        {current && <li aria-current="page" className="text-chalk">{current.title}</li>}
      </ol>
    </nav>
  );
}
