'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import { AchievementsBadges } from '@/components/app/AchievementsBadges';
import { BadgeGrid } from '@/components/app/drivers/BadgeGrid';
import {
  AchievementGrid,
  RacingBadge,
  LicenceCard,
  StreakCounter,
  XPProgressBar,
  type Achievement,
} from '@/components/app/gamification';
import type { DriverBadge } from '@/lib/api-types';

const achievementBadges = [
  {
    id: 'pace-master',
    label: 'Pace Master',
    tier: 'gold' as const,
    category: 'pace',
    criteria: 'Best laps consistently inside the 98th percentile window.',
  },
  {
    id: 'consistency-champion',
    label: 'Consistency',
    tier: 'silver' as const,
    category: 'consistency',
    criteria: 'Hold lap-time spread under 1.8% over a race-distance run.',
  },
  {
    id: 'execution-expert',
    label: 'Execution',
    tier: 'bronze' as const,
    category: 'execution',
    criteria: 'Hit target brake and throttle traces in 12 clean corners.',
  },
  {
    id: 'robust-defender',
    label: 'Robustness',
    tier: 'silver' as const,
    category: 'robustness',
    criteria: 'Protect pace under tire fade and traffic pressure.',
  },
  {
    id: 'adaptive-ace',
    label: 'Adaptation',
    tier: 'gold' as const,
    category: 'adaptation',
    criteria: 'Improve balance and pace after a setup or weather shift.',
  },
  {
    id: 'grand-slam',
    label: 'Grand Slam',
    tier: 'gold' as const,
    category: 'total',
    criteria: 'Break 90 overall while holding all core dimensions above target.',
  },
];

const achievementGridItems: Achievement[] = [
  {
    key: 'session-architect',
    label: 'Session Architect',
    description: 'Complete 20 analyzed sessions with full telemetry coverage.',
    icon: 'calendar',
    unlocked: true,
    unlocked_at: '2025-08-16T08:00:00.000Z',
  },
  {
    key: 'red-mist',
    label: 'Red Mist',
    description: 'Stack three straight A-grade sessions in sprint trim.',
    icon: 'fire',
    unlocked: true,
    unlocked_at: '2025-08-20T08:00:00.000Z',
  },
  {
    key: 'control-room',
    label: 'Control Room',
    description: 'Hold consistency score above 85 for five sessions.',
    icon: 'shield',
    unlocked: true,
    unlocked_at: '2025-08-24T08:00:00.000Z',
  },
  {
    key: 'dyno-mode',
    label: 'Dyno Mode',
    description: 'Unlock after three execution gains in a single week.',
    icon: 'zap',
    unlocked: false,
    unlocked_at: null,
  },
  {
    key: 'trend-breaker',
    label: 'Trend Breaker',
    description: 'Reverse a negative score trend inside two sessions.',
    icon: 'trending-up',
    unlocked: false,
    unlocked_at: null,
  },
];

const legacyDriverBadges: DriverBadge[] = [
  {
    id: 1,
    badge_type: 'pace',
    badge_name: 'Hot Lap Hunter',
    badge_level: 'gold',
    metadata_json: null,
    earned_at: '2025-07-11T08:00:00.000Z',
  },
  {
    id: 2,
    badge_type: 'discipline',
    badge_name: 'Clean Sheet',
    badge_level: 'silver',
    metadata_json: null,
    earned_at: '2025-07-19T08:00:00.000Z',
  },
  {
    id: 3,
    badge_type: 'craft',
    badge_name: 'Rain Whisperer',
    badge_level: 'platinum',
    metadata_json: null,
    earned_at: '2025-07-24T08:00:00.000Z',
  },
  {
    id: 4,
    badge_type: 'consistency',
    badge_name: 'Metronome',
    badge_level: 'bronze',
    metadata_json: null,
    earned_at: '2025-07-29T08:00:00.000Z',
  },
];

const badgeMarks: Array<{
  title: string;
  category: 'progress' | 'technique' | 'consistency' | 'learning' | 'endurance';
  unlocked: boolean;
}> = [
  { title: 'Hotlap Hunter', category: 'technique', unlocked: true },
  { title: 'Metronome', category: 'consistency', unlocked: true },
  { title: 'Apex Hunter', category: 'technique', unlocked: true },
  { title: 'Stint Manager', category: 'endurance', unlocked: true },
  { title: 'Track Scout', category: 'learning', unlocked: true },
  { title: 'First Lap', category: 'progress', unlocked: false },
];

function Surface({
  eyebrow,
  title,
  children,
  className = '',
}: {
  eyebrow: string;
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-[28px] border border-white/10 bg-[linear-gradient(180deg,rgba(20,20,20,0.92),rgba(10,10,10,0.96))] p-6 shadow-[0_24px_80px_-32px_rgba(0,0,0,0.8)] ${className}`}
    >
      <p className="font-telemetry text-[11px] uppercase tracking-[0.24em] text-acid-green/80">
        {eyebrow}
      </p>
      <h2 className="mt-2 font-monument text-xl text-chalk">{title}</h2>
      <div className="mt-5">{children}</div>
    </section>
  );
}

function ShareCardPreview() {
  return (
    <div
      className="overflow-hidden rounded-[28px] border border-white/10 bg-[linear-gradient(135deg,#0d0e12_0%,#171922_46%,#0b0c10_100%)] p-6 shadow-[0_28px_90px_-48px_rgba(182,255,46,0.55)]"
      style={{ aspectRatio: '1200 / 630' }}
    >
      <div className="flex h-full flex-col">
        <div className="flex items-start justify-between gap-6">
          <div>
            <p className="font-telemetry text-[11px] uppercase tracking-[0.24em] text-acid-green">
              LAP COACH
            </p>
            <h3 className="mt-3 font-monument text-[clamp(1.4rem,2.6vw,2.4rem)] text-chalk">
              Theo Eleve
            </h3>
            <p className="mt-3 font-body text-sm text-steel">
              Lonato South • 28 Aug 2025 • Qualifying
            </p>
          </div>

          <div className="flex h-16 w-16 items-center justify-center rounded-2xl border-2 border-acid-green/60 bg-acid-green/12 font-monument text-3xl text-acid-green">
            A+
          </div>
        </div>

        <div className="mt-8 grid grid-cols-4 gap-3">
          {[
            { label: 'Best Lap', value: '46.238', tone: 'text-acid-green' },
            { label: 'Score', value: '91', tone: 'text-chalk' },
            { label: 'Laps', value: '18', tone: 'text-chalk' },
            { label: 'Consistency', value: '92%', tone: 'text-[#00d4ff]' },
          ].map((item) => (
            <div
              key={item.label}
              className="rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-4"
            >
              <p className="font-body text-[11px] uppercase tracking-[0.18em] text-steel/70">
                {item.label}
              </p>
              <p className={`mt-3 font-monument text-2xl ${item.tone}`}>{item.value}</p>
            </div>
          ))}
        </div>

        <div className="mt-8 border-t border-white/8 pt-6">
          <p className="font-body text-[11px] uppercase tracking-[0.18em] text-steel/70">
            Badges Earned
          </p>
          <div className="mt-4 flex gap-5">
            {[
              { title: 'Hotlap Hunter', category: 'technique' as const },
              { title: 'Metronome', category: 'consistency' as const },
              { title: 'Apex Hunter', category: 'technique' as const },
            ].map((badge) => (
              <div key={badge.title} className="flex flex-col items-center gap-2">
                <RacingBadge title={badge.title} description="" unlocked category={badge.category} />
                <p className="font-body text-[11px] text-chalk">{badge.title}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-auto flex items-end justify-between pt-6">
          <p className="font-body text-[11px] uppercase tracking-[0.18em] text-steel/50">
            Motorsport Telemetry Analysis
          </p>
          <p className="font-telemetry text-[11px] uppercase tracking-[0.18em] text-acid-green">
            lap-coach.racing
          </p>
        </div>
      </div>
    </div>
  );
}

export default function GamificationShowcasePage() {
  return (
    <main
      id="main-content"
      className="relative min-h-screen overflow-hidden bg-black text-chalk"
    >
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(182,255,46,0.14),transparent_28%),radial-gradient(circle_at_85%_12%,rgba(0,212,255,0.12),transparent_24%),linear-gradient(180deg,#050505_0%,#090909_42%,#000_100%)]" />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-56 bg-[linear-gradient(180deg,rgba(255,255,255,0.05),transparent)]" />

      <div className="relative mx-auto flex w-full max-w-7xl flex-col gap-8 px-6 py-10 lg:px-10">
        <header className="rounded-[32px] border border-white/10 bg-[linear-gradient(135deg,rgba(182,255,46,0.08),rgba(0,0,0,0.2)_42%,rgba(0,212,255,0.08))] p-7 shadow-[0_32px_90px_-44px_rgba(182,255,46,0.35)]">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl">
              <p className="font-telemetry text-[11px] uppercase tracking-[0.3em] text-acid-green/80">
                LAP UI Export
              </p>
              <h1 className="mt-3 font-monument text-3xl text-chalk sm:text-4xl">
                Gamification Badge And Card Catalogue
              </h1>
              <p className="mt-4 max-w-2xl font-body text-sm leading-6 text-steel">
                Public capture surface for the current gamification system: progression cards,
                licence card, badge families, and the social share card. Additional full-screen
                reward states are split into dedicated routes so they can be imported into Figma
                cleanly.
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              <Link
                href="/gamification-showcase/level-up"
                className="inline-flex min-h-[44px] items-center rounded-full border border-white/15 px-4 py-2 font-body text-sm text-chalk transition-colors hover:border-acid-green/50 hover:text-acid-green"
              >
                Level-Up State
              </Link>
              <Link
                href="/gamification-showcase/unlock"
                className="inline-flex min-h-[44px] items-center rounded-full bg-acid-green px-4 py-2 font-body text-sm font-semibold text-black transition-colors hover:bg-[#a3e629]"
              >
                Achievement Unlock
              </Link>
            </div>
          </div>
        </header>

        <div className="grid gap-8 xl:grid-cols-[1.2fr_0.8fr]">
          <Surface eyebrow="Progression" title="XP, streak, and licence hierarchy">
            <div className="grid gap-6">
              <div className="rounded-[22px] border border-white/8 bg-asphalt/70 p-5">
                <div className="flex flex-col gap-4 md:flex-row md:items-center">
                  <XPProgressBar
                    totalXp={1640}
                    level={6}
                    xpForCurrentLevel={1500}
                    xpForNextLevel={1800}
                    className="flex-1 min-w-0"
                  />
                  <StreakCounter currentStreak={6} longestStreak={11} />
                </div>
              </div>

              <LicenceCard
                tier="club"
                color="#22C55E"
                nextTier="national"
                nextColor="#C9A84C"
                progress={{
                  laps: { current: 182, required: 240 },
                  score: { current: 78, required: 86 },
                }}
              />
            </div>
          </Surface>

          <Surface eyebrow="Badge Marks" title="Core badge icon and tier language">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              {badgeMarks.map((badge) => (
                <div
                  key={badge.title}
                  className="rounded-[22px] border border-white/8 bg-asphalt/70 p-4 flex flex-col items-center text-center"
                >
                  <RacingBadge
                    title={badge.title}
                    description=""
                    unlocked={badge.unlocked}
                    category={badge.category}
                  />
                  <p className="mt-3 font-body text-xs font-medium text-chalk">
                    {badge.title}
                  </p>
                  <p className="mt-1 font-telemetry text-[10px] uppercase tracking-[0.18em] text-steel">
                    {badge.category}
                  </p>
                </div>
              ))}
            </div>
          </Surface>
        </div>

        <div className="grid gap-8 xl:grid-cols-[0.9fr_1.1fr]">
          <Surface eyebrow="Achievement Family" title="Hex badge matrix with tier labels">
            <AchievementsBadges badges={achievementBadges} />
          </Surface>

          <Surface eyebrow="Driver Badges" title="Legacy square badge cards">
            <BadgeGrid badges={legacyDriverBadges} />
          </Surface>
        </div>

        <Surface eyebrow="Achievement Grid" title="Unlocked versus locked progression board">
          <AchievementGrid achievements={achievementGridItems} />
        </Surface>

        <div className="grid gap-8 xl:grid-cols-[0.86fr_1.14fr]">
          <Surface eyebrow="Social Asset" title="Share card preview">
            <ShareCardPreview />
          </Surface>

          <Surface eyebrow="Coverage" title="Included front-end surfaces in this export">
            <div className="grid gap-4 sm:grid-cols-2">
              {[
                'XP progress bar',
                'Streak counter',
                'Licence card',
                'AchievementsBadges card',
                'BadgeGrid legacy cards',
                'AchievementGrid locked/unlocked board',
                'BadgeHex base marks',
                'Share card canvas',
              ].map((item) => (
                <div
                  key={item}
                  className="rounded-[20px] border border-white/8 bg-asphalt/70 px-4 py-4"
                >
                  <p className="font-body text-sm text-chalk">{item}</p>
                </div>
              ))}
            </div>

            <div className="mt-5 rounded-[22px] border border-acid-green/20 bg-acid-green/[0.06] p-5">
              <p className="font-telemetry text-[11px] uppercase tracking-[0.24em] text-acid-green/80">
                Separate capture pages
              </p>
              <p className="mt-2 font-body text-sm leading-6 text-steel">
                Full-screen reward states are isolated on dedicated routes so they import into
                Figma as clean frames instead of covering the entire catalogue capture.
              </p>
              <div className="mt-4 flex flex-wrap gap-3">
                <Link
                  href="/gamification-showcase/level-up"
                  className="inline-flex min-h-[44px] items-center rounded-full border border-white/15 px-4 py-2 font-body text-sm text-chalk transition-colors hover:border-acid-green/50 hover:text-acid-green"
                >
                  /level-up
                </Link>
                <Link
                  href="/gamification-showcase/unlock"
                  className="inline-flex min-h-[44px] items-center rounded-full border border-white/15 px-4 py-2 font-body text-sm text-chalk transition-colors hover:border-acid-green/50 hover:text-acid-green"
                >
                  /unlock
                </Link>
              </div>
            </div>
          </Surface>
        </div>
      </div>
    </main>
  );
}
