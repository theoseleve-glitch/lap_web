import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock consent — return true by default
vi.mock('@/lib/consent', () => ({
  hasAnalyticsConsent: vi.fn(() => true),
}));

// Mock api-client
const mockPost = vi.fn().mockResolvedValue({ accepted: 1 });
vi.mock('@/lib/api-client', () => ({
  api: { post: (...args: unknown[]) => mockPost(...args) },
}));

describe('useTrackEvent', () => {
  beforeEach(() => {
    vi.resetModules();
    mockPost.mockClear();
  });

  afterEach(() => {
    vi.resetModules();
  });

  it('batches events and flushes', async () => {
    const { trackEvent, _flushNow } = await import('@/hooks/useTrackEvent');

    trackEvent('test.event1', { foo: 'bar' }, '/app/dashboard');
    trackEvent('test.event2', { baz: 1 }, '/app/sessions');

    await _flushNow();

    expect(mockPost).toHaveBeenCalledTimes(1);
    const [path, body] = mockPost.mock.calls[0] as [string, { events: unknown[] }];
    expect(path).toBe('/events');
    expect(body.events).toHaveLength(2);
    expect((body.events[0] as { event: string }).event).toBe('test.event1');
    expect((body.events[1] as { event: string }).event).toBe('test.event2');
  });

  it('does not send when consent is denied', async () => {
    const { hasAnalyticsConsent } = await import('@/lib/consent');
    vi.mocked(hasAnalyticsConsent).mockReturnValue(false);

    const { trackEvent, _flushNow } = await import('@/hooks/useTrackEvent');

    trackEvent('test.no_consent', {}, '/app/dashboard');

    await _flushNow();

    expect(mockPost).not.toHaveBeenCalled();
  });
});
