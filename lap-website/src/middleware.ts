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

function detectPersona(request: NextRequest): string {
  const explicitPersona = request.nextUrl.searchParams.get('persona');
  if (explicitPersona) return explicitPersona;
  return request.cookies.get('lap_persona')?.value ?? 'drivers';
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
  // Canonical domain redirect: bare domain → www (301 permanent)
  const host = request.headers.get('host') ?? '';
  if (host === 'lap-coach.racing') {
    const url = request.nextUrl.clone();
    url.host = CANONICAL_HOST;
    url.port = '';
    const redirect = NextResponse.redirect(url, 301);
    redirect.headers.set('Strict-Transport-Security', 'max-age=300');
    return redirect;
  }

  const response = NextResponse.next();

  if (!request.cookies.get('lap_session_id')?.value) {
    response.cookies.set('lap_session_id', crypto.randomUUID(), {
      httpOnly: false,
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

  const persona = detectPersona(request);
  response.cookies.set('lap_persona', persona, {
    httpOnly: false,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: 60 * 60 * 24 * 90,
  });

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

  // Prevent Cloudflare from caching HTML pages for too long.
  // Static assets (/_next/static/) are excluded by the matcher and have
  // content-hashed filenames, so they can be cached indefinitely.
  // HTML pages must revalidate on each deploy to avoid stale chunk references.
  const isPageRequest =
    !request.nextUrl.pathname.startsWith('/_next/') &&
    !request.nextUrl.pathname.startsWith('/api/');
  if (isPageRequest) {
    response.headers.set(
      'Cache-Control',
      'public, s-maxage=60, stale-while-revalidate=30'
    );
  }

  return response;
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
