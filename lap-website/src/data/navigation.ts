export interface NavLink {
  label: string;
  href: string;
  /** Optional audience hint for mobile drawer grouping */
  audience?: 'b2c' | 'b2b' | 'shared';
}

export const topNavLinks: NavLink[] = [
  { label: 'Product', href: '/product', audience: 'b2c' },
  { label: 'Pricing', href: '/pricing', audience: 'shared' },
  { label: 'For Venues', href: '/contact?plan=b2b', audience: 'b2b' },
  { label: 'Demo', href: '/demo', audience: 'b2c' },
  { label: 'Contact', href: '/contact', audience: 'shared' },
];

export const footerLinks: NavLink[] = [
  { label: 'Contact', href: '/contact' },
  { label: 'Book', href: '/book' },
  { label: 'Waitlist', href: '/waitlist' },
  { label: 'Billing', href: '/billing' },
  { label: 'Status', href: '/status' },
  { label: 'Privacy', href: '/privacy' },
  { label: 'Terms', href: '/terms' },
  { label: 'Security', href: '/security' },
  { label: 'DPA', href: '/dpa' },
  { label: 'Subprocessors', href: '/subprocessors' },
];
