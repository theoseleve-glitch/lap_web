import { describe, it, expect } from 'vitest';
import { generateSeoMetadata } from '@/lib/seo';

describe('generateSeoMetadata', () => {
  it('returns metadata for a known route', () => {
    const meta = generateSeoMetadata('/pricing');
    expect(meta.title).toBe('Pricing');
    expect(meta.description).toBeDefined();
    expect(meta.description!.length).toBeGreaterThanOrEqual(80);
  });

  it('includes openGraph fields', () => {
    const meta = generateSeoMetadata('/pricing');
    expect(meta.openGraph).toBeDefined();
    expect(meta.openGraph!.title).toBeDefined();
    expect(meta.openGraph!.description).toBeDefined();
    expect(meta.openGraph!.url).toContain('/pricing');
    expect(meta.openGraph!.images).toBeDefined();
  });

  it('includes twitter card', () => {
    const meta = generateSeoMetadata('/pricing');
    expect(meta.twitter).toBeDefined();
    expect(meta.twitter!.card).toBe('summary_large_image');
  });

  it('includes canonical URL', () => {
    const meta = generateSeoMetadata('/pricing');
    expect(meta.alternates).toBeDefined();
    expect(meta.alternates!.canonical).toBe('https://www.lap-coach.racing/pricing');
  });

  it('returns empty metadata for unknown routes', () => {
    const meta = generateSeoMetadata('/nonexistent');
    expect(meta.title).toBeUndefined();
    expect(meta.openGraph).toBeUndefined();
  });

  it('applies overrides for dynamic routes', () => {
    const meta = generateSeoMetadata('/insights', {
      title: 'Custom Article Title',
      metaDescription: 'A custom description that is long enough to pass the minimum character length requirement for meta descriptions.',
    });
    expect(meta.title).toBe('Custom Article Title');
    expect(meta.description).toContain('custom description');
  });

  it('sets noindex when overrides specify noIndex', () => {
    const meta = generateSeoMetadata('/pricing', { noIndex: true });
    expect(meta.robots).toEqual({ index: false, follow: false });
  });
});
