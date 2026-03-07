import Link from 'next/link';

const legalLinks = [
  { label: 'Privacy', href: '/privacy' },
  { label: 'Terms', href: '/terms' },
  { label: 'Security', href: '/security' },
  { label: 'Status', href: '/status' },
];

export function AppFooter() {
  return (
    <footer className="mt-auto border-t border-steel/10 py-[var(--space-4)] px-6">
      <nav aria-label="Legal">
        <ul className="flex items-center gap-4">
          {legalLinks.map((link) => (
            <li key={link.href}>
              <Link href={link.href} className="font-telemetry text-[var(--text-caption)] text-steel hover:text-chalk transition-colors">
                {link.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </footer>
  );
}
