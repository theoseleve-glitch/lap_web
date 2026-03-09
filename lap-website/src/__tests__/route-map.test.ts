import { describe, it, expect } from 'vitest';
import { routeMap, buildBreadcrumbs } from '@/data/route-map';

describe('routeMap', () => {
  it('has entry for "/"', () => {
    expect(routeMap['/']).toBeDefined();
    expect(routeMap['/'].path).toBe('/');
  });

  it('every entry has path matching its key and non-empty title', () => {
    for (const [key, entry] of Object.entries(routeMap)) {
      expect(entry.path).toBe(key);
      expect(entry.title.length).toBeGreaterThan(0);
    }
  });

  it('parent references all exist in the map', () => {
    for (const [, entry] of Object.entries(routeMap)) {
      if (entry.parent !== null) {
        expect(routeMap[entry.parent]).toBeDefined();
      }
    }
  });

  it('has no circular parent references', () => {
    for (const [key, entry] of Object.entries(routeMap)) {
      const visited = new Set<string>();
      let current: string | null = entry.parent;
      visited.add(key);
      while (current !== null) {
        expect(visited.has(current)).toBe(false);
        visited.add(current);
        current = routeMap[current]?.parent ?? null;
      }
    }
  });
});

describe('SEO fields', () => {
  const nonExemptEntries = Object.entries(routeMap).filter(
    ([key, entry]) => key !== '/' && key !== '/sitemap' && !key.startsWith('/app/') && !entry.noIndex,
  );

  it('every non-exempt entry has primaryKeyword', () => {
    for (const [key, entry] of nonExemptEntries) {
      expect(entry.primaryKeyword, `${key} missing primaryKeyword`).toBeDefined();
      expect(entry.primaryKeyword!.length).toBeGreaterThan(0);
    }
  });

  it('every non-exempt entry has metaDescription between 80-160 chars', () => {
    for (const [key, entry] of nonExemptEntries) {
      expect(entry.metaDescription, `${key} missing metaDescription`).toBeDefined();
      const len = entry.metaDescription!.length;
      expect(len, `${key} metaDescription too short (${len})`).toBeGreaterThanOrEqual(80);
      expect(len, `${key} metaDescription too long (${len})`).toBeLessThanOrEqual(160);
    }
  });

  it('no two entries share the same primaryKeyword', () => {
    const keywords = nonExemptEntries.map(([, e]) => e.primaryKeyword!.toLowerCase());
    const unique = new Set(keywords);
    expect(unique.size).toBe(keywords.length);
  });

  it('no two entries share the same metaDescription', () => {
    const descriptions = nonExemptEntries.map(([, e]) => e.metaDescription!);
    const unique = new Set(descriptions);
    expect(unique.size).toBe(descriptions.length);
  });
});

describe('buildBreadcrumbs', () => {
  it('returns empty array for the homepage', () => {
    expect(buildBreadcrumbs('/')).toEqual([]);
  });

  it('returns Home trail for marketing pages', () => {
    expect(buildBreadcrumbs('/pricing')).toEqual([
      { label: 'Home', href: '/' },
    ]);
    expect(buildBreadcrumbs('/product')).toEqual([
      { label: 'Home', href: '/' },
    ]);
  });

  it('returns full trail for subpages', () => {
    const crumbs = buildBreadcrumbs('/pricing/compare');
    expect(crumbs).toEqual([
      { label: 'Home', href: '/' },
      { label: 'Pricing', href: '/pricing' },
    ]);
  });

  it('returns empty array for unknown paths', () => {
    expect(buildBreadcrumbs('/nonexistent')).toEqual([]);
    expect(buildBreadcrumbs('/foo/bar/baz')).toEqual([]);
  });
});
