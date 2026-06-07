'use client';

export interface Quest {
  id: number;
  metric: string;
  human_text: string;
  xp: number;
  status: string;
  focused?: boolean;
  baseline?: number | null;
  target?: number | null;
}

/** One quest row — text, XP pill, status, optional focus star toggle. */
export function QuestCard({
  quest,
  onFocus,
}: {
  quest: Quest;
  onFocus?: (id: number, focused: boolean) => void;
}) {
  const done = quest.status === 'completed';
  const expired = quest.status === 'expired';

  const containerClass = done
    ? 'border-acid-green/30 bg-acid-green/5'
    : expired
      ? 'border-steel/10 bg-asphalt opacity-50'
      : 'border-steel/15 bg-asphalt';

  const textClass = done
    ? 'text-acid-green line-through'
    : expired
      ? 'text-steel line-through'
      : 'text-chalk';

  return (
    <div
      className={`flex items-center justify-between gap-3 rounded-lg border px-3 py-2 ${containerClass}`}
    >
      <div className="min-w-0 flex-1">
        <p className={`font-telemetry text-xs truncate ${textClass}`}>
          {quest.human_text}
        </p>
        <p className="font-telemetry text-[10px] text-steel">
          +{quest.xp} XP{done ? ' · done' : expired ? ' · expired' : ''}
          {!done && quest.baseline != null && quest.target != null && (
            <span className="ml-2 text-steel/70">
              {Math.round(quest.baseline * 10) / 10}
              <span className="mx-0.5">→</span>
              <span className="text-chalk/80">{Math.round(quest.target * 10) / 10}</span>
            </span>
          )}
        </p>
      </div>

      {!done && !expired && onFocus && (
        <button
          type="button"
          aria-label={quest.focused ? 'Unfocus quest' : 'Focus quest'}
          onClick={() => onFocus(quest.id, !quest.focused)}
          className="shrink-0 text-sm leading-none transition-colors"
          style={{ color: quest.focused ? '#FACC15' : '#94949466' }}
        >
          {quest.focused ? '★' : '☆'}
        </button>
      )}
    </div>
  );
}
