/**
 * Tests for the session cache (IndexedDB).
 *
 * Uses a mock IDB since jsdom doesn't ship one.
 * Verifies the public API contract.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Minimal IndexedDB mock
function createMockIDB() {
  const stores: Record<string, Map<string, unknown>> = {};

  const mockStore = (name: string): IDBObjectStore => {
    if (!stores[name]) stores[name] = new Map();
    const data = stores[name];

    return {
      put: (val: Record<string, unknown>) => {
        const key = val.session_id as string;
        data.set(key, val);
        return { onsuccess: null, onerror: null } as unknown as IDBRequest;
      },
      get: (key: string) => {
        const req = { result: data.get(key), onsuccess: null, onerror: null } as unknown as IDBRequest;
        setTimeout(() => (req as { onsuccess: (() => void) | null }).onsuccess?.(), 0);
        return req;
      },
      getAll: () => {
        const req = { result: Array.from(data.values()), onsuccess: null, onerror: null } as unknown as IDBRequest;
        setTimeout(() => (req as { onsuccess: (() => void) | null }).onsuccess?.(), 0);
        return req;
      },
      clear: () => {
        data.clear();
        return { onsuccess: null, onerror: null } as unknown as IDBRequest;
      },
      count: () => {
        const req = { result: data.size, onsuccess: null, onerror: null } as unknown as IDBRequest;
        setTimeout(() => (req as { onsuccess: (() => void) | null }).onsuccess?.(), 0);
        return req;
      },
      openCursor: () => {
        return { onsuccess: null, onerror: null, result: null } as unknown as IDBRequest;
      },
    } as unknown as IDBObjectStore;
  };

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const mockTx = (..._storeNames: string[]) => ({
    objectStore: (name: string) => mockStore(name),
  });

  const mockDB = {
    objectStoreNames: { contains: () => false },
    createObjectStore: vi.fn(),
    transaction: (...args: unknown[]) => {
      if (Array.isArray(args[0])) return mockTx(...(args[0] as string[]));
      return mockTx(args[0] as string);
    },
  };

  return {
    open: () => {
      const req = {
        result: mockDB,
        onupgradeneeded: null as (() => void) | null,
        onsuccess: null as (() => void) | null,
        onerror: null as (() => void) | null,
      };
      setTimeout(() => {
        req.onupgradeneeded?.();
        req.onsuccess?.();
      }, 0);
      return req;
    },
  };
}

describe('session-cache', () => {
  beforeEach(() => {
    vi.stubGlobal('indexedDB', createMockIDB());
  });

  it('exports cache functions', async () => {
    const mod = await import('@/lib/session-cache');
    expect(typeof mod.cacheSummaries).toBe('function');
    expect(typeof mod.getCachedSummaries).toBe('function');
    expect(typeof mod.cacheSessionDetail).toBe('function');
    expect(typeof mod.getCachedSessionDetail).toBe('function');
    expect(typeof mod.clearSessionCache).toBe('function');
  });

  it('returns empty array when no summaries cached', async () => {
    const { getCachedSummaries } = await import('@/lib/session-cache');
    const result = await getCachedSummaries();
    expect(Array.isArray(result)).toBe(true);
  });

  it('returns null when session detail not cached', async () => {
    const { getCachedSessionDetail } = await import('@/lib/session-cache');
    const result = await getCachedSessionDetail('nonexistent');
    expect(result).toBeNull();
  });
});
