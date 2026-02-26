import type { MetadataRoute } from 'next';

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
  return routes.map((route) => ({
    url: `https://lap.racing${route}`,
    lastModified: now,
    changeFrequency: route === '' ? 'weekly' : 'monthly',
    priority: route === '' ? 1 : 0.7,
  }));
}
