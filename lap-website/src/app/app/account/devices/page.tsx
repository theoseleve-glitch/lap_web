'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api-client';
import { useEntitlementsStore } from '@/lib/entitlements-store';
import { UpgradeBanner } from '@/components/billing/UpgradeBanner';
/* Icons replaced with Unicode — no icon library installed */

/* ── Types ────────────────────────────────────────────────── */

interface Device {
  id: number;
  device_name: string | null;
  status: string;
  last_seen_at: string | null;
  confirmed_at: string | null;
}

/* ── Page ─────────────────────────────────────────────────── */

export default function DevicesPage() {
  const ents = useEntitlementsStore((s) => s.entitlements);
  const canSync = ents?.deviceSync ?? false;
  const maxDevices = ents?.maxLinkedDevices ?? 0;

  const queryClient = useQueryClient();
  const [showLinkModal, setShowLinkModal] = useState(false);
  const [code, setCode] = useState('');
  const [linkError, setLinkError] = useState('');

  const { data: devices = [], isLoading } = useQuery<Device[]>({
    queryKey: ['devices'],
    queryFn: async () => {
      const res = await apiFetch('/api/v1/devices');
      if (!res.ok) throw new Error(res.error || 'Failed to load devices');
      return res.data;
    },
    enabled: canSync,
  });

  const confirmMutation = useMutation({
    mutationFn: async (pairingCode: string) => {
      const res = await apiFetch('/api/v1/devices/confirm', {
        method: 'POST',
        body: JSON.stringify({ code: pairingCode }),
      });
      if (!res.ok) throw new Error(res.error || 'Failed to link device');
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['devices'] });
      setShowLinkModal(false);
      setCode('');
      setLinkError('');
    },
    onError: (err: Error) => {
      setLinkError(err.message);
    },
  });

  const revokeMutation = useMutation({
    mutationFn: async (deviceId: number) => {
      const res = await apiFetch(`/api/v1/devices/${deviceId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(res.error || 'Failed to unlink device');
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['devices'] });
    },
  });

  /* ── Gated ──────────────────────────────────────────────── */

  if (!canSync) {
    return (
      <div className="max-w-2xl mx-auto py-12 px-6">
        <h1 className="font-monument text-2xl text-chalk mb-6">Linked Devices</h1>
        <UpgradeBanner
          feature="device_sync"
          message="Device sync requires a Racer plan or higher. Link your Lap Coach Logger to automatically upload sessions."
        />
      </div>
    );
  }

  /* ── Render ─────────────────────────────────────────────── */

  return (
    <div className="max-w-2xl mx-auto py-12 px-6">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="font-monument text-2xl text-chalk">Linked Devices</h1>
          <p className="font-telemetry text-sm text-steel mt-1">
            {devices.length} of {maxDevices} devices linked
          </p>
        </div>
        {devices.length < maxDevices && (
          <button
            onClick={() => setShowLinkModal(true)}
            className="inline-flex items-center gap-2 bg-gold text-white font-telemetry text-sm uppercase tracking-wider px-5 py-2.5 rounded hover:bg-gold/80 transition-colors"
          >
            + Link a Device
          </button>
        )}
      </div>

      {/* Device List */}
      {isLoading ? (
        <div className="text-steel font-body text-sm py-8 text-center">Loading devices...</div>
      ) : devices.length === 0 ? (
        <div className="bg-concrete rounded-lg border border-steel/10 p-8 text-center">
          <span className="text-4xl text-steel/40 block mx-auto mb-4">🖥</span>
          <p className="font-body text-steel mb-4">No devices linked yet.</p>
          <p className="font-body text-sm text-steel/60 mb-6">
            Open the Lap Coach Logger on your PC, go to Settings → Account, and enter the code shown here.
          </p>
          <button
            onClick={() => setShowLinkModal(true)}
            className="inline-flex items-center gap-2 bg-gold text-white font-telemetry text-sm uppercase tracking-wider px-5 py-2.5 rounded hover:bg-gold/80 transition-colors"
          >
            + Link a Device
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {devices.map((device) => (
            <div
              key={device.id}
              className="bg-concrete rounded-lg border border-steel/10 p-5 flex items-center justify-between"
            >
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-lg bg-steel/10 flex items-center justify-center">
                  <span className="text-chalk">🖥</span>
                </div>
                <div>
                  <p className="font-monument text-sm text-chalk">
                    {device.device_name || 'Unknown Device'}
                  </p>
                  <div className="flex items-center gap-3 mt-1">
                    {device.last_seen_at ? (
                      <span className="inline-flex items-center gap-1 font-telemetry text-xs text-acid-green">
                        ● Last seen {new Date(device.last_seen_at).toLocaleDateString()}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 font-telemetry text-xs text-steel">
                        ○ Never connected
                      </span>
                    )}
                    {device.confirmed_at && (
                      <span className="font-telemetry text-xs text-steel">
                        Linked {new Date(device.confirmed_at).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <button
                onClick={() => revokeMutation.mutate(device.id)}
                disabled={revokeMutation.isPending}
                className="border border-safety-red/40 text-safety-red font-telemetry text-xs uppercase tracking-wider px-3 py-1.5 rounded hover:bg-safety-red/10 transition-colors disabled:opacity-50"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Link Modal */}
      {showLinkModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-asphalt/80 backdrop-blur-sm">
          <div className="bg-concrete rounded-lg border border-steel/20 p-8 w-full max-w-md mx-4">
            <h2 className="font-monument text-xl text-chalk mb-2">Link a Device</h2>
            <p className="font-body text-sm text-steel mb-6">
              Enter the 6-character pairing code shown in the Lap Coach Logger on your PC.
            </p>
            <input
              type="text"
              value={code}
              onChange={(e) => {
                setCode(e.target.value.toUpperCase());
                setLinkError('');
              }}
              placeholder="XXX-XXX"
              maxLength={7}
              className="w-full bg-asphalt border border-steel/30 rounded px-4 py-3 font-telemetry text-lg text-chalk text-center tracking-[0.3em] placeholder:text-steel/30 focus:border-gold focus:outline-none"
            />
            {linkError && (
              <p className="font-body text-sm text-safety-red mt-2">{linkError}</p>
            )}
            <div className="flex gap-3 mt-6">
              <button
                onClick={() => { setShowLinkModal(false); setCode(''); setLinkError(''); }}
                className="flex-1 border border-steel/30 text-chalk font-telemetry text-sm uppercase tracking-wider px-4 py-2.5 rounded hover:bg-concrete transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => confirmMutation.mutate(code)}
                disabled={code.length < 7 || confirmMutation.isPending}
                className="flex-1 bg-gold text-white font-telemetry text-sm uppercase tracking-wider px-4 py-2.5 rounded hover:bg-gold/80 transition-colors disabled:opacity-50"
              >
                {confirmMutation.isPending ? 'Linking...' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
