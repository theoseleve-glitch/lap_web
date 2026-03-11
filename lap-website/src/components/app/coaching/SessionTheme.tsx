'use client';

interface SessionThemeProps {
  grade?: string | null;
  session_theme?: string | null;
  narrative?: string | null;
  confidence?: number | null;
}

const GRADE_COLORS: Record<string, string> = {
  S: 'bg-yellow-400 text-black',
  A: 'bg-emerald-500 text-white',
  B: 'bg-blue-500 text-white',
  C: 'bg-yellow-500 text-black',
  D: 'bg-orange-500 text-white',
  F: 'bg-red-600 text-white',
};

export default function SessionTheme({ grade, session_theme, narrative, confidence }: SessionThemeProps) {
  if (!session_theme && !narrative) return null;

  const gradeStyle = grade ? GRADE_COLORS[grade.toUpperCase()] ?? 'bg-steel/30 text-chalk' : null;
  const confPct = confidence != null ? Math.min(100, Math.max(0, Math.round(confidence * 100))) : null;

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-6">
      <div className="flex items-center gap-3 mb-3">
        {grade && gradeStyle && (
          <span className={`inline-flex items-center justify-center w-10 h-10 rounded-lg font-monument text-lg ${gradeStyle}`}>
            {grade.toUpperCase()}
          </span>
        )}
        {session_theme && (
          <h2 className="text-lg font-monument text-chalk">{session_theme}</h2>
        )}
      </div>

      {narrative && (
        <p className="text-sm text-chalk/80 font-body leading-relaxed mb-4">{narrative}</p>
      )}

      {confPct != null && (
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-steel font-telemetry uppercase tracking-wider">Confidence</span>
            <span className="text-xs text-chalk/70 font-telemetry">{confPct}%</span>
          </div>
          <div className="h-1.5 bg-asphalt rounded-full overflow-hidden">
            <div
              className="h-full bg-acid-green rounded-full transition-all"
              style={{ width: `${confPct}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
