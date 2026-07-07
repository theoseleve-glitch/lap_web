/**
 * Tests for the Turnstile step-up challenge contract in lib/auth.ts.
 *
 * Backend contract (telemetry_tool/web/routes/auth.py::login /
 * auth/lockout.py::challenge_required): a flagged email gets an HTTP 428
 * envelope `{ challenge_required: true, sitekey }` instead of normal tokens;
 * submitting again with a `cf-turnstile-response` token lets login proceed.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

vi.stubGlobal('BroadcastChannel', class {
  onmessage = null;
  postMessage = vi.fn();
  close = vi.fn();
});

function envelopeResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    text: async () => JSON.stringify(body),
  };
}

describe('login() Turnstile step-up challenge', () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it('returns a ChallengeRequired result on a 428 challenge_required envelope', async () => {
    mockFetch.mockResolvedValueOnce(
      envelopeResponse(
        { ok: true, data: { challenge_required: true, sitekey: '1x00000000000000000000AA' } },
        428,
      ),
    );

    const { login } = await import('@/lib/auth');
    const result = await login('flagged@example.com', 'whatever-password');

    expect(result).toEqual({ challenge_required: true, sitekey: '1x00000000000000000000AA' });
  });

  it('does not set an access token for a challenge_required result', async () => {
    mockFetch.mockResolvedValueOnce(
      envelopeResponse(
        { ok: true, data: { challenge_required: true, sitekey: null } },
        428,
      ),
    );

    const { login, clearAuthState } = await import('@/lib/auth');
    const { getAccessToken } = await import('@/lib/auth-store');

    clearAuthState();
    await login('flagged@example.com', 'whatever-password');
    expect(getAccessToken()).toBeNull();
  });

  it('includes cf-turnstile-response in the request body when a token is provided', async () => {
    mockFetch.mockResolvedValueOnce(
      envelopeResponse({
        ok: true,
        data: {
          access_token: 'tok-123',
          refresh_token: 'refresh-123',
          user: { id: 1, email: 'flagged@example.com', display_name: 'Flagged' },
        },
      }),
    );

    const { login } = await import('@/lib/auth');
    await login('flagged@example.com', 'correct-password', 'cf-token-abc');

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [, init] = mockFetch.mock.calls[0];
    const sentBody = JSON.parse((init as RequestInit).body as string);
    expect(sentBody['cf-turnstile-response']).toBe('cf-token-abc');
    expect(sentBody.email).toBe('flagged@example.com');
  });

  it('omits cf-turnstile-response when no token is provided', async () => {
    mockFetch.mockResolvedValueOnce(
      envelopeResponse(
        { ok: true, data: { challenge_required: true, sitekey: 'site-key' } },
        428,
      ),
    );

    const { login } = await import('@/lib/auth');
    await login('unflagged@example.com', 'whatever-password');

    const [, init] = mockFetch.mock.calls[0];
    const sentBody = JSON.parse((init as RequestInit).body as string);
    expect('cf-turnstile-response' in sentBody).toBe(false);
  });
});
