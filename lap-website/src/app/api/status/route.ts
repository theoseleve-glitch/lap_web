import { NextResponse } from 'next/server';

interface StatusPayload {
  indicator: 'none' | 'minor' | 'major' | 'critical';
  description: string;
  source: string;
  updatedAt: string;
}

const FALLBACK_STATUS: StatusPayload = {
  indicator: 'none',
  description: 'Operational',
  source: 'fallback',
  updatedAt: new Date().toISOString(),
};

export async function GET() {
  const candidates = [
    'https://status.lap.racing/api/v2/status.json',
    'https://status.lap.racing/api/status',
  ];

  for (const endpoint of candidates) {
    try {
      const response = await fetch(endpoint, { next: { revalidate: 60 } });
      if (!response.ok) continue;

      const data: Record<string, unknown> = await response.json();
      const nested = data.status as Record<string, unknown> | undefined;
      const indicatorRaw = String(nested?.indicator ?? data.indicator ?? 'none').toLowerCase();
      const description = String(nested?.description ?? data.description ?? 'Operational');
      const updatedAt = String(data.page?.updated_at ?? data.updated_at ?? new Date().toISOString());

      const indicator =
        indicatorRaw === 'critical' || indicatorRaw === 'major' || indicatorRaw === 'minor'
          ? indicatorRaw
          : 'none';

      return NextResponse.json({
        indicator,
        description,
        source: endpoint,
        updatedAt,
      } satisfies StatusPayload);
    } catch {
      // Try next endpoint.
    }
  }

  return NextResponse.json(FALLBACK_STATUS);
}
