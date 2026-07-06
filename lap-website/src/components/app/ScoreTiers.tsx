'use client';

interface Provenance { code: string; label: string; dimension: string | null }
interface Adjustment { code: string; label: string; dimension: string; delta: number }

export interface ScoreTiersData {
  absolute: { total_score: number | null; grade: string | null };
  contextualized: {
    total_score: number | null;
    grade: string | null;
    adjustments: Adjustment[];
    provenance: Provenance[];
  };
  competition: {
    score: number; grade: string; position: number | null;
    total_competitors: number | null; percentile: number | null;
    is_dnf: boolean; basis: string; provenance: Provenance[];
  } | null;
  reflection_present: boolean;
}

function TierCard({
  title, sub, score, grade, accent,
}: {
  title: string; sub: string; score: number | null; grade: string | null; accent: string;
}) {
  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-4 flex-1 min-w-[140px]">
      <div className="text-[10px] font-telemetry text-steel uppercase tracking-wider">{title}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className={`text-3xl font-monument ${accent}`}>
          {score != null ? Math.round(score) : '--'}
        </span>
        <span className="text-xs font-telemetry text-steel">/100</span>
        {grade && <span className="text-sm font-telemetry text-chalk">{grade}</span>}
      </div>
      <div className="mt-1 text-[10px] font-body text-steel">{sub}</div>
    </div>
  );
}

export function ScoreTiers({ tiers }: { tiers: ScoreTiersData }) {
  if (!tiers) return null;
  const ctx = tiers.contextualized;
  const comp = tiers.competition;

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-6">
      <h2 className="text-lg font-monument text-chalk mb-1">Performance Tiers</h2>
      <p className="text-xs font-body text-steel mb-4">
        Every number is labeled with how it was derived — nothing is silently adjusted.
      </p>

      <div className="flex flex-wrap gap-3">
        <TierCard title="Absolute" sub="vs your theoretical lap"
          score={tiers.absolute.total_score} grade={tiers.absolute.grade} accent="text-chalk" />
        <TierCard title="In Context" sub="adjusted for how it went"
          score={ctx.total_score} grade={ctx.grade} accent="text-gold" />
        {comp && (
          <TierCard title="vs Competition" sub="self-reported result"
            score={comp.score} grade={comp.grade} accent="text-acid-green" />
        )}
      </div>

      {ctx.adjustments.length > 0 && (
        <div className="mt-4">
          <h3 className="text-xs text-steel font-body uppercase tracking-wider mb-2">
            Context adjustments
          </h3>
          <ul className="space-y-1">
            {ctx.adjustments.map((a) => (
              <li key={a.code} className="text-sm text-chalk/80 font-body flex gap-2">
                <span className="text-gold shrink-0 font-telemetry">
                  {a.delta > 0 ? `+${a.delta}` : a.delta}
                </span>
                {a.label}
              </li>
            ))}
          </ul>
        </div>
      )}

      {(ctx.provenance.length > 0 || comp) && (
        <div className="mt-4 pt-3 border-t border-steel/10">
          <h3 className="text-xs text-steel font-body uppercase tracking-wider mb-2">Provenance</h3>
          <ul className="space-y-1">
            {ctx.provenance.map((p) => (
              <li key={p.code} className="text-[11px] text-steel font-body">{p.label}</li>
            ))}
            {comp?.provenance.map((p) => (
              <li key={`c-${p.code}`} className="text-[11px] text-steel font-body">{p.label}</li>
            ))}
            {comp && (
              <li className="text-[11px] text-steel font-body">
                Finished P{comp.position ?? '?'}
                {comp.total_competitors ? ` of ${comp.total_competitors}` : ''}
                {comp.percentile != null ? ` — ${comp.percentile}th percentile of the field.` : '.'}
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
