import { NextResponse } from 'next/server';

/**
 * Static feature flag endpoint.
 * Returns default flags — override per-environment by changing this response
 * or pointing to a remote config service.
 *
 * Cache: 60s CDN, 30s stale-while-revalidate.
 */
export function GET() {
  const flags = {
    offline_cache: true,
    web_vitals: true,
    chart_placeholders: true,
    driving_analyzer: true,
    session_expired_modal: true,
  };

  return NextResponse.json(flags, {
    headers: {
      'Cache-Control': 'public, s-maxage=60, stale-while-revalidate=30',
    },
  });
}
