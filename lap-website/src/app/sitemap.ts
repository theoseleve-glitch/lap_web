import type { MetadataRoute } from 'next';
import { getSiteUrl } from '@/lib/site-url';
import { insightEntries } from '@/data/insights-cms';
import { routeMap } from '@/data/route-map';
import { collectMarketingSitemapRoutes } from '@/lib/sitemap-routes.mjs';

const extraRoutes: string[] = [];

function getRoutePriority(route: string): number {
  if (route === '') return 1;
  const segments = route.split('/').filter(Boolean).length;
  if (segments === 1) return 0.8;
  return 0.6;
}

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const siteUrl = getSiteUrl();

  const marketingRoutes = collectMarketingSitemapRoutes();
  const discovered = marketingRoutes.map((r: string) => (r === '/' ? '' : r));
  const allRoutes = ['', ...discovered.filter((r: string) => r !== ''), ...extraRoutes]
    .filter((route) => {
      const entry = routeMap[route || '/'];
      return !entry?.noIndex;
    });

  const pages: MetadataRoute.Sitemap = allRoutes.map((route) => ({
    url: `${siteUrl}${route}`,
    lastModified: now,
    changeFrequency: route === '' ? ('weekly' as const) : ('monthly' as const),
    priority: getRoutePriority(route),
  }));

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
