import type { MetadataRoute } from 'next';
import { getSiteUrl } from '@/lib/site-url';
import { insightEntries } from '@/data/insights-cms';

const staticRoutes = [
  '',
  '/product',
  '/pricing',
  '/demo',
  '/book',
  '/contact',
  '/waitlist',
  '/drivers',
  '/circuits',
  '/teams',
  '/endurance',
  '/billing',
  '/security',
  '/status',
  '/privacy',
  '/terms',
  '/dpa',
  '/subprocessors',
  '/customers',
  '/insights',
  '/free-report/analyze',
];

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const siteUrl = getSiteUrl();

  const pages: MetadataRoute.Sitemap = staticRoutes.map((route) => ({
    url: `${siteUrl}${route}`,
    lastModified: now,
    changeFrequency: route === '' ? 'weekly' : 'monthly',
    priority: route === '' ? 1 : route === '/pricing' || route === '/product' ? 0.9 : 0.7,
  }));

  // Dynamic insight article pages
  for (const entry of insightEntries) {
    pages.push({
      url: `${siteUrl}/insights/${entry.slug}`,
      lastModified: now,
      changeFrequency: 'monthly',
      priority: 0.6,
    });
  }

  return pages;
}
