'use client';

/* ── Types ────────────────────────────────────────────────── */

interface StreakTrackerProps {
  currentStreak: number;
  longestStreak: number;
  daysActive: boolean[];
  className?: string;
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/* ── Component ────────────────────────────────────────────── */

export function StreakTracker({
  currentStreak,
  longestStreak,
  daysActive,
  className,
}: StreakTrackerProps) {
  return (
    <div
      className={`p-6 rounded-xl border border-gold/20 bg-gradient-to-br from-gold/10 to-safety-red/10 ${className ?? ''}`}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#C9A84C" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z" />
        </svg>
        <h2 className="text-2xl font-monument font-bold text-chalk">Weekly Streak</h2>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 mb-6">
        <div className="text-center p-4 rounded-lg bg-gold/20">
          <div className="text-4xl font-telemetry font-bold text-gold">{currentStreak}</div>
          <div className="text-sm font-body text-steel mt-1">Current Streak</div>
        </div>
        <div className="text-center p-4 rounded-lg bg-safety-red/20">
          <div className="text-4xl font-telemetry font-bold text-safety-red">{longestStreak}</div>
          <div className="text-sm font-body text-steel mt-1">Best Streak</div>
        </div>
      </div>

      {/* Week grid */}
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sm text-steel font-body">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M8 2v4" /><path d="M16 2v4" />
            <rect width="18" height="18" x="3" y="4" rx="2" />
            <path d="M3 10h18" />
          </svg>
          <span>This Week</span>
        </div>
        <div className="grid grid-cols-7 gap-2">
          {DAYS.map((day, index) => (
            <div key={day} className="text-center">
              <div className="text-xs text-steel mb-1 font-telemetry">{day}</div>
              <div
                className={`h-10 rounded-lg flex items-center justify-center transition-all ${
                  daysActive[index]
                    ? 'bg-gradient-to-br from-gold to-safety-red'
                    : 'bg-steel/10'
                }`}
              >
                {daysActive[index] && (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z" />
                  </svg>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Fire banner */}
      {currentStreak >= 4 && (
        <div className="w-full mt-4 bg-gradient-to-r from-gold to-safety-red text-white text-center py-2 rounded-lg font-telemetry text-sm uppercase tracking-wider">
          You&apos;re on fire! Keep it up!
        </div>
      )}
    </div>
  );
}
