import type { Metadata } from 'next';
import { routeMap } from '@/data/route-map';
import { getSiteUrl } from '@/lib/site-url';

const OG_WORKER_ORIGIN = 'https://og.lap-coach.racing';

export interface SeoOverrides {
  title?: string;
  metaDescription?: string;
  ogTitle?: string;
  ogDescription?: string;
  noIndex?: boolean;
  canonical?: string;
}

function buildOgImageUrl(title: string, eyebrow?: string): string {
  const params = new URLSearchParams({ title });
  if (eyebrow) params.set('eyebrow', eyebrow);
  return `${OG_WORKER_ORIGIN}/og?${params.toString()}`;
}

export function generateSeoMetadata(
  pathname: string,
  overrides?: SeoOverrides,
): Metadata {
  const entry = routeMap[pathname];
  if (!entry && !overrides) return {};

  const siteUrl = getSiteUrl();
  const title = overrides?.title ?? entry?.title;
  const description = overrides?.metaDescription ?? entry?.metaDescription;
  const ogTitle = overrides?.ogTitle ?? entry?.ogTitle ?? title;
  const ogDescription = overrides?.ogDescription ?? entry?.ogDescription ?? description;
  const noIndex = overrides?.noIndex ?? entry?.noIndex ?? false;
  const canonical = overrides?.canonical ?? entry?.canonical ?? `${siteUrl}${pathname}`;
  const eyebrow = entry?.eyebrow;

  const meta: Metadata = {};

  if (title) meta.title = title;
  if (description) meta.description = description;

  if (ogTitle && ogDescription) {
    meta.openGraph = {
      title: ogTitle,
      description: ogDescription,
      url: `${siteUrl}${pathname}`,
      images: [buildOgImageUrl(ogTitle, eyebrow)],
    };
    meta.twitter = {
      card: 'summary_large_image',
      title: ogTitle,
      description: ogDescription,
    };
  }

  meta.alternates = { canonical };

  if (noIndex) {
    meta.robots = { index: false, follow: false };
  }

  return meta;
}
