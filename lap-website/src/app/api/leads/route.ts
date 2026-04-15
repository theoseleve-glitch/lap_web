import { NextResponse } from 'next/server';
import { validateLeadPayload } from '@/lib/lead-validation';
import { deliverLead } from '@/lib/lead-delivery';
import { sendServerConversion } from '@/lib/server-conversions';
import {
  consumeLeadRateLimit,
  getClientIp,
  isDuplicateLead,
  recordLeadAbuseEvent,
} from '@/lib/lead-abuse';
import { verifyBotChallenge } from '@/lib/lead-challenge';

function parseAttributionCookie(value: string | undefined): Record<string, string> | undefined {
  if (!value) return undefined;
  try {
    return JSON.parse(decodeURIComponent(value)) as Record<string, string>;
  } catch {
    return undefined;
  }
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const challengeToken =
    body && typeof body === 'object' && typeof body.challengeToken === 'string'
      ? body.challengeToken.trim()
      : '';
  const validation = validateLeadPayload(body);

  const ip = getClientIp(request.headers);
  const sessionIdFromCookie = request.headers
    .get('cookie')
    ?.split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith('lap_session_id='))
    ?.split('=')[1];

  // Bot challenge verification — only enforced when a provider is configured.
  // When no provider is set, rely on honeypot + rate limiting + duplicate detection.
  if (challengeToken) {
    const challenge = await verifyBotChallenge({ token: challengeToken, remoteIp: ip });
    if (!challenge.ok && challenge.reason !== 'challenge provider is not configured') {
      const alert = recordLeadAbuseEvent('challenge_failed');
      await sendServerConversion({
        event: 'lead_abuse_signal',
        sourcePath: undefined,
        leadType: 'unknown',
        sessionId: sessionIdFromCookie,
        attribution: { reason: challenge.reason ?? 'challenge_failed', provider: challenge.provider ?? 'unknown' },
      });
      if (alert.shouldAlert) {
        console.error('Lead abuse alert triggered', {
          ratio: alert.ratio,
          total: alert.total,
          reason: 'challenge_failed',
        });
      }
      return NextResponse.json(
        { ok: false, message: 'Challenge verification failed.' },
        { status: 403 },
      );
    }
  }

  if (!validation.valid) {
    recordLeadAbuseEvent('validation_failed');
    return NextResponse.json(
      {
        ok: false,
        message: 'Validation failed',
        fieldErrors: validation.fieldErrors,
      },
      { status: 400 },
    );
  }

  const attribution = parseAttributionCookie(
    request.headers
      .get('cookie')
      ?.split(';')
      .map((part) => part.trim())
      .find((part) => part.startsWith('lap_attribution='))
      ?.split('=')[1],
  );

  const payload = {
    ...validation.data,
    utm: validation.data.utm ?? attribution,
    sessionId: validation.data.sessionId ?? sessionIdFromCookie,
    challengeToken,
  };

  const rateLimit = consumeLeadRateLimit({ ip, sessionId: payload.sessionId });
  if (rateLimit.limited) {
    const alert = recordLeadAbuseEvent('rate_limited');
    await sendServerConversion({
      event: 'lead_abuse_signal',
      leadType: payload.type,
      sourcePath: payload.sourcePath,
      sessionId: payload.sessionId,
      attribution: { reason: `rate_limit_${rateLimit.reason ?? 'unknown'}` },
    });
    if (alert.shouldAlert) {
      console.error('Lead abuse alert triggered', {
        ratio: alert.ratio,
        total: alert.total,
        reason: 'rate_limited',
      });
      await sendServerConversion({
        event: 'lead_abuse_alert',
        leadType: payload.type,
        sourcePath: payload.sourcePath,
        sessionId: payload.sessionId,
        attribution: {
          reason: 'rate_limited',
          ratio: String(alert.ratio ?? 0),
          total: String(alert.total ?? 0),
        },
      });
    }
    return NextResponse.json(
      {
        ok: false,
        message: 'Too many submissions. Please try again shortly.',
      },
      {
        status: 429,
        headers: rateLimit.retryAfterSeconds
          ? { 'retry-after': String(rateLimit.retryAfterSeconds) }
          : undefined,
      },
    );
  }

  if (isDuplicateLead({ email: payload.email, type: payload.type })) {
    recordLeadAbuseEvent('duplicate');
    await sendServerConversion({
      event: 'lead_abuse_signal',
      leadType: payload.type,
      sourcePath: payload.sourcePath,
      sessionId: payload.sessionId,
      attribution: { reason: 'duplicate_submission' },
    });
    return NextResponse.json(
      {
        ok: false,
        message: 'A similar submission was already received recently.',
      },
      { status: 409 },
    );
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { challengeToken: _challengeToken, ...deliverablePayload } = payload;

  const delivery = await deliverLead(deliverablePayload);
  const sentCount = [delivery.crm, delivery.email].filter((item) => item.status === 'sent').length;
  const failedCount = [delivery.crm, delivery.email].filter((item) => item.status === 'failed').length;

  await sendServerConversion({
    event: 'lead_submitted',
    leadType: payload.type,
    sourcePath: payload.sourcePath,
    attribution: payload.utm,
    sessionId: payload.sessionId,
  });

  if (failedCount > 0 && sentCount === 0) {
    const alert = recordLeadAbuseEvent('delivery_failed');
    if (alert.shouldAlert) {
      await sendServerConversion({
        event: 'lead_abuse_alert',
        leadType: payload.type,
        sourcePath: payload.sourcePath,
        sessionId: payload.sessionId,
        attribution: {
          reason: 'delivery_failed',
          ratio: String(alert.ratio ?? 0),
          total: String(alert.total ?? 0),
        },
      });
    }
    return NextResponse.json(
      {
        ok: false,
        message: 'Lead could not be delivered to CRM/email endpoints.',
      },
      { status: 502 },
    );
  }

  recordLeadAbuseEvent('accepted');

  return NextResponse.json({
    ok: true,
    message:
      sentCount > 0
        ? 'Lead captured and forwarded successfully.'
        : 'Lead captured. CRM/email endpoints are not configured yet.',
  });
}
