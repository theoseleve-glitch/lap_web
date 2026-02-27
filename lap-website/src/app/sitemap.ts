import type { MetadataRoute } from 'next';

import { collectMarketingSitemapRoutes } from '@/lib/sitemap-routes.mjs';

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const routes = collectMarketingSitemapRoutes();

  return routes.map((route) => ({
    url: `https://lap.racing${route === '/' ? '' : route}`,
    lastModified: now,
    changeFrequency: route === '/' ? 'weekly' : 'monthly',
    priority: route === '/' ? 1 : 0.7,
  }));
}
