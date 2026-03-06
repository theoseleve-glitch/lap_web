/**
 * IndexedDB-backed session cache for offline viewing.
 *
 * Stores the last N session summaries and the last opened session's full data.
 * Read-only offline viewing — no mutations cached.
 *
 * Limits:
 *  - Max 20 session summaries (~2KB each = ~40KB)
 *  - Max 3 full session details (~50KB each = ~150KB)
 *  - Total budget: ~200KB
 */

const DB_NAME = 'lap-session-cache';
const DB_VERSION = 1;
const STORE_SUMMARIES = 'summaries';
const STORE_DETAILS = 'details';
const MAX_SUMMARIES = 20;
const MAX_DETAILS = 3;

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('IndexedDB not available'));
      return;
    }

    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_SUMMARIES)) {
        db.createObjectStore(STORE_SUMMARIES, { keyPath: 'session_id' });
      }
      if (!db.objectStoreNames.contains(STORE_DETAILS)) {
        db.createObjectStore(STORE_DETAILS, { keyPath: 'session_id' });
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withStore<T>(
  storeName: string,
  mode: IDBTransactionMode,
  fn: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, mode);
    const store = tx.objectStore(storeName);
    const request = fn(store);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

/** Cache session summaries (the session list). */
export async function cacheSummaries(sessions: Array<{ session_id: string; [k: string]: unknown }>): Promise<void> {
  try {
    const db = await openDB();
    const tx = db.transaction(STORE_SUMMARIES, 'readwrite');
    const store = tx.objectStore(STORE_SUMMARIES);

    // Clear and re-populate with latest N
    store.clear();
    const toCache = sessions.slice(0, MAX_SUMMARIES);
    for (const session of toCache) {
      store.put({ ...session, _cachedAt: Date.now() });
    }
  } catch {
    // Non-fatal
  }
}

/** Get cached session summaries. */
export async function getCachedSummaries(): Promise<Array<{ session_id: string; [k: string]: unknown }>> {
  try {
    return await withStore(STORE_SUMMARIES, 'readonly', (store) => store.getAll());
  } catch {
    return [];
  }
}

/** Cache a full session detail. Evicts oldest if over limit. */
export async function cacheSessionDetail(sessionId: string, data: Record<string, unknown>): Promise<void> {
  try {
    const db = await openDB();
    const tx = db.transaction(STORE_DETAILS, 'readwrite');
    const store = tx.objectStore(STORE_DETAILS);

    // Check count
    const countReq = store.count();
    await new Promise<void>((resolve) => {
      countReq.onsuccess = () => {
        if (countReq.result >= MAX_DETAILS) {
          // Evict oldest by iterating
          const cursorReq = store.openCursor();
          cursorReq.onsuccess = () => {
            const cursor = cursorReq.result;
            if (cursor) {
              cursor.delete();
              resolve();
            } else {
              resolve();
            }
          };
        } else {
          resolve();
        }
      };
    });

    store.put({ session_id: sessionId, ...data, _cachedAt: Date.now() });
  } catch {
    // Non-fatal
  }
}

/** Get cached session detail. */
export async function getCachedSessionDetail(sessionId: string): Promise<Record<string, unknown> | null> {
  try {
    const result = await withStore(STORE_DETAILS, 'readonly', (store) => store.get(sessionId));
    return result ?? null;
  } catch {
    return null;
  }
}

/** Clear all cached data. */
export async function clearSessionCache(): Promise<void> {
  try {
    const db = await openDB();
    const tx = db.transaction([STORE_SUMMARIES, STORE_DETAILS], 'readwrite');
    tx.objectStore(STORE_SUMMARIES).clear();
    tx.objectStore(STORE_DETAILS).clear();
  } catch {
    // Non-fatal
  }
}
