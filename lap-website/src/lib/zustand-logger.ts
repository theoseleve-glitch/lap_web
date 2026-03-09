/**
 * Development-only Zustand middleware that logs state changes.
 *
 * Usage:
 *   import { devLogger } from '@/lib/zustand-logger';
 *   const useStore = create<State>()(devLogger('StoreName', (set) => ({ ... })));
 *
 * In production the middleware is a no-op passthrough.
 */
import type { StateCreator, StoreMutatorIdentifier } from 'zustand';

type DevLogger = <
  T,
  Mps extends [StoreMutatorIdentifier, unknown][] = [],
  Mcs extends [StoreMutatorIdentifier, unknown][] = [],
>(
  name: string,
  f: StateCreator<T, Mps, Mcs>,
) => StateCreator<T, Mps, Mcs>;

const isDev = process.env.NODE_ENV === 'development';

export const devLogger: DevLogger = (name, f) => (set, get, store) => {
  if (!isDev) return f(set, get, store);

  const loggedSet: typeof set = (...args) => {
    const prev = get();
    // @ts-expect-error -- spread of overloaded set() params
    set(...args);
    const next = get();
    console.debug(`[zustand:${name}]`, { prev, next }); // eslint-disable-line no-console
  };

  return f(loggedSet, get, store);
};
