import { afterEach, describe, expect, it, vi } from 'vitest';

const originalSiteUrl = process.env.SITE_URL;

async function loadSitemapWithSiteUrl(siteUrl?: string) {
  vi.resetModules();

  if (siteUrl === undefined) {
    delete process.env.SITE_URL;
  } else {
    process.env.SITE_URL = siteUrl;
  }

  const { default: sitemap } = await import('@/app/sitemap');
  return sitemap();
}

async function loadRobotsWithSiteUrl(siteUrl?: string) {
  vi.resetModules();

  if (siteUrl === undefined) {
    delete process.env.SITE_URL;
  } else {
    process.env.SITE_URL = siteUrl;
  }

  const { default: robots } = await import('@/app/robots');
  return robots();
}

async function loadMetadataWithSiteUrl(siteUrl?: string) {
  vi.resetModules();

  if (siteUrl === undefined) {
    delete process.env.SITE_URL;
  } else {
    process.env.SITE_URL = siteUrl;
  }

  const { metadata } = await import('@/app/layout');
  return metadata;
}

afterEach(() => {
  vi.resetModules();
  if (originalSiteUrl === undefined) {
    delete process.env.SITE_URL;
  } else {
    process.env.SITE_URL = originalSiteUrl;
  }
});

describe('SITE_URL config', () => {
  it('uses default canonical URL when SITE_URL is not set', async () => {
    const sitemap = await loadSitemapWithSiteUrl();
    const robots = await loadRobotsWithSiteUrl();
    const metadata = await loadMetadataWithSiteUrl();

    expect(sitemap[0]?.url).toBe('https://lap-coach.racing');
    expect(robots.host).toBe('https://lap-coach.racing');
    expect(robots.sitemap).toBe('https://lap-coach.racing/sitemap.xml');
    expect(metadata.metadataBase?.href).toBe('https://lap-coach.racing/');
  });

  it('applies custom SITE_URL to sitemap/robots/metadata canonical values', async () => {
    const sitemap = await loadSitemapWithSiteUrl('https://staging.lap-coach.racing');
    const robots = await loadRobotsWithSiteUrl('https://staging.lap-coach.racing');
    const metadata = await loadMetadataWithSiteUrl('https://staging.lap-coach.racing');

    expect(sitemap[0]?.url).toBe('https://staging.lap-coach.racing');
    expect(robots.host).toBe('https://staging.lap-coach.racing');
    expect(robots.sitemap).toBe('https://staging.lap-coach.racing/sitemap.xml');
    expect(metadata.metadataBase?.href).toBe('https://staging.lap-coach.racing/');
  });

  it('rejects invalid SITE_URL values', async () => {
    vi.resetModules();
    process.env.SITE_URL = 'http://lap-coach.racing';

    const { default: sitemap } = await import('@/app/sitemap');

    expect(() => sitemap()).toThrow(/SITE_URL must use https protocol/);
  });
});
