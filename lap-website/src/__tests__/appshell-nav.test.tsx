/**
 * Regression guard: the "Race Strategy" nav link must be present in the
 * sidebar. It was silently dropped from AppShell during an unrelated
 * launch-UI cleanup — see the W2 endurance-finish plan.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('next/navigation', () => ({
  usePathname: () => '/app/dashboard',
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock('@/providers/query-provider', () => ({
  QueryProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('@/components/auth/AuthGuard', () => ({
  AuthGuard: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('@/components/dev/DiagnosticsOverlay', () => ({ DiagnosticsOverlay: () => null }));
vi.mock('@/components/billing/BillingStateBanner', () => ({ BillingStateBanner: () => null }));
vi.mock('@/components/shared/OfflineBanner', () => ({ OfflineBanner: () => null }));
vi.mock('@/components/app/KeyboardShortcuts', () => ({ KeyboardShortcuts: () => null }));
vi.mock('@/components/app/CommandPalette', () => ({ CommandPalette: () => null }));
vi.mock('@/hooks/useDriverProgress', () => ({ useDriverProgress: () => ({}) }));
vi.mock('@/stores/gamification-store', () => ({
  useGamificationStore: () => ({
    achievementOverlay: null, levelUp: null, floatingPoints: [],
    dismissAchievementOverlay: vi.fn(), dismissLevelUp: vi.fn(),
  }),
}));

import { AppShell } from '@/app/app/AppShell';

// AppShell reads the sidebar-collapsed key from localStorage on mount; this
// jsdom config doesn't expose a working one, so provide a minimal in-memory stub.
const _lsStore: Record<string, string> = {};
vi.stubGlobal('localStorage', {
  getItem: (k: string) => (k in _lsStore ? _lsStore[k] : null),
  setItem: (k: string, v: string) => { _lsStore[k] = String(v); },
  removeItem: (k: string) => { delete _lsStore[k]; },
  clear: () => { Object.keys(_lsStore).forEach((k) => delete _lsStore[k]); },
});

describe('AppShell sidebar nav', () => {
  it('includes a Race Strategy link', () => {
    render(<AppShell><div>content</div></AppShell>);
    const link = screen.getByRole('link', { name: /race strategy/i });
    expect(link).toHaveAttribute('href', '/app/race-strategy');
  });
});
