import { buildBreadcrumbs } from '@/data/route-map';
import { getSiteUrl } from '@/lib/site-url';

interface Props {
  pathname: string;
}

export function BreadcrumbJsonLd({ pathname }: Props) {
  const crumbs = buildBreadcrumbs(pathname);
  if (crumbs.length === 0) return null;

  const siteUrl = getSiteUrl();
  const items = [
    ...crumbs.map((c, i) => ({
      '@type': 'ListItem' as const,
      position: i + 1,
      name: c.label,
      item: `${siteUrl}${c.href}`,
    })),
    {
      '@type': 'ListItem' as const,
      position: crumbs.length + 1,
      name: pathname.split('/').pop() || 'Page',
      item: `${siteUrl}${pathname}`,
    },
  ];

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items,
  };

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
    />
  );
}
