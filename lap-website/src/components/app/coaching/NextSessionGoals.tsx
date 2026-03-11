'use client';

interface NextSessionGoalsProps {
  goals?: string[] | null;
}

export default function NextSessionGoals({ goals }: NextSessionGoalsProps) {
  if (!goals || goals.length === 0) return null;

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-6">
      <h3 className="text-xs text-steel font-body uppercase tracking-wider mb-4">Next Session Goals</h3>
      <ol className="space-y-3">
        {goals.slice(0, 3).map((goal, i) => (
          <li key={i} className="flex items-start gap-3">
            <span className="inline-flex items-center justify-center w-6 h-6 rounded-md border border-steel/20 bg-asphalt text-xs font-telemetry text-chalk/60 shrink-0">
              {i + 1}
            </span>
            <span className="text-sm text-chalk/80 font-body leading-relaxed">{goal}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
