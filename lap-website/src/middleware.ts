import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const ATTRIBUTION_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'gclid', 'fbclid'];
const EXPERIMENTS: Record<string, string[]> = {
  lap_exp_hero: ['control', 'performance_focus'],
  lap_exp_pricing: ['standard_table', 'comparison_first'],
  lap_exp_cta: ['demo_first', 'book_first'],
};

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

export function middleware(request: NextRequest) {
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

  const attribution = parseAttribution(request);
  if (Object.keys(attribution).length > 0) {
    response.cookies.set('lap_attribution', JSON.stringify(attribution), {
      httpOnly: false,
      sameSite: 'lax',
      secure: process.env.NODE_ENV === 'production',
      path: '/',
      maxAge: 60 * 60 * 24 * 90,
    });
  }

  for (const [cookieName, options] of Object.entries(EXPERIMENTS)) {
    if (!request.cookies.get(cookieName)?.value) {
      const value = options[Math.floor(Math.random() * options.length)];
      response.cookies.set(cookieName, value, {
        httpOnly: false,
        sameSite: 'lax',
        secure: process.env.NODE_ENV === 'production',
        path: '/',
        maxAge: 60 * 60 * 24 * 30,
      });
    }
  }

  return response;
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
