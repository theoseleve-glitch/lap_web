import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/lead-challenge', () => ({
  verifyBotChallenge: vi.fn(),
}));

vi.mock('@/lib/lead-delivery', () => ({
  deliverLead: vi.fn(),
}));

vi.mock('@/lib/server-conversions', () => ({
  sendServerConversion: vi.fn().mockResolvedValue(undefined),
}));

import { POST } from '@/app/api/leads/route';
import { verifyBotChallenge } from '@/lib/lead-challenge';
import { deliverLead } from '@/lib/lead-delivery';
import { resetLeadAbuseState } from '@/lib/lead-abuse';

function makeRequest(body: Record<string, unknown>, ip = '198.51.100.10') {
  return new Request('http://localhost/api/leads', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-forwarded-for': ip,
      cookie: 'lap_session_id=test-session',
    },
    body: JSON.stringify(body),
  });
}

const validPayload = {
  type: 'contact',
  name: 'Jane Driver',
  email: 'jane@example.com',
  message: 'Need info',
  challengeToken: 'token-ok',
  startedAt: Date.now() - 3_000,
};

describe('POST /api/leads abuse controls', () => {
  beforeEach(() => {
    resetLeadAbuseState();
    vi.clearAllMocks();
    vi.mocked(verifyBotChallenge).mockResolvedValue({ ok: true, provider: 'turnstile' });
    vi.mocked(deliverLead).mockResolvedValue({
      crm: { destination: 'crm', status: 'sent' },
      email: { destination: 'email', status: 'sent' },
    });
  });

  it('accepts submissions under threshold', async () => {
    const response = await POST(makeRequest(validPayload));
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.ok).toBe(true);
    expect(deliverLead).toHaveBeenCalledTimes(1);
  });

  it('rejects duplicate submissions in dedupe window', async () => {
    const first = await POST(makeRequest(validPayload));
    expect(first.status).toBe(200);

    const second = await POST(makeRequest(validPayload));
    expect(second.status).toBe(409);
    const body = await second.json();
    expect(body.ok).toBe(false);
  });

  it('rejects flood submissions over per-IP threshold', async () => {
    let lastStatus = 200;

    for (let i = 0; i < 13; i += 1) {
      const response = await POST(
        makeRequest({
          ...validPayload,
          email: `driver${i}@example.com`,
        }),
      );
      lastStatus = response.status;
    }

    expect(lastStatus).toBe(429);
  });

  it('rejects an empty/omitted challenge token when a provider is configured (no skip-by-omission)', async () => {
    // A configured provider rejects an empty response token. The route must
    // ALWAYS call verifyBotChallenge — a bot must not be able to skip the
    // challenge by simply omitting challengeToken (the fixed bypass).
    vi.mocked(verifyBotChallenge).mockResolvedValue({
      ok: false,
      reason: 'missing-input-response',
      provider: 'turnstile',
    });

    const response = await POST(
      makeRequest({
        ...validPayload,
        challengeToken: '',
      }),
    );

    expect(verifyBotChallenge).toHaveBeenCalledWith(
      expect.objectContaining({ token: '' }),
    );
    expect(response.status).toBe(403);
    expect(deliverLead).not.toHaveBeenCalled();
  });

  it('accepts an empty token when no challenge provider is configured (honeypot/rate-limit fallback)', async () => {
    // Documented design: with no provider set, verifyBotChallenge reports
    // "not configured" and the route falls back to honeypot + rate limiting +
    // dedupe rather than hard-requiring a token — which would break legit
    // forms whose challenge widget is not wired yet.
    vi.mocked(verifyBotChallenge).mockResolvedValue({
      ok: false,
      reason: 'challenge provider is not configured',
    });

    const response = await POST(
      makeRequest({
        ...validPayload,
        challengeToken: '',
      }),
    );

    expect(verifyBotChallenge).toHaveBeenCalled();
    expect(response.status).toBe(200);
  });
});
