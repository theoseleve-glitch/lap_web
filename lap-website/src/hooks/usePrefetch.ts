/**
 * Hook for route + data prefetching on pointer enter.
 *
 * Usage:
 *   const prefetchProps = usePrefetch('/app/sessions/abc', {
 *     queryKey: ['sessions', 'detail', 'abc'],
 *     queryFn: () => api.get(`/sessions/abc`),
 *   });
 *   <Link href="/app/sessions/abc" {...prefetchProps}>...</Link>
 */

import { useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useQueryClient, type QueryKey } from '@tanstack/react-query';
import {
  canPrefetch,
  markPrefetched,
  incrementInFlight,
  decrementInFlight,
  isAllowedRoute,
} from '@/lib/prefetch';

interface DataPrefetch {
  queryKey: QueryKey;
  queryFn: () => Promise<unknown>;
  staleTime?: number;
}

interface PrefetchOptions {
  dataPrefetch?: DataPrefetch;
}

/**
 * Returns `onPointerEnter` props to spread onto a Link or element.
 * Prefetches both the route chunk and optional data on hover.
 */
export function usePrefetch(href: string, options?: PrefetchOptions) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const prefetchedRef = useRef(false);

  const onPointerEnter = useCallback(() => {
    if (prefetchedRef.current) return;

    // Route prefetch
    const routeKey = `route:${href}`;
    if (isAllowedRoute(href) && canPrefetch(routeKey)) {
      markPrefetched(routeKey);
      router.prefetch(href);
    }

    // Data prefetch
    if (options?.dataPrefetch) {
      const dataKey = `data:${JSON.stringify(options.dataPrefetch.queryKey)}`;
      if (canPrefetch(dataKey)) {
        markPrefetched(dataKey);
        incrementInFlight();
        queryClient
          .prefetchQuery({
            queryKey: options.dataPrefetch.queryKey,
            queryFn: options.dataPrefetch.queryFn,
            staleTime: options.dataPrefetch.staleTime ?? 30_000,
          })
          .finally(() => {
            decrementInFlight();
          });
      }
    }

    prefetchedRef.current = true;
  }, [href, options, router, queryClient]);

  return { onPointerEnter };
}
