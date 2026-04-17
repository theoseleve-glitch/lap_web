'use client';

/**
 * AppShell — the global app frame.
 *
 * Premium motorsport telemetry console shell:
 *   - Sidebar: near-black surface, gold active accent, grouped nav sections
 *   - Top bar: search + unit toggle + upload CTA
 *   - Main content: full-width, breadcrumb, billing banner
 */

import { type ReactNode, useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { QueryProvider } from '@/providers/query-provider';
import { AppFooter } from '@/components/ui/AppFooter';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { DiagnosticsOverlay } from '@/components/dev/DiagnosticsOverlay';
import { BillingStateBanner } from '@/components/billing/BillingStateBanner';
import { Breadcrumb } from '@/components/ui/Breadcrumb';
import { OfflineBanner } from '@/components/shared/OfflineBanner';
import { KeyboardShortcuts } from '@/components/app/KeyboardShortcuts';
import { CommandPalette } from '@/components/app/CommandPalette';
import { UndoToastContainer } from '@/components/ui/UndoToast';
import { UnitToggle } from '@/components/app/UnitToggle';
import { LapMonogram } from '@/components/shared/LapMonogram';
import { logout } from '@/lib/auth';
import { useGamificationStore } from '@/stores/gamification-store';
import { useDriverProgress } from '@/hooks/useDriverProgress';
import { AchievementUnlockOverlay } from '@/components/app/gamification';
import AchievementToast from '@/components/app/gamification/AchievementToast';
import LevelUpModal from '@/components/app/gamification/LevelUpModal';

const SIDEBAR_KEY = 'lap-sidebar-collapsed';

interface NavItem { href: string; label: string; icon: string; }
interface NavGroup { label: string; items: NavItem[]; }

const navGroups: NavGroup[] = [
  {
    label: 'Coach',
    items: [
      { href: '/app/dashboard', label: 'Dashboard', icon: '◉' },
      { href: '/app/sessions', label: 'Sessions', icon: '◎' },
      { href: '/app/compare', label: 'Compare', icon: '⟺' },
      { href: '/app/visualize', label: 'Visualization', icon: '◆' },
      { href: '/app/leaderboard', label: 'Leaderboard', icon: '★' },
    ],
  },
  {
    label: 'Strategy',
    items: [
      { href: '/app/race-strategy', label: 'Race Strategy', icon: '⚑' },
    ],
  },
  {
    label: 'Analysis',
    items: [
      { href: '/app/bundles', label: 'Session Analysis', icon: '◇' },
    ],
  },
  {
    label: 'Data',
    items: [
      { href: '/app/tracks', label: 'Tracks', icon: '◌' },
      { href: '/app/drivers', label: 'Drivers', icon: '◈' },
      { href: '/app/karts', label: 'Karts', icon: '⊞' },
      { href: '/app/weekends', label: 'Weekends', icon: '▣' },
    ],
  },
];

/* ── Sidebar surface tokens ───────────────────────────────── */

const SIDEBAR_STYLE: React.CSSProperties = {
  background: 'linear-gradient(180deg, #070707 0%, #030303 100%)',
  borderRight: '1px solid rgba(255,255,255,0.04)',
};

const TOPBAR_STYLE: React.CSSProperties = {
  background: 'rgba(0,0,0,0.85)',
  backdropFilter: 'blur(12px)',
  borderBottom: '1px solid rgba(255,255,255,0.04)',
};

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(SIDEBAR_KEY);
    if (stored === '1') setCollapsed(true);
  }, []);

  const toggle = () => {
    setCollapsed((prev) => {
      localStorage.setItem(SIDEBAR_KEY, prev ? '0' : '1');
      return !prev;
    });
  };

  return (
    <QueryProvider>
    <div className="flex min-h-screen">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:px-4 focus:py-2 focus:bg-gold focus:text-white focus:font-telemetry focus:text-sm focus:rounded"
      >
        Skip to content
      </a>

      {/* ═══ SIDEBAR ═══════════════════════════════════════════ */}
      <aside
        className={`${collapsed ? 'w-14' : 'w-56'} flex flex-col shrink-0 overflow-hidden transition-all duration-300 ease-out`}
        style={SIDEBAR_STYLE}
      >
        {/* Logo + collapse toggle */}
        <div className="px-4 py-4 flex items-center justify-between gap-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
          <Link href="/" className="flex items-center gap-2" title="LAP">
            <LapMonogram size={collapsed ? 22 : 26} color="currentColor" className="text-chalk shrink-0" />
            {!collapsed && (
              <span className="font-monument text-lg text-chalk tracking-tight">LAP</span>
            )}
          </Link>
          <button
            type="button"
            onClick={toggle}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="w-6 h-6 flex items-center justify-center rounded text-steel/50 hover:text-chalk hover:bg-steel/8 transition-colors shrink-0"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              {collapsed
                ? <polyline points="5,3 9,7 5,11" />
                : <polyline points="9,3 5,7 9,11" />
              }
            </svg>
          </button>
        </div>

        {/* Navigation */}
        <nav aria-label="Main navigation" className="flex-1 py-3 overflow-y-auto">
          {navGroups.map((group, gi) => (
            <div key={group.label} role="group" aria-label={group.label}>
              {gi > 0 && <div className="mx-4 my-2 h-px bg-steel/6" />}
              {!collapsed && (
                <p className="px-4 pt-2 pb-1 text-[9px] font-telemetry tracking-[0.2em] uppercase text-steel/40">
                  {group.label}
                </p>
              )}
              {group.items.map((item) => {
                const isActive = pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    title={collapsed ? item.label : undefined}
                    aria-current={isActive ? 'page' : undefined}
                    className={`flex items-center ${collapsed ? 'justify-center mx-1.5 px-0' : 'gap-3 mx-2 px-3'} py-2 text-[13px] rounded-md transition-all ${
                      isActive
                        ? 'text-gold bg-gold/8 border-l-2 border-gold/60 rounded-l-none'
                        : 'text-steel/70 hover:text-chalk hover:bg-steel/6 border-l-2 border-transparent'
                    }`}
                  >
                    <span className={`${collapsed ? 'w-6 text-center' : 'w-5 text-center'} font-telemetry shrink-0 text-[12px]`} aria-hidden="true">
                      {item.icon}
                    </span>
                    {!collapsed && <span className="font-body whitespace-nowrap">{item.label}</span>}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        {/* XP mini-indicator */}
        <SidebarXPIndicator collapsed={collapsed} />

        {/* Footer nav */}
        <div className="py-2" style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
          <Link
            href="/help"
            title={collapsed ? 'Help' : undefined}
            className={`flex items-center ${collapsed ? 'justify-center mx-1.5 px-0' : 'gap-3 mx-2 px-3'} py-2 text-[13px] rounded-md transition-colors text-steel/60 hover:text-chalk hover:bg-steel/6 border-l-2 border-transparent`}
          >
            <span className={`${collapsed ? 'w-6 text-center' : 'w-5 text-center'} font-telemetry shrink-0 text-[12px]`} aria-hidden="true">?</span>
            {!collapsed && <span className="font-body">Help</span>}
          </Link>
          <Link
            href="/app/account"
            title={collapsed ? 'Account' : undefined}
            aria-current={pathname.startsWith('/app/account') ? 'page' : undefined}
            className={`flex items-center ${collapsed ? 'justify-center mx-1.5 px-0' : 'gap-3 mx-2 px-3'} py-2 text-[13px] rounded-md transition-all ${
              pathname.startsWith('/app/account')
                ? 'text-gold bg-gold/8 border-l-2 border-gold/60 rounded-l-none'
                : 'text-steel/60 hover:text-chalk hover:bg-steel/6 border-l-2 border-transparent'
            }`}
          >
            <span className={`${collapsed ? 'w-6 text-center' : 'w-5 text-center'} font-telemetry shrink-0 text-[12px]`} aria-hidden="true">◉</span>
            {!collapsed && <span className="font-body">Account</span>}
          </Link>
          <button
            type="button"
            title={collapsed ? 'Log out' : undefined}
            onClick={() => { logout().then(() => { window.location.href = '/login'; }); }}
            className={`flex items-center ${collapsed ? 'justify-center mx-1.5 px-0' : 'gap-3 mx-2 px-3'} py-2 text-[13px] rounded-md transition-colors text-steel/40 hover:text-safety-red hover:bg-safety-red/5 w-full border-l-2 border-transparent`}
          >
            <span className={`${collapsed ? 'w-6 text-center' : 'w-5 text-center'} font-telemetry shrink-0 text-[12px]`} aria-hidden="true">→</span>
            {!collapsed && <span className="font-body">Log out</span>}
          </button>
        </div>
      </aside>

      {/* ═══ MAIN CONTENT ══════════════════════════════════════ */}
        <AuthGuard>
          <main id="main-content" className="flex-1 flex flex-col overflow-y-auto bg-asphalt">
            <OfflineBanner />
            {/* Top bar */}
            <div className="sticky top-0 z-30 flex items-center justify-end gap-3 px-6 py-2" style={TOPBAR_STYLE}>
              <button
                type="button"
                onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }))}
                className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg border border-steel/10 text-steel/50 text-xs font-telemetry hover:border-steel/20 hover:text-steel transition-colors"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="opacity-60">
                  <circle cx="11" cy="11" r="8" />
                  <line x1="21" y1="21" x2="16.65" y2="16.65" />
                </svg>
                <span>Search</span>
                <kbd className="font-telemetry text-[9px] text-steel/40 border border-steel/10 rounded px-1 py-0.5 leading-none">⌘K</kbd>
              </button>
              <UnitToggle />
              <Link
                href="/app/sessions/upload"
                className="inline-flex items-center gap-1.5 px-4 py-1.5 bg-gold text-white font-telemetry text-[11px] font-semibold uppercase tracking-[0.08em] rounded-lg hover:bg-gold/85 transition-colors"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19" />
                  <line x1="5" y1="12" x2="19" y2="12" />
                </svg>
                Upload
              </Link>
            </div>
            <div className="max-w-[1600px] mx-auto px-6 lg:px-12 xl:px-16 py-6">
              <Breadcrumb />
              <BillingStateBanner />
              {children}
            </div>
            <AppFooter />
          </main>
        </AuthGuard>
        {process.env.NODE_ENV === 'development' && <DiagnosticsOverlay />}
        <KeyboardShortcuts />
        <CommandPalette />
        <UndoToastContainer />
        <GlobalGamificationOverlays />
    </div>
    </QueryProvider>
  );
}

/* ── Sidebar XP mini-indicator ──────────────────────────────────────────── */

function SidebarXPIndicator({ collapsed }: { collapsed: boolean }) {
  const { level, totalXp, xpForCurrentLevel, xpForNextLevel } = useDriverProgress();

  const xpCurrent = xpForCurrentLevel;
  const xpNext = xpForNextLevel;
  const range = Math.max(1, xpNext - xpCurrent);
  const pct = Math.min(100, Math.max(0, ((totalXp - xpCurrent) / range) * 100));

  // SVG ring parameters
  const R = 14;
  const C = Math.PI * 2 * R;
  const offset = C - (pct / 100) * C;

  return (
    <div className="px-3 py-2" style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
      <div className={`flex items-center ${collapsed ? 'justify-center' : 'gap-3'}`}>
        {/* XP ring */}
        <div className="relative w-9 h-9 shrink-0">
          <svg width="36" height="36" viewBox="0 0 36 36" className="transform -rotate-90">
            <circle cx="18" cy="18" r={R} fill="none" stroke="rgba(148,148,148,0.1)" strokeWidth="2.5" />
            <circle
              cx="18" cy="18" r={R} fill="none"
              stroke="#C9A84C" strokeWidth="2.5"
              strokeDasharray={C} strokeDashoffset={offset}
              strokeLinecap="round"
              className="transition-all duration-500"
            />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center text-[9px] font-monument text-gold">
            {level}
          </span>
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <div className="text-[10px] font-telemetry text-steel/60 uppercase tracking-[0.15em]">
              Level {level}
            </div>
            <div className="text-[9px] font-telemetry text-steel/40">
              {totalXp} XP
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Global gamification overlays (rendered once, triggered from anywhere) ── */

function GlobalGamificationOverlays() {
  const {
    achievementToast,
    dismissAchievementToast,
    achievementOverlay,
    dismissAchievementOverlay,
    levelUp,
    dismissLevelUp,
  } = useGamificationStore();

  return (
    <>
      {/* Achievement toast — slides in from top-right, auto-dismisses after 5s */}
      <AchievementToast
        achievement={achievementToast}
        onDismiss={dismissAchievementToast}
      />

      {/* Achievement unlock overlay — fullscreen celebration */}
      <AchievementUnlockOverlay
        achievement={achievementOverlay}
        onDismiss={dismissAchievementOverlay}
      />

      {/* Level-up modal — XP arc animation */}
      {levelUp && (
        <LevelUpModal
          oldLevel={levelUp.oldLevel}
          newLevel={levelUp.newLevel}
          totalXp={levelUp.totalXp}
          sessionXp={levelUp.sessionXp}
          onClose={dismissLevelUp}
        />
      )}
    </>
  );
}
