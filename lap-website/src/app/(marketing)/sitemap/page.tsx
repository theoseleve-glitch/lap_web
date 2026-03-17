import Link from 'next/link';
import { PageIntro } from '@/components/ui/PageIntro';
import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/sitemap');

interface SitemapSection {
  heading: string;
  links: { href: string; label: string }[];
}

const sections: SitemapSection[] = [
  {
    heading: 'Product',
    links: [
      { href: '/', label: 'Home' },
      { href: '/product', label: 'Product overview' },
      { href: '/pricing', label: 'Plans & pricing' },
      { href: '/billing', label: 'Billing' },
      { href: '/demo', label: 'Request a demo' },
      { href: '/register?source=sitemap', label: 'Try free analysis' },
      { href: '/compare-tools', label: 'LAP vs Spreadsheets' },
    ],
  },
  {
    heading: 'Use Cases',
    links: [
      { href: '/teams', label: 'For racing teams' },
      { href: '/circuits', label: 'For circuits & venues' },
      { href: '/coaches', label: 'For coaches' },
    ],
  },
  {
    heading: 'Resources',
    links: [
      { href: '/insights', label: 'Insights & guides' },
      { href: '/customers', label: 'Customer stories' },
      { href: '/changelog', label: 'Changelog' },
      { href: '/help', label: 'Help center' },
      { href: '/status', label: 'System status' },
    ],
  },
  {
    heading: 'Company',
    links: [
      { href: '/contact', label: 'Contact us' },
      { href: '/book', label: 'Book a call' },
      { href: '/waitlist', label: 'Join the waitlist' },
      { href: '/security', label: 'Security' },
    ],
  },
  {
    heading: 'Legal',
    links: [
      { href: '/terms', label: 'Terms of service' },
      { href: '/privacy', label: 'Privacy policy' },
      { href: '/dpa', label: 'Data processing agreement' },
      { href: '/subprocessors', label: 'Sub-processors' },
      { href: '/accessibility', label: 'Accessibility statement' },
    ],
  },
  {
    heading: 'Account',
    links: [
      { href: '/login', label: 'Sign in' },
      { href: '/register', label: 'Create an account' },
    ],
  },
];

export default function SitemapPage() {
  return (
    <main className="mx-auto max-w-4xl px-4 py-10 md:py-14">
      <PageIntro title="Sitemap" />
      <div className="mx-auto max-w-3xl">

        <div className="grid gap-10 sm:grid-cols-2">
          {sections.map((section) => (
            <section key={section.heading}>
              <h2 className="font-telemetry text-xs uppercase tracking-wider text-chalk/60 mb-3">
                {section.heading}
              </h2>
              <ul className="space-y-2">
                {section.links.map(({ href, label }) => (
                  <li key={href}>
                    <Link
                      href={href}
                      className="text-acid-green font-body text-sm hover:underline"
                    >
                      {label}
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </main>
  );
}
