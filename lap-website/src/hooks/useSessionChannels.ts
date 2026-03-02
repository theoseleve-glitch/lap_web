/**
 * useSessionChannels.ts — Fetch available telemetry channels for a session.
 *
 * Queries the /sessions/:id/channels endpoint to discover which data channels
 * are available, enabling conditional chart rendering in AnalyticsTab.
 */
'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api-client';

interface ChannelAvailability {
  throttle: boolean;
  brake: boolean;
  steering: boolean;
  rpm: boolean;
  gear: boolean;
  tire_temp: boolean;
  tire_pressure: boolean;
  brake_temp: boolean;
  wheel_slip: boolean;
  fuel: boolean;
}

interface UseSessionChannelsResult {
  channels: ChannelAvailability;
  tier: number;
  loading: boolean;
  error: string | null;
}

const EMPTY_CHANNELS: ChannelAvailability = {
  throttle: false,
  brake: false,
  steering: false,
  rpm: false,
  gear: false,
  tire_temp: false,
  tire_pressure: false,
  brake_temp: false,
  wheel_slip: false,
  fuel: false,
};

export function useSessionChannels(sessionId: string): UseSessionChannelsResult {
  const [channels, setChannels] = useState<ChannelAvailability>(EMPTY_CHANNELS);
  const [tier, setTier] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    apiFetch<{ available: boolean; channels?: ChannelAvailability; tier?: number }>(
      `/sessions/${encodeURIComponent(sessionId)}/channels`,
    )
      .then((data) => {
        if (cancelled) return;
        if (data.available === false) {
          setChannels(EMPTY_CHANNELS);
          setTier(0);
        } else {
          setChannels(data.channels ?? EMPTY_CHANNELS);
          setTier(data.tier ?? 0);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load channels');
        setChannels(EMPTY_CHANNELS);
        setTier(0);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  return { channels, tier, loading, error };
}
