export interface NavLink {
  label: string;
  href: string;
  /** Optional audience hint for mobile drawer grouping */
  audience?: 'b2c' | 'b2b' | 'shared';
}

export const topNavLinks: NavLink[] = [
  { label: 'Product', href: '/product', audience: 'b2c' },
  { label: 'Pricing', href: '/pricing', audience: 'shared' },
  { label: 'Demo', href: '/demo', audience: 'b2c' },
  { label: 'Logger', href: '/product/logger', audience: 'b2c' },
  { label: 'Contact', href: '/contact', audience: 'shared' },
];

export const footerLinks: NavLink[] = [
  { label: 'Contact', href: '/contact' },
  { label: 'Demo', href: '/demo' },
  { label: 'Help', href: '/help' },
  { label: 'Changelog', href: '/changelog' },
  { label: 'Status', href: '/status' },
  { label: 'Privacy', href: '/privacy' },
  { label: 'Terms', href: '/terms' },
  { label: 'Security', href: '/security' },
  { label: 'For Venues & Teams', href: '/venues', audience: 'b2b' },
];
