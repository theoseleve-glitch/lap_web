import type { MetadataRoute } from 'next';
import { getSiteUrl } from '@/lib/site-url';

const routes = [
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
  '/customers',
  '/insights',
];

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const siteUrl = getSiteUrl();
  return routes.map((route) => ({
    url: `${siteUrl}${route}`,
    lastModified: now,
    changeFrequency: route === '' ? 'weekly' : 'monthly',
    priority: route === '' ? 1 : 0.7,
  }));
}
