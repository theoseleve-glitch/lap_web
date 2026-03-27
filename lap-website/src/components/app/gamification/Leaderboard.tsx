'use client';

/* ── Types ────────────────────────────────────────────────── */

interface LeaderboardEntry {
  rank: number;
  username: string;
  points: number;
  level: number;
  isCurrentUser?: boolean;
}

interface LeaderboardProps {
  entries: LeaderboardEntry[];
  className?: string;
}

/* ── Rank Icons ───────────────────────────────────────────── */

function TrophyIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#FACC15" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6" /><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18" />
      <path d="M4 22h16" /><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22" />
      <path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22" />
      <path d="M18 2H6v7a6 6 0 0 0 12 0V2Z" />
    </svg>
  );
}

function MedalIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#949494" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M7.21 15 2.66 7.14a2 2 0 0 1 .13-2.2L4.4 2.8A2 2 0 0 1 6 2h12a2 2 0 0 1 1.6.8l1.6 2.14a2 2 0 0 1 .14 2.2L16.79 15" />
      <path d="M11 12 5.12 2.2" /><path d="m13 12 5.88-9.8" />
      <path d="M8 7h8" /><circle cx="12" cy="17" r="5" />
      <path d="M12 18v-2h-.5" />
    </svg>
  );
}

function AwardIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#C9A84C" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8" r="6" />
      <path d="M15.477 12.89 17 22l-5-3-5 3 1.523-9.11" />
    </svg>
  );
}

function getRankIcon(rank: number) {
  if (rank === 1) return <TrophyIcon />;
  if (rank === 2) return <MedalIcon />;
  if (rank === 3) return <AwardIcon />;
  return null;
}

function getRankColor(rank: number): string {
  if (rank === 1) return 'text-marshal-yellow';
  if (rank === 2) return 'text-steel';
  if (rank === 3) return 'text-gold';
  return 'text-steel/60';
}

/* ── Component ────────────────────────────────────────────── */

export function Leaderboard({ entries, className }: LeaderboardProps) {
  return (
    <div className={`p-6 rounded-xl border border-steel/20 bg-concrete ${className ?? ''}`}>
      <div className="flex items-center gap-2 mb-6">
        <TrophyIcon />
        <h2 className="text-2xl font-monument font-bold text-chalk">Leaderboard</h2>
      </div>

      <div className="space-y-3">
        {entries.map((entry) => (
          <div
            key={entry.rank}
            className={`flex items-center gap-4 p-3 rounded-lg transition-all ${
              entry.isCurrentUser
                ? 'bg-gradient-to-r from-racing-purple/20 to-acid-green/10 border border-racing-purple/30'
                : 'bg-steel/5 hover:bg-steel/10'
            }`}
          >
            {/* Rank */}
            <div className={`w-8 font-telemetry font-bold text-center ${getRankColor(entry.rank)}`}>
              {entry.rank <= 3 ? getRankIcon(entry.rank) : `#${entry.rank}`}
            </div>

            {/* Avatar */}
            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-racing-purple to-acid-green flex items-center justify-center shrink-0">
              <span className="text-white font-monument font-bold text-sm">
                {entry.username.charAt(0).toUpperCase()}
              </span>
            </div>

            {/* Name + level */}
            <div className="flex-1 min-w-0">
              <div className="font-body font-semibold text-chalk flex items-center gap-2">
                <span className="truncate">{entry.username}</span>
                {entry.isCurrentUser && (
                  <span className="font-telemetry text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded border border-steel/30 text-steel shrink-0">
                    You
                  </span>
                )}
              </div>
              <div className="text-sm font-body text-steel">Level {entry.level}</div>
            </div>

            {/* Points */}
            <div className="text-right shrink-0">
              <div className="font-telemetry font-bold text-lg text-chalk">{entry.points.toLocaleString()}</div>
              <div className="text-xs font-body text-steel">points</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
