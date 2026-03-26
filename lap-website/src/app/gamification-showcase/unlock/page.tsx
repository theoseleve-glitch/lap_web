'use client';

import Link from 'next/link';
import { BadgeHex } from '@/components/app/gamification';

export default function AchievementUnlockShowcasePage() {
  return (
    <main
      id="main-content"
      className="relative min-h-screen overflow-hidden bg-black text-chalk"
    >
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(255,212,0,0.12),transparent_22%),radial-gradient(circle_at_15%_15%,rgba(182,255,46,0.14),transparent_24%),linear-gradient(180deg,#040404_0%,#090909_42%,#000_100%)]" />

      <div className="relative mx-auto flex min-h-screen w-full max-w-6xl flex-col px-6 py-10 lg:px-10">
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-[28px] border border-white/10 bg-white/[0.03] px-6 py-5">
          <div>
            <p className="font-telemetry text-[11px] uppercase tracking-[0.24em] text-acid-green/80">
              Reward State
            </p>
            <h1 className="mt-2 font-monument text-2xl text-chalk">Achievement Unlock Overlay</h1>
          </div>
          <Link
            href="/gamification-showcase"
            className="inline-flex min-h-[44px] items-center rounded-full border border-white/15 px-4 py-2 font-body text-sm text-chalk transition-colors hover:border-acid-green/50 hover:text-acid-green"
          >
            Back to catalogue
          </Link>
        </div>

        <div className="relative mt-8 flex flex-1 items-center justify-center overflow-hidden rounded-[32px] border border-white/10 bg-[linear-gradient(180deg,rgba(16,16,16,0.92),rgba(6,6,6,0.98))] p-8 shadow-[0_40px_120px_-64px_rgba(255,212,0,0.35)]">
          <div className="absolute inset-0 bg-black/65" />
          <div className="absolute left-1/2 top-1/2 h-72 w-72 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(circle,rgba(255,215,0,0.18),transparent_62%)] blur-3xl" />

          <div className="relative z-10 w-full max-w-md rounded-[28px] border border-[#FFD700]/25 bg-[linear-gradient(135deg,#141414_0%,#000_100%)] px-8 py-10 text-center shadow-[0_32px_100px_-40px_rgba(255,215,0,0.35)]">
            <div className="flex justify-center">
              <BadgeHex icon="trophy" tier="gold" size={136} glow animate />
            </div>

            <p className="mt-6 font-telemetry text-[11px] uppercase tracking-[0.24em] text-[#FFD700]">
              Achievement Unlocked
            </p>
            <h2 className="mt-3 font-monument text-2xl text-chalk">Telemetry Prodigy</h2>
            <p className="mt-4 font-body text-sm leading-6 text-steel">
              Unlock after stacking pace, consistency, and execution gains in one session.
            </p>

            <div className="mt-7 flex justify-center gap-3">
              <span className="h-2.5 w-2.5 rounded-full bg-[#CD7F32]" />
              <span className="h-2.5 w-2.5 rounded-full bg-[#C0C0C0]" />
              <span className="h-2.5 w-2.5 rounded-full bg-[#FFD700] shadow-[0_0_14px_rgba(255,215,0,0.6)]" />
            </div>

            <button
              type="button"
              className="mt-8 inline-flex min-h-[44px] items-center justify-center rounded-xl border border-[#FFD700]/40 px-7 py-3 font-telemetry text-sm uppercase tracking-[0.18em] text-[#FFD700]"
            >
              Continue
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}
