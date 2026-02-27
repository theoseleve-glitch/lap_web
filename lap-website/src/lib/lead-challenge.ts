const TURNSTILE_VERIFY_URL =
  process.env.TURNSTILE_VERIFY_URL ?? 'https://challenges.cloudflare.com/turnstile/v0/siteverify';
const HCAPTCHA_VERIFY_URL = process.env.HCAPTCHA_VERIFY_URL ?? 'https://hcaptcha.com/siteverify';

type ChallengeProvider = 'turnstile' | 'hcaptcha';

function getChallengeConfig(): { provider: ChallengeProvider; secret: string; endpoint: string } | null {
  const provider = process.env.LEAD_CHALLENGE_PROVIDER;

  if (provider === 'turnstile') {
    const secret = process.env.TURNSTILE_SECRET_KEY;
    if (!secret) return null;
    return { provider, secret, endpoint: TURNSTILE_VERIFY_URL };
  }

  if (provider === 'hcaptcha') {
    const secret = process.env.HCAPTCHA_SECRET_KEY;
    if (!secret) return null;
    return { provider, secret, endpoint: HCAPTCHA_VERIFY_URL };
  }

  return null;
}

export async function verifyBotChallenge(params: {
  token: string;
  remoteIp?: string;
}): Promise<{ ok: boolean; reason?: string; provider?: ChallengeProvider }> {
  const config = getChallengeConfig();
  if (!config) {
    return { ok: false, reason: 'challenge provider is not configured' };
  }

  const body = new URLSearchParams();
  body.set('secret', config.secret);
  body.set('response', params.token);
  if (params.remoteIp) {
    body.set('remoteip', params.remoteIp);
  }

  try {
    const response = await fetch(config.endpoint, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    });

    if (!response.ok) {
      return { ok: false, reason: `challenge verification HTTP ${response.status}` };
    }

    const payload = (await response.json()) as { success?: boolean; 'error-codes'?: string[] };
    if (payload.success) {
      return { ok: true, provider: config.provider };
    }

    return {
      ok: false,
      reason: payload['error-codes']?.join(', ') ?? 'challenge failed',
      provider: config.provider,
    };
  } catch (error) {
    return {
      ok: false,
      reason: error instanceof Error ? error.message : 'challenge request failed',
      provider: config.provider,
    };
  }
}
