'use client';

/* ── Types ────────────────────────────────────────────────── */

interface ChallengeCardProps {
  title: string;
  description: string;
  /** SVG icon as JSX, or omit for default target icon */
  icon?: React.ReactNode;
  progress: number;
  maxProgress: number;
  reward: number;
  timeLeft?: string;
  difficulty: 'easy' | 'medium' | 'hard';
  onAction: () => void;
  completed?: boolean;
  className?: string;
}

const difficultyStyles: Record<string, { bg: string; text: string; label: string }> = {
  easy: { bg: 'bg-acid-green/20', text: 'text-acid-green', label: 'Easy' },
  medium: { bg: 'bg-marshal-yellow/20', text: 'text-marshal-yellow', label: 'Medium' },
  hard: { bg: 'bg-safety-red/20', text: 'text-safety-red', label: 'Hard' },
};

/* ── Default Icon ─────────────────────────────────────────── */

function DefaultChallengeIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  );
}

/* ── Component ────────────────────────────────────────────── */

export function ChallengeCard({
  title,
  description,
  icon,
  progress,
  maxProgress,
  reward,
  timeLeft,
  difficulty,
  onAction,
  completed = false,
  className,
}: ChallengeCardProps) {
  const pct = Math.min(100, (progress / Math.max(maxProgress, 1)) * 100);
  const diff = difficultyStyles[difficulty];

  return (
    <div
      className={`p-5 rounded-xl border border-steel/20 bg-gradient-to-br from-white/5 to-white/10 hover:border-racing-purple/30 transition-all ${className ?? ''}`}
    >
      <div className="flex gap-4">
        {/* Icon */}
        <div className="p-3 rounded-lg bg-gradient-to-br from-racing-purple to-acid-green/60 h-fit shrink-0">
          {icon ?? <DefaultChallengeIcon />}
        </div>

        <div className="flex-1 space-y-3 min-w-0">
          {/* Title + difficulty */}
          <div>
            <div className="flex items-start justify-between gap-2 mb-1">
              <h3 className="font-monument font-semibold text-chalk">{title}</h3>
              <span
                className={`${diff.bg} ${diff.text} font-telemetry text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full border border-current/20 shrink-0`}
              >
                {diff.label}
              </span>
            </div>
            <p className="text-sm font-body text-steel">{description}</p>
          </div>

          {/* Progress bar */}
          <div className="space-y-1">
            <div className="flex justify-between text-sm font-telemetry">
              <span className="text-steel">
                Progress: {progress} / {maxProgress}
              </span>
              <span className="font-semibold text-chalk">{Math.round(pct)}%</span>
            </div>
            <div className="w-full h-2 rounded-full bg-steel/10 overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-racing-purple to-acid-green transition-all duration-300"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>

          {/* Footer: reward + time + action */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4 text-sm">
              <div className="flex items-center gap-1">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="#FACC15" stroke="#FACC15" strokeWidth="1">
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                </svg>
                <span className="font-telemetry font-semibold text-marshal-yellow">+{reward} pts</span>
              </div>
              {timeLeft && (
                <div className="flex items-center gap-1 text-steel font-body">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10" />
                    <polyline points="12 6 12 12 16 14" />
                  </svg>
                  <span>{timeLeft}</span>
                </div>
              )}
            </div>

            <button
              type="button"
              onClick={onAction}
              disabled={completed}
              className={`px-4 py-1.5 rounded-lg font-telemetry text-xs uppercase tracking-wider transition-all ${
                completed
                  ? 'bg-steel/20 text-steel cursor-not-allowed'
                  : 'bg-gradient-to-r from-racing-purple to-acid-green/80 text-white hover:brightness-110'
              }`}
            >
              {completed ? 'Completed' : 'Complete'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
