'use client';

import Link from 'next/link';

export default function LevelUpShowcasePage() {
  return (
    <main
      id="main-content"
      className="relative min-h-screen overflow-hidden bg-black text-chalk"
    >
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(182,255,46,0.16),transparent_26%),linear-gradient(180deg,#050505_0%,#0A0A0A_45%,#000_100%)]" />

      <div className="relative mx-auto flex min-h-screen w-full max-w-6xl flex-col px-6 py-10 lg:px-10">
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-[28px] border border-white/10 bg-white/[0.03] px-6 py-5">
          <div>
            <p className="font-telemetry text-[11px] uppercase tracking-[0.24em] text-acid-green/80">
              Reward State
            </p>
            <h1 className="mt-2 font-monument text-2xl text-chalk">Level-Up Modal And Toast</h1>
          </div>
          <Link
            href="/gamification-showcase"
            className="inline-flex min-h-[44px] items-center rounded-full border border-white/15 px-4 py-2 font-body text-sm text-chalk transition-colors hover:border-acid-green/50 hover:text-acid-green"
          >
            Back to catalogue
          </Link>
        </div>

        <div className="relative mt-8 flex flex-1 items-center justify-center overflow-hidden rounded-[32px] border border-white/10 bg-[linear-gradient(180deg,rgba(16,16,16,0.92),rgba(6,6,6,0.98))] p-8 shadow-[0_40px_120px_-64px_rgba(182,255,46,0.4)]">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_40%,rgba(34,197,94,0.09),transparent_28%),radial-gradient(circle_at_82%_16%,rgba(255,212,0,0.08),transparent_20%)]" />
          <div className="absolute inset-0 bg-black/55" />

          <div className="absolute right-8 top-8 w-full max-w-sm rounded-2xl border-2 border-[#C9A84C] bg-[#141414] p-4 shadow-[0_20px_48px_-24px_rgba(201,168,76,0.45)] lg:right-10 lg:top-10">
            <div className="flex items-start gap-3">
              <div className="text-3xl">⚡</div>
              <div className="min-w-0 flex-1">
                <p className="font-monument text-xs uppercase tracking-[0.18em] text-[#C9A84C]">
                  Achievement Unlocked
                </p>
                <p className="mt-1 font-monument text-sm text-chalk">Precision Attack</p>
                <p className="mt-2 font-body text-xs leading-5 text-steel">
                  Three execution gains in a row without a single invalid lap.
                </p>
              </div>
              <div className="text-steel">×</div>
            </div>
          </div>

          <div className="relative z-10 w-full max-w-md rounded-[28px] border-2 border-[#22C55E] bg-[#141414] p-8 text-center shadow-[0_30px_90px_-36px_rgba(34,197,94,0.45)]">
            <p className="font-monument text-3xl tracking-[0.08em] text-[#22C55E]">LEVEL UP!</p>

            <div className="mt-8 flex items-center justify-center gap-4">
              <div className="flex h-16 w-16 items-center justify-center rounded-full border-2 border-steel bg-steel/10 font-monument text-2xl text-steel">
                5
              </div>
              <div className="text-2xl text-steel">→</div>
              <div className="flex h-16 w-16 items-center justify-center rounded-full border-2 border-[#22C55E] bg-[#22C55E]/15 font-monument text-2xl text-[#22C55E] shadow-[0_0_32px_rgba(34,197,94,0.25)]">
                6
              </div>
            </div>

            <p className="mt-6 font-telemetry text-sm text-steel">
              Total XP: <span className="text-chalk">1,640</span>
            </p>

            <button
              type="button"
              className="mt-7 inline-flex min-h-[44px] items-center justify-center rounded-xl bg-[#22C55E] px-7 py-3 font-monument text-sm text-black"
            >
              Continue
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}
