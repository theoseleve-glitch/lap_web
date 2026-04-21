import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { SessionContract } from '@/types/contracts';
import { fetchSessionContract } from './session-contracts-client';

const mockSession: SessionContract = {
  session_id: 'abc',
  session_start: '2026-04-19T12:00:00Z',
  duration_s: 600,
  workspace_id: 'ws-1',
  source: 'real_life',
  driver: { driver_id: 1, name: 'Test' },
  track: { track_id: 1, name: 'Monza' },
  vehicle: {},
  capabilities: { channels: ['gps', 'lat_g', 'lon_g'] },
};

describe('fetchSessionContract', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () =>
      new Response(JSON.stringify({ ok: true, data: { session: mockSession, coaching: null, optimizer: null } }),
        { status: 200, headers: { 'content-type': 'application/json' } }),
    ));
  });

  it('returns the parsed envelope for a valid contract response', async () => {
    const result = await fetchSessionContract('abc');
    expect(result.session.session_id).toBe('abc');
    expect(result.session.source).toBe('real_life');
    expect(result.coaching).toBeNull();
    expect(result.optimizer).toBeNull();
  });

  it('throws if session payload is missing required fields', async () => {
    vi.stubGlobal('fetch', vi.fn(async () =>
      new Response(JSON.stringify({ ok: true, data: { session: {} } }),
        { status: 200, headers: { 'content-type': 'application/json' } }),
    ));
    await expect(fetchSessionContract('abc')).rejects.toThrow(/invalid session contract/i);
  });
});
