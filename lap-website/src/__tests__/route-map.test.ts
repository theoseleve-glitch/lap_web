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

describe('buildBreadcrumbs', () => {
  it('returns empty array for top-level pages', () => {
    expect(buildBreadcrumbs('/')).toEqual([]);
    expect(buildBreadcrumbs('/pricing')).toEqual([]);
    expect(buildBreadcrumbs('/product')).toEqual([]);
  });

  it('returns trail for subpages', () => {
    const crumbs = buildBreadcrumbs('/pricing/compare');
    expect(crumbs).toEqual([
      { label: 'Pricing', href: '/pricing' },
    ]);
  });

  it('returns empty array for unknown paths', () => {
    expect(buildBreadcrumbs('/nonexistent')).toEqual([]);
    expect(buildBreadcrumbs('/foo/bar/baz')).toEqual([]);
  });
});
