/**
 * Zustand store for plan entitlements.
 *
 * Cached outside the React tree so it's available in API interceptors,
 * middleware, and server-side code. The store is populated by
 * useEntitlements() on auth restore.
 */
import { create } from 'zustand';

export interface Entitlements {
  planTier: 'demo' | 'racer' | 'world-class' | 'b2b';
  subscriptionStatus: 'free' | 'active' | 'past_due' | 'canceled' | 'trialing';
  analysesPerMonth: number | null;
  analysesUsed: number;
  analysesRemaining: number | null;
  uploadVolumeMbPerMonth: number | null;
  uploadVolumeMbUsed: number;
  uploadVolumeMbRemaining: number | null;
  apiAccess: boolean;
  comparisonEnabled: boolean;
  coachingPlansEnabled: boolean;
  visualizationEnabled: boolean;
  badgeShareCard: boolean;
  gamification: boolean;
  raceStrategyLimit: '4h_basic' | '24h_complex' | 'unlimited' | null;
  raceStrategyMaxDurationS: number | null;
  raceStrategyParams: 'basic' | 'complex';
  optimizerModes: string[];
  liveMonitoring: boolean;
  exportFormats: string[];
  telemetryRetentionDays: number;
  maxUploadSizeMb: number;
  maxSessionDataMb: number;
  maxConcurrentJobs: number;
  rateMultiplier: number;
  deviceSync: boolean;
  autoAnalyzeOnSync: boolean;
  maxLinkedDevices: number;
}

interface EntitlementsState {
  entitlements: Entitlements | null;
  setEntitlements: (e: Entitlements | null) => void;
  clear: () => void;
}

export const useEntitlementsStore = create<EntitlementsState>((set) => ({
  entitlements: null,
  setEntitlements: (e) => set({ entitlements: e }),
  clear: () => set({ entitlements: null }),
}));

// ── Feature gate helpers (usable outside React) ─────────────────────

/** Map of feature keys to the entitlement property that controls them. */
const FEATURE_MAP: Record<string, keyof Entitlements> = {
  comparison: 'comparisonEnabled',
  api_access: 'apiAccess',
  coaching_plans: 'coachingPlansEnabled',
  visualization: 'visualizationEnabled',
  live_monitoring: 'liveMonitoring',
  gamification: 'gamification',
  device_sync: 'deviceSync',
  auto_analyze_on_sync: 'autoAnalyzeOnSync',
};

/** Which tier unlocks each feature (for upgrade prompts). */
const UPGRADE_TIERS: Record<string, { tier: string; url: string }> = {
  comparison: { tier: 'racer', url: '/pricing?plan=RACER' },
  api_access: { tier: 'world-class', url: '/pricing?plan=WORLD-CLASS' },
  coaching_plans: { tier: 'racer', url: '/pricing?plan=RACER' },
  visualization: { tier: 'racer', url: '/pricing?plan=RACER' },
  gamification: { tier: 'racer', url: '/pricing?plan=RACER' },
  live_monitoring: { tier: 'racer', url: '/pricing?plan=RACER' },
  export_pdf: { tier: 'racer', url: '/pricing?plan=RACER' },
  race_strategy_complex: { tier: 'racer', url: '/pricing?plan=RACER' },
  race_strategy_full: { tier: 'world-class', url: '/pricing?plan=WORLD-CLASS' },
  optimizer_performance: { tier: 'world-class', url: '/pricing?plan=WORLD-CLASS' },
};

/**
 * Check if the current user can use a feature.
 * Returns true if no entitlements are loaded (fail open for UX).
 */
export function canUseFeature(feature: string): boolean {
  const ent = useEntitlementsStore.getState().entitlements;
  if (!ent) return false; // Fail closed — block until entitlements are loaded

  // Boolean features
  const prop = FEATURE_MAP[feature];
  if (prop) return Boolean(ent[prop]);

  // PDF export: check export_formats
  if (feature === 'export_pdf') {
    return ent.exportFormats.includes('pdf');
  }

  // Race strategy tiers
  if (feature === 'race_strategy_full') {
    return ent.raceStrategyLimit === 'unlimited';
  }
  if (feature === 'race_strategy_complex') {
    return ent.raceStrategyLimit === '24h_complex' || ent.raceStrategyLimit === 'unlimited';
  }

  // Optimizer mode check
  if (feature === 'optimizer_performance') {
    return ent.optimizerModes?.includes('performance') ?? false;
  }

  return true; // Unknown features are allowed
}

/**
 * Get remaining quota for a meter key.
 * Returns null if unlimited or entitlements not loaded.
 */
export function getRemainingQuota(key: string): number | null {
  const ent = useEntitlementsStore.getState().entitlements;
  if (!ent) return null;

  if (key === 'analyses') return ent.analysesRemaining;
  if (key === 'upload_volume_mb') return ent.uploadVolumeMbRemaining;
  return null;
}

/**
 * Check if a feature requires an upgrade.
 * Returns null if feature is available or entitlements not loaded.
 */
export function getUpgradeInfo(
  feature: string,
): { required: boolean; tier: string; url: string } | null {
  if (canUseFeature(feature)) return null;
  const info = UPGRADE_TIERS[feature];
  if (!info) return null;
  return { required: true, tier: info.tier, url: info.url };
}
