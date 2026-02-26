export interface NavLink {
  label: string;
  href: string;
}

export const topNavLinks: NavLink[] = [
  { label: 'Product', href: '/product' },
  { label: 'Pricing', href: '/pricing' },
  { label: 'Drivers', href: '/drivers' },
  { label: 'Circuits', href: '/circuits' },
  { label: 'Teams', href: '/teams' },
  { label: 'Endurance', href: '/endurance' },
  { label: 'Customers', href: '/customers' },
  { label: 'Security', href: '/security' },
  { label: 'Insights', href: '/insights' },
];

export const footerLinks: NavLink[] = [
  { label: 'Contact', href: '/contact' },
  { label: 'Book', href: '/book' },
  { label: 'Waitlist', href: '/waitlist' },
  { label: 'Billing', href: '/billing' },
  { label: 'Status', href: '/status' },
  { label: 'Privacy', href: '/privacy' },
  { label: 'Terms', href: '/terms' },
  { label: 'DPA', href: '/dpa' },
];
