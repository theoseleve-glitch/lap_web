import type { LeadType } from '@/lib/lead-types';

const RATE_WINDOW_MS = Number(process.env.LEAD_RATE_LIMIT_WINDOW_MS ?? 60_000);
const IP_MAX = Number(process.env.LEAD_RATE_LIMIT_IP_MAX ?? 12);
const SESSION_MAX = Number(process.env.LEAD_RATE_LIMIT_SESSION_MAX ?? 6);
const DEDUPE_WINDOW_MS = Number(process.env.LEAD_DEDUPE_WINDOW_MS ?? 10 * 60_000);
const ALERT_WINDOW_MS = Number(process.env.LEAD_ABUSE_ALERT_WINDOW_MS ?? 5 * 60_000);
const ALERT_MIN_EVENTS = Number(process.env.LEAD_ABUSE_ALERT_MIN_EVENTS ?? 20);
const ALERT_FAILURE_RATIO = Number(process.env.LEAD_ABUSE_ALERT_FAILURE_RATIO ?? 0.6);
const ALERT_COOLDOWN_MS = Number(process.env.LEAD_ABUSE_ALERT_COOLDOWN_MS ?? 5 * 60_000);

const ipHits = new Map<string, number[]>();
const sessionHits = new Map<string, number[]>();
const dedupeHits = new Map<string, number>();
const abuseEvents: Array<{ ts: number; outcome: string }> = [];
let lastAlertAt = 0;

function keepRecent(timestamps: number[], now: number, windowMs: number): number[] {
  const min = now - windowMs;
  return timestamps.filter((ts) => ts >= min);
}

function keyBucket(now: number, windowMs: number): number {
  return Math.floor(now / windowMs);
}

export function getClientIp(headers: Headers): string {
  const forwardedFor = headers.get('x-forwarded-for');
  if (forwardedFor) {
    const first = forwardedFor.split(',')[0]?.trim();
    if (first) return first;
  }

  return headers.get('x-real-ip') ?? 'unknown';
}

export function consumeLeadRateLimit(params: {
  ip: string;
  sessionId?: string;
  now?: number;
}): { limited: boolean; reason?: 'ip' | 'session'; retryAfterSeconds?: number } {
  const now = params.now ?? Date.now();

  const ipTimestamps = keepRecent(ipHits.get(params.ip) ?? [], now, RATE_WINDOW_MS);
  ipTimestamps.push(now);
  ipHits.set(params.ip, ipTimestamps);

  if (ipTimestamps.length > IP_MAX) {
    return {
      limited: true,
      reason: 'ip',
      retryAfterSeconds: Math.ceil(RATE_WINDOW_MS / 1000),
    };
  }

  if (params.sessionId) {
    const sessionTimestamps = keepRecent(
      sessionHits.get(params.sessionId) ?? [],
      now,
      RATE_WINDOW_MS,
    );
    sessionTimestamps.push(now);
    sessionHits.set(params.sessionId, sessionTimestamps);

    if (sessionTimestamps.length > SESSION_MAX) {
      return {
        limited: true,
        reason: 'session',
        retryAfterSeconds: Math.ceil(RATE_WINDOW_MS / 1000),
      };
    }
  }

  return { limited: false };
}

export function isDuplicateLead(params: {
  email: string;
  type: LeadType;
  now?: number;
}): boolean {
  const now = params.now ?? Date.now();
  const normalizedEmail = params.email.trim().toLowerCase();
  const key = `${normalizedEmail}:${params.type}:${keyBucket(now, DEDUPE_WINDOW_MS)}`;

  for (const [storedKey, timestamp] of dedupeHits.entries()) {
    if (timestamp < now - DEDUPE_WINDOW_MS) {
      dedupeHits.delete(storedKey);
    }
  }

  if (dedupeHits.has(key)) {
    return true;
  }

  dedupeHits.set(key, now);
  return false;
}

export function recordLeadAbuseEvent(outcome: string, now = Date.now()): {
  shouldAlert: boolean;
  ratio?: number;
  total?: number;
} {
  abuseEvents.push({ ts: now, outcome });

  const min = now - ALERT_WINDOW_MS;
  while (abuseEvents.length > 0 && abuseEvents[0] && abuseEvents[0].ts < min) {
    abuseEvents.shift();
  }

  const total = abuseEvents.length;
  const failures = abuseEvents.filter((event) => event.outcome !== 'accepted').length;
  const ratio = total > 0 ? failures / total : 0;

  if (
    total >= ALERT_MIN_EVENTS &&
    ratio >= ALERT_FAILURE_RATIO &&
    now - lastAlertAt >= ALERT_COOLDOWN_MS
  ) {
    lastAlertAt = now;
    return { shouldAlert: true, ratio, total };
  }

  return { shouldAlert: false };
}

export function resetLeadAbuseState(): void {
  ipHits.clear();
  sessionHits.clear();
  dedupeHits.clear();
  abuseEvents.length = 0;
  lastAlertAt = 0;
}
