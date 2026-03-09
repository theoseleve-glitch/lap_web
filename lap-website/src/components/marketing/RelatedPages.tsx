'use client';

import Link from 'next/link';

interface RelatedLink {
  href: string;
  label: string;
  description: string;
}

const PAGE_LINKS: Record<string, RelatedLink[]> = {
  '/product': [
    { href: '/pricing', label: 'Pricing', description: 'Choose the right plan for your racing programme' },
    { href: '/demo', label: 'Demo', description: 'See LAP in action with interactive demos' },
    { href: '/customers', label: 'Customers', description: 'Read how teams use LAP in competition' },
  ],
  '/pricing': [
    { href: '/product', label: 'Product', description: 'Explore the full platform capabilities' },
    { href: '/demo', label: 'Try Demo', description: 'Upload a session and see your coaching report' },
    { href: '/help', label: 'Help Center', description: 'Get answers to common questions' },
  ],
  '/customers': [
    { href: '/product', label: 'Product', description: 'Explore the analysis and coaching features' },
    { href: '/pricing', label: 'Pricing', description: 'Plans for individual drivers and teams' },
    { href: '/book', label: 'Book a Call', description: 'Discuss your telemetry requirements' },
  ],
  '/help': [
    { href: '/product', label: 'Product', description: 'Full feature overview of the platform' },
    { href: '/security', label: 'Security', description: 'How we protect your racing data' },
    { href: '/contact', label: 'Contact', description: 'Get in touch with our support team' },
  ],
  '/security': [
    { href: '/privacy', label: 'Privacy Policy', description: 'How we handle your personal data' },
    { href: '/dpa', label: 'DPA', description: 'Data processing agreement for teams' },
    { href: '/subprocessors', label: 'Sub-processors', description: 'Third-party services we use' },
  ],
  '/changelog': [
    { href: '/product', label: 'Product', description: 'Full feature overview' },
    { href: '/pricing', label: 'Pricing', description: 'Choose your plan' },
    { href: '/help', label: 'Help', description: 'Getting started guides' },
  ],
};

interface RelatedPagesProps {
  pathname: string;
}

export function RelatedPages({ pathname }: RelatedPagesProps) {
  const links = PAGE_LINKS[pathname];
  if (!links) return null;

  return (
    <nav className="border-t border-steel/10 pt-8 mt-10" aria-label="Related pages">
      <h2 className="font-monument text-xs tracking-[0.12em] uppercase text-steel mb-4">Related</h2>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {links.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className="block p-4 border border-steel/15 hover:border-steel/30 bg-concrete/20 transition-colors group"
          >
            <span className="font-monument text-sm text-chalk group-hover:text-pit-orange transition-colors">{link.label}</span>
            <p className="text-steel text-xs font-body mt-1">{link.description}</p>
          </Link>
        ))}
      </div>
    </nav>
  );
}
