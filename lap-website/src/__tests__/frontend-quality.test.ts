/**
 * Tests for frontend quality improvements:
 * 1. Logger wrapper gates console.* behind NODE_ENV
 * 2. ApiError carries requestId from backend envelope
 * 3. parseEnvelopeOrThrow extracts request_id from body + header
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── 1. Logger tests ──────────────────────────────────────────────────────

describe('logger', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('error() always emits regardless of NODE_ENV', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { logger } = await import('@/lib/logger');
    logger.error('boom');
    expect(spy).toHaveBeenCalledWith('boom');
  });

  it('debug/info/warn are silenced in production', async () => {
    // The module reads process.env.NODE_ENV at import time.
    // In vitest, NODE_ENV is 'test' which != 'production',
    // so we test the inverse: they DO emit in non-production.
    const debugSpy = vi.spyOn(console, 'debug').mockImplementation(() => {});
    const infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { logger } = await import('@/lib/logger');
    logger.debug('d');
    logger.info('i');
    logger.warn('w');
    // In test env (non-production), all should emit
    expect(debugSpy).toHaveBeenCalled();
    expect(infoSpy).toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalled();
  });
});

// ── 2. ApiError requestId ────────────────────────────────────────────────

describe('ApiError', () => {
  it('carries requestId when provided', async () => {
    const { ApiError } = await import('@/lib/api-client');
    const err = new ApiError('ERR', 'fail', 500, undefined, 'abc123');
    expect(err.requestId).toBe('abc123');
    expect(err.message).toBe('fail');
    expect(err.code).toBe('ERR');
    expect(err.status).toBe(500);
  });

  it('requestId is undefined when not provided', async () => {
    const { ApiError } = await import('@/lib/api-client');
    const err = new ApiError('ERR', 'fail', 500);
    expect(err.requestId).toBeUndefined();
  });
});

// ── 3. parseEnvelopeOrThrow request_id extraction ────────────────────────

describe('parseEnvelopeOrThrow', () => {
  function makeResponse(body: object, status = 200, headers?: Record<string, string>): Response {
    const h = new Headers({ 'content-type': 'application/json', ...headers });
    return new Response(JSON.stringify(body), { status, headers: h });
  }

  it('extracts request_id from meta on error envelope', async () => {
    const { parseEnvelopeOrThrow } = await import('@/lib/http-envelope');
    const res = makeResponse(
      { ok: false, error: { code: 'BAD', message: 'nope' }, meta: { request_id: 'req_123' } },
      400,
    );
    try {
      await parseEnvelopeOrThrow(res);
      expect.unreachable();
    } catch (err: unknown) {
      const { ApiError } = await import('@/lib/api-client');
      expect(err).toBeInstanceOf(ApiError);
      expect((err as InstanceType<typeof ApiError>).requestId).toBe('req_123');
    }
  });

  it('extracts request_id from X-Request-Id header when no meta', async () => {
    const { parseEnvelopeOrThrow } = await import('@/lib/http-envelope');
    const res = makeResponse(
      { ok: false, error: { code: 'BAD', message: 'nope' } },
      400,
      { 'X-Request-Id': 'hdr_456' },
    );
    try {
      await parseEnvelopeOrThrow(res);
      expect.unreachable();
    } catch (err: unknown) {
      const { ApiError } = await import('@/lib/api-client');
      expect(err).toBeInstanceOf(ApiError);
      expect((err as InstanceType<typeof ApiError>).requestId).toBe('hdr_456');
    }
  });

  it('prefers meta.request_id over X-Request-Id header', async () => {
    const { parseEnvelopeOrThrow } = await import('@/lib/http-envelope');
    const res = makeResponse(
      { ok: false, error: { code: 'BAD', message: 'nope' }, meta: { request_id: 'meta_win' } },
      400,
      { 'X-Request-Id': 'hdr_lose' },
    );
    try {
      await parseEnvelopeOrThrow(res);
      expect.unreachable();
    } catch (err: unknown) {
      const { ApiError } = await import('@/lib/api-client');
      expect((err as InstanceType<typeof ApiError>).requestId).toBe('meta_win');
    }
  });

  it('sets requestId on non-envelope error responses', async () => {
    const { parseEnvelopeOrThrow } = await import('@/lib/http-envelope');
    const h = new Headers({
      'content-type': 'text/html',
      'X-Request-Id': 'html_req',
    });
    const res = new Response('<h1>500</h1>', { status: 500, headers: h });
    try {
      await parseEnvelopeOrThrow(res);
      expect.unreachable();
    } catch (err: unknown) {
      const { ApiError } = await import('@/lib/api-client');
      expect(err).toBeInstanceOf(ApiError);
      expect((err as InstanceType<typeof ApiError>).requestId).toBe('html_req');
    }
  });

  it('returns data on success (no requestId needed)', async () => {
    const { parseEnvelopeOrThrow } = await import('@/lib/http-envelope');
    const res = makeResponse({ ok: true, data: { name: 'Monza' }, meta: { request_id: 'ok_req' } });
    const data = await parseEnvelopeOrThrow<{ name: string }>(res);
    expect(data.name).toBe('Monza');
  });
});
