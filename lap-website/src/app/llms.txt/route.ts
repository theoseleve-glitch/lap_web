import { routeMap } from '@/data/route-map';
import { BRAND } from '@/data/brand';

const HEADERS = {
  'Content-Type': 'text/plain; charset=utf-8',
  'Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=600',
};

export function GET(): Response {
  const now = new Date();
  const lastUpdated = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;

  const keyPages = Object.values(routeMap)
    .filter((entry) => !entry.noIndex && entry.metaDescription)
    .slice(0, 15)
    .map((entry) => `- [${entry.title}](https://www.lap-coach.racing${entry.path}): ${entry.metaDescription}`)
    .join('\n');

  const content = `# ${BRAND.productName} \u2014 Motorsport Telemetry Analysis Platform

> ${BRAND.positioning}

## About

- Type: WebApplication
- Category: Motorsport Telemetry Analysis / Driver Coaching SaaS
- Language: English
- Audience: Kart and car racing drivers, coaches, and teams
- Pricing: One membership \u2014 \u20ac19.90/mo (\u20ac14.90/mo for the first 50 founding members), 30-day free trial, no free tier
- Last Updated: ${lastUpdated}

## Key Pages

${keyPages}

## Canonical

- Primary URL: https://www.lap-coach.racing
- llms.txt Location: https://www.lap-coach.racing/llms.txt
- API URL: https://api.lap-coach.racing

## Optional

- Changelog: https://www.lap-coach.racing/changelog
- Waitlist: https://www.lap-coach.racing/waitlist
- Contact: https://www.lap-coach.racing/contact
`;

  return new Response(content, { headers: HEADERS });
}
