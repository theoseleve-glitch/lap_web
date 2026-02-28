import type { MetadataRoute } from 'next';
import { getSiteUrl } from '@/lib/site-url';
import { insightEntries } from '@/data/insights-cms';
import { collectMarketingSitemapRoutes } from '@/lib/sitemap-routes.mjs';

// Routes outside (marketing)/ that should still appear in the sitemap
const extraRoutes = ['/free-report/analyze'];

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  const siteUrl = getSiteUrl();

  // Dynamic marketing routes discovered from filesystem
  const marketingRoutes = collectMarketingSitemapRoutes();
  const allRoutes = [...marketingRoutes.map((r: string) => (r === '/' ? '' : r)), ...extraRoutes];

  const pages: MetadataRoute.Sitemap = allRoutes.map((route) => ({
    url: `${siteUrl}${route}`,
    lastModified: now,
    changeFrequency: route === '' ? ('weekly' as const) : ('monthly' as const),
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
