'use client';

import { create } from 'zustand';
import { api } from '@/lib/api-client';
import type { Entitlements } from '@/lib/entitlements-store';

export interface UserPreferences {
  language: string;
  timezone: string;
  units: 'metric' | 'imperial';
  speed_unit: 'kmh' | 'mph' | 'ms';
  notifications: {
    report_ready: boolean;
    billing_alerts: boolean;
    product_updates: boolean;
    weekly_digest: boolean;
  };
}

interface AccountState {
  entitlements: Entitlements | null;
  preferences: UserPreferences | null;
  loading: boolean;

  fetchEntitlements: () => Promise<void>;
  updatePreferences: (partial: Partial<UserPreferences>) => Promise<void>;
  setPreferences: (prefs: UserPreferences) => void;
  reset: () => void;
}

export const useAccountStore = create<AccountState>((set, get) => ({
  entitlements: null,
  preferences: null,
  loading: false,

  fetchEntitlements: async () => {
    set({ loading: true });
    try {
      const data = await api.get<{ entitlements: Entitlements }>('/me');
      set({ entitlements: data.entitlements, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  updatePreferences: async (partial) => {
    const current = get().preferences;
    const merged = { ...current, ...partial } as UserPreferences;
    set({ preferences: merged });

    await api.put<UserPreferences>('/account/preferences', partial);
  },

  setPreferences: (prefs) => set({ preferences: prefs }),

  reset: () => set({ entitlements: null, preferences: null, loading: false }),
}));
