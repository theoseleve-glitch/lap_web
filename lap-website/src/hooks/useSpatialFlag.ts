'use client';

import { useSearchParams } from 'next/navigation';

/**
 * Day-13 Phase 7.5 — URL-driven gate for the conditions UI surfaces
 * (ConditionRow, Spatial Grip mode toggle, SpatialDiagnosticsPanel).
 *
 * Returns true when the request has `?debug=spatial`. Founding members
 * at launch see no conditions UI until the flag flips post-bug-4
 * (Distance(m) cascade in step 09a2).
 *
 * Why a URL param rather than the email/server-driven useFeatureFlag:
 *   - Zero round-trip, no async resolve, no caching window.
 *   - Reviewer / engineering can toggle on any session URL inline.
 *   - Cannot be enabled by an unauthenticated visitor: the surfaces
 *     it gates live inside /app/* which already requires auth.
 */
export function useSpatialFlag(): boolean {
  const searchParams = useSearchParams();
  return searchParams?.get('debug') === 'spatial';
}
