'use client';

import { useState } from 'react';
import { RacingBadge } from './RacingBadge';

/* ── Types ────────────────────────────────────────────────── */

interface Badge {
  title: string;
  description: string;
  unlocked: boolean;
  category?: 'progress' | 'technique' | 'consistency' | 'learning' | 'endurance';
}

interface DriverProfileCardProps {
  driverName: string;
  track: string;
  date: string;
  sessionType: string;
  bestLap: string;
  score: number;
  maxScore: number;
  laps: number;
  consistency: number;
  badges: Badge[];
  licenseLevel: 'Rookie' | 'Club' | 'National' | 'Pro' | 'Elite' | 'Legend';
  level: number;
  currentXP: number;
  nextLevelXP: number;
  streak: number;
  lapsToNextLicense?: number;
  lapsRequiredForNext?: number;
  scoreToNextLicense?: number;
  scoreRequiredForNext?: number;
  className?: string;
}

const licenseOrder: DriverProfileCardProps['licenseLevel'][] = [
  'Rookie', 'Club', 'National', 'Pro', 'Elite', 'Legend',
];

const licenseLetters: Record<string, string> = {
  Rookie: 'R', Club: 'C', National: 'N', Pro: 'P', Elite: 'E', Legend: 'L',
};

const licenseColors: Record<string, string> = {
  Rookie: '#949494',
  Club: '#22C55E',
  National: '#C9A84C',
  Pro: '#8B5CF6',
  Elite: '#FACC15',
  Legend: '#FF2A2A',
};

/* ── Component ────────────────────────────────────────────── */

export function DriverProfileCard({
  driverName,
  track,
  date,
  sessionType,
  bestLap,
  score,
  maxScore,
  laps,
  consistency,
  badges,
  licenseLevel,
  level,
  currentXP,
  nextLevelXP,
  streak,
  lapsToNextLicense = 182,
  lapsRequiredForNext = 240,
  scoreToNextLicense = 78,
  scoreRequiredForNext = 86,
  className,
}: DriverProfileCardProps) {
  const [notes, setNotes] = useState('');
  const [editingNotes, setEditingNotes] = useState(false);
  const xpPercent = Math.min(100, (currentXP / Math.max(nextLevelXP, 1)) * 100);
  const currentLicenseIdx = licenseOrder.indexOf(licenseLevel);
  const nextLicense = currentLicenseIdx < licenseOrder.length - 1 ? licenseOrder[currentLicenseIdx + 1] : null;
  const color = licenseColors[licenseLevel];
  const nextColor = nextLicense ? licenseColors[nextLicense] : color;
  const lapsPercent = Math.min(100, (lapsToNextLicense / Math.max(lapsRequiredForNext, 1)) * 100);
  const scorePercent = Math.min(100, (scoreToNextLicense / Math.max(scoreRequiredForNext, 1)) * 100);

  return (
    <div className={`space-y-6 ${className ?? ''}`}>
      {/* === TOP: Name + Notes === */}
      <div>
        <div className="flex items-center gap-3 mb-1">
          <h2 className="text-4xl font-monument font-bold text-chalk uppercase tracking-tight">
            {driverName}
          </h2>
          {/* Pencil icon */}
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-steel cursor-pointer hover:text-chalk transition-colors">
            <path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
            <path d="m15 5 4 4" />
          </svg>
        </div>
        {editingNotes ? (
          <input
            autoFocus
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            onBlur={() => setEditingNotes(false)}
            onKeyDown={(e) => e.key === 'Enter' && setEditingNotes(false)}
            placeholder="Add notes..."
            className="bg-transparent text-sm italic text-steel border-b border-steel/30 outline-none w-64 pb-0.5 font-body"
          />
        ) : (
          <button
            type="button"
            onClick={() => setEditingNotes(true)}
            className="flex items-center gap-2 text-sm italic text-steel hover:text-chalk transition-colors cursor-pointer font-body"
          >
            {notes || 'ADD NOTES...'}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
              <path d="m15 5 4 4" />
            </svg>
          </button>
        )}
      </div>

      {/* === LEVEL + XP BAR + STREAK === */}
      <div className="flex items-center gap-4 px-5 py-3 rounded-[22px] border border-steel/20">
        {/* Level circle */}
        <div className="w-12 h-12 rounded-full flex items-center justify-center border-2 border-acid-green bg-acid-green/10 shrink-0">
          <span className="text-acid-green text-lg font-monument font-bold">{level}</span>
        </div>

        {/* XP bar */}
        <div className="flex-1 min-w-0">
          <div className="font-telemetry text-[11px] text-chalk uppercase tracking-[0.1em] mb-1">
            Level {level} — {currentXP} / {nextLevelXP} XP
          </div>
          <div className="h-3 bg-concrete rounded-full overflow-hidden">
            <div
              className="h-full rounded-full bg-acid-green transition-all duration-700"
              style={{ width: `${xpPercent}%` }}
            />
          </div>
        </div>

        {/* Streak pill */}
        <div className="flex items-center gap-2 px-3 py-2 rounded-full border border-gold/40 bg-gold/15 shrink-0">
          {/* Flame icon */}
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#C9A84C" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z" />
          </svg>
          <span className="font-telemetry text-[11px] text-gold uppercase tracking-[0.1em] font-bold">
            {streak} Day Streak
          </span>
        </div>
      </div>

      {/* === LICENCE CARD === */}
      <div
        className="relative rounded-lg overflow-hidden border-l-4"
        style={{
          borderLeftColor: color,
          background: `linear-gradient(160deg, ${color}14 0%, #141414 60%)`,
        }}
      >
        <div className="pl-5 pr-5 pt-4 pb-4 space-y-4">
          <div className="flex items-start justify-between">
            <div>
              <div
                className="font-telemetry text-[10px] uppercase tracking-[0.1em] mb-1"
                style={{ color }}
              >
                Current Licence
              </div>
              <div className="text-2xl font-monument font-black text-chalk capitalize">
                {licenseLevel.toLowerCase()}
              </div>
            </div>
            <div
              className="w-14 h-14 rounded-lg flex items-center justify-center text-2xl font-black text-chalk"
              style={{ background: `linear-gradient(135deg, ${color}, ${color}cc)` }}
            >
              {licenseLetters[licenseLevel]}
            </div>
          </div>

          {nextLicense && (
            <div className="space-y-2">
              <div className="font-telemetry text-[10px] uppercase tracking-wider text-steel/60">
                Progress to{' '}
                <span className="capitalize" style={{ color: nextColor }}>
                  {nextLicense.toLowerCase()}
                </span>
              </div>

              {/* Laps progress */}
              <div className="space-y-0.5">
                <div className="flex items-center justify-between">
                  <span className="font-telemetry text-[10px] text-steel/50 uppercase">Laps</span>
                  <span className="font-telemetry text-[10px] text-steel/70">
                    {lapsToNextLicense} / {lapsRequiredForNext} laps
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-white/5 overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${lapsPercent}%`,
                      background: `linear-gradient(90deg, ${color}, ${nextColor})`,
                    }}
                  />
                </div>
              </div>

              {/* Score progress */}
              <div className="space-y-0.5">
                <div className="flex items-center justify-between">
                  <span className="font-telemetry text-[10px] text-steel/50 uppercase">Score</span>
                  <span className="font-telemetry text-[10px] text-steel/70">
                    {scoreToNextLicense} / {scoreRequiredForNext} needed
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-white/5 overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${scorePercent}%`,
                      background: `linear-gradient(90deg, ${color}, ${nextColor})`,
                    }}
                  />
                </div>
              </div>
            </div>
          )}

          {/* Tier ladder */}
          <div className="flex gap-1">
            {licenseOrder.map((tier, idx) => {
              const isActive = idx === currentLicenseIdx;
              const isPast = idx < currentLicenseIdx;
              const tColor = licenseColors[tier];
              return (
                <div key={tier} className="flex-1 flex flex-col items-center">
                  <div
                    className="w-full pt-1 pb-0.5 border-b-2 rounded-sm text-center"
                    style={{
                      borderColor: tColor,
                      backgroundColor: isActive ? `${tColor}15` : 'transparent',
                      opacity: isPast || isActive ? 1 : 0.3,
                    }}
                  >
                    <span
                      className="font-telemetry capitalize block"
                      style={{
                        fontSize: '8px',
                        lineHeight: '12px',
                        color: isActive ? tColor : isPast ? '#949494' : 'rgba(160,160,180,0.6)',
                        fontWeight: isActive ? 'bold' : 'normal',
                      }}
                    >
                      {tier.toLowerCase()}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* === SESSION STATS === */}
      <div
        className="rounded-xl p-6 border border-chalk/[0.08]"
        style={{ background: 'linear-gradient(135deg, #0a0a0a 0%, #141414 100%)' }}
      >
        <div className="font-telemetry text-[10px] text-steel uppercase tracking-[0.2em] mb-4">
          Last Session — {track} &bull; {date} &bull; {sessionType}
        </div>
        <div className="grid grid-cols-4 gap-6">
          <div>
            <div className="font-telemetry text-[10px] text-steel uppercase tracking-wider mb-1">Best Lap</div>
            <div className="text-3xl font-telemetry font-bold text-acid-green">{bestLap}</div>
          </div>
          <div>
            <div className="font-telemetry text-[10px] text-steel uppercase tracking-wider mb-1">Score</div>
            <div className="text-3xl font-telemetry font-bold text-chalk">
              {score}<span className="text-lg text-steel">/{maxScore}</span>
            </div>
          </div>
          <div>
            <div className="font-telemetry text-[10px] text-steel uppercase tracking-wider mb-1">Laps</div>
            <div className="text-3xl font-telemetry font-bold text-chalk">{laps}</div>
          </div>
          <div>
            <div className="font-telemetry text-[10px] text-steel uppercase tracking-wider mb-1">Consistency</div>
            <div className="text-3xl font-telemetry font-bold text-acid-green">{consistency}%</div>
          </div>
        </div>
      </div>

      {/* === BADGES EARNED === */}
      <div>
        <div className="font-telemetry text-[10px] text-steel uppercase tracking-[0.2em] mb-4">
          Badges Earned
        </div>
        <div className="flex gap-4 flex-wrap">
          {badges.slice(0, 6).map((badge, index) => (
            <RacingBadge key={index} {...badge} />
          ))}
        </div>
      </div>
    </div>
  );
}
