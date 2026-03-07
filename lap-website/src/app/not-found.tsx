import Link from 'next/link';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Page Not Found',
  robots: { index: false, follow: true },
};

const recoveryLinks = [
  { href: '/', label: 'Home' },
  { href: '/product', label: 'Product overview' },
  { href: '/pricing', label: 'Plans & pricing' },
  { href: '/insights', label: 'Insights & guides' },
  { href: '/free-report/analyze', label: 'Free telemetry report' },
  { href: '/contact', label: 'Contact support' },
  { href: '/sitemap', label: 'Full sitemap' },
];

export default function NotFound() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-asphalt px-4">
      <div className="max-w-md w-full text-center">
        <h1 className="font-monument text-6xl text-chalk mb-2">404</h1>
        <p className="text-steel font-body mb-8">
          The page you requested could not be found.
        </p>

        <nav aria-label="Recovery navigation">
          <h2 className="text-chalk/60 font-telemetry text-xs uppercase tracking-wider mb-4">
            Try one of these pages
          </h2>
          <ul className="space-y-2">
            {recoveryLinks.map(({ href, label }) => (
              <li key={href}>
                <Link
                  href={href}
                  className="text-acid-green font-telemetry text-sm hover:underline"
                >
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </div>
  );
}
