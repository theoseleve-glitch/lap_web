import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const ATTRIBUTION_KEYS = [
  'utm_source',
  'utm_medium',
  'utm_campaign',
  'utm_term',
  'utm_content',
  'gclid',
  'fbclid',
];

function parseAttribution(request: NextRequest): Record<string, string> {
  const result: Record<string, string> = {};
  for (const key of ATTRIBUTION_KEYS) {
    const value = request.nextUrl.searchParams.get(key);
    if (value) {
      result[key] = value;
    }
  }
  return result;
}

function chooseVariant(cookieName: string, persona: string, attribution: Record<string, string>): string {
  const source = (attribution.utm_source ?? '').toLowerCase();
  const isPaid = !!attribution.gclid || !!attribution.fbclid || source.includes('ads') || source.includes('google');

  if (cookieName === 'lap_exp_hero') {
    if (persona !== 'drivers' || isPaid) return 'performance_focus';
    return 'control';
  }

  if (cookieName === 'lap_exp_pricing') {
    if (persona === 'circuits' || persona === 'teams' || persona === 'endurance') {
      return 'comparison_first';
    }
    return 'standard_table';
  }

  if (cookieName === 'lap_exp_cta') {
    if (persona !== 'drivers' || isPaid) return 'book_first';
    return 'demo_first';
  }

  return 'control';
}

const CANONICAL_HOST = 'www.lap-coach.racing';

export function middleware(request: NextRequest) {
  const host = request.headers.get('host') ?? '';
  const isCanonicalHost = host === CANONICAL_HOST;

  // Canonical domain redirect: bare domain → www (301 permanent)
  if (host === 'lap-coach.racing') {
    const url = request.nextUrl.clone();
    url.host = CANONICAL_HOST;
    url.port = '';
    const redirect = NextResponse.redirect(url, 301);
    redirect.headers.set('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
    // The redirect response itself is FROM the bare apex (non-canonical);
    // belt-and-suspenders noindex so the 301 doesn't get crawled/cached.
    redirect.headers.set('X-Robots-Tag', 'noindex, nofollow');
    return redirect;
  }

  // Strip trailing slashes (except root) → 301 to canonical path
  const { pathname } = request.nextUrl;
  if (pathname.length > 1 && pathname.endsWith('/')) {
    const url = request.nextUrl.clone();
    url.pathname = pathname.replace(/\/+$/, '');
    const redirect = NextResponse.redirect(url, 301);
    if (!isCanonicalHost) {
      redirect.headers.set('X-Robots-Tag', 'noindex, nofollow');
    }
    return redirect;
  }

  const response = NextResponse.next();

  // M-01: HSTS with 1-year max-age + includeSubDomains
  response.headers.set('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');

  // Block search-engine indexing of any non-canonical host (workers.dev,
  // preview deploys, localhost). www.lap-coach.racing remains indexable.
  if (!isCanonicalHost) {
    response.headers.set('X-Robots-Tag', 'noindex, nofollow');
  }

  if (!request.cookies.get('lap_session_id')?.value) {
    response.cookies.set('lap_session_id', crypto.randomUUID(), {
      httpOnly: true,
      sameSite: 'lax',
      secure: process.env.NODE_ENV === 'production',
      path: '/',
      maxAge: 60 * 60 * 24 * 180,
    });
  }

  if (!request.cookies.get('lap_locale')?.value) {
    response.cookies.set('lap_locale', request.nextUrl.searchParams.get('lang') || 'en', {
      httpOnly: false,
      sameSite: 'lax',
      secure: process.env.NODE_ENV === 'production',
      path: '/',
      maxAge: 60 * 60 * 24 * 180,
    });
  }

  if (!request.cookies.get('lap_currency')?.value) {
    response.cookies.set('lap_currency', request.nextUrl.searchParams.get('currency') || 'eur', {
      httpOnly: false,
      sameSite: 'lax',
      secure: process.env.NODE_ENV === 'production',
      path: '/',
      maxAge: 60 * 60 * 24 * 180,
    });
  }

  // L-04: Only set lap_persona when user explicitly chose one (query param)
  // or already has the cookie. Don't set on first visit before interaction.
  const explicitPersona = request.nextUrl.searchParams.get('persona');
  const existingPersona = request.cookies.get('lap_persona')?.value;
  if (explicitPersona || existingPersona) {
    const persona = explicitPersona || existingPersona || 'drivers';
    response.cookies.set('lap_persona', persona, {
      httpOnly: false,
      sameSite: 'lax',
      secure: process.env.NODE_ENV === 'production',
      path: '/',
      maxAge: 60 * 60 * 24 * 90,
    });
  }
  const persona = explicitPersona || existingPersona || 'drivers';

  const consent = request.cookies.get('lap_cookie_consent')?.value;
  const consentGranted = consent === 'granted';
  const attribution = parseAttribution(request);

  if (consentGranted && Object.keys(attribution).length > 0) {
    response.cookies.set('lap_attribution', JSON.stringify(attribution), {
      httpOnly: false,
      sameSite: 'lax',
      secure: process.env.NODE_ENV === 'production',
      path: '/',
      maxAge: 60 * 60 * 24 * 90,
    });
  }

  if (consentGranted) {
    const experimentCookies = ['lap_exp_hero', 'lap_exp_pricing', 'lap_exp_cta'];
    for (const cookieName of experimentCookies) {
      if (!request.cookies.get(cookieName)?.value) {
        const value = chooseVariant(cookieName, persona, attribution);
        response.cookies.set(cookieName, value, {
          httpOnly: false,
          sameSite: 'lax',
          secure: process.env.NODE_ENV === 'production',
          path: '/',
          maxAge: 60 * 60 * 24 * 30,
        });
      }
    }
  }

  // Cache control for Cloudflare Workers / CDN.
  // Static assets (/_next/static/) are excluded by the matcher and have
  // content-hashed filenames, so they can be cached indefinitely.
  // HTML pages must revalidate on each deploy to avoid stale chunk references.
  const isApiRoute = pathname.startsWith('/api/');
  if (!pathname.startsWith('/_next/') && !isApiRoute) {
    // Browser sees short TTL; Cloudflare edge caches longer via CDN-Cache-Control
    response.headers.set('Cache-Control', 'public, max-age=0, must-revalidate');
    response.headers.set('CDN-Cache-Control', 'public, s-maxage=60, stale-while-revalidate=30');
  }

  return response;
}

export const config = {
  matcher: [
    /*
     * Match all paths except:
     * - _next/static (static assets)
     * - _next/image (image optimization)
     * - favicon.ico, robots.txt, sitemap.xml
     * - Public static files (images, fonts, JS, CSS)
     */
    '/((?!_next/static|_next/image|favicon\\.ico|robots\\.txt|sitemap\\.xml|manifest\\.json|.*\\.(?:png|jpg|jpeg|gif|svg|ico|woff2?|ttf|eot|css|js|map|webp|avif)).*)',
  ],
};
