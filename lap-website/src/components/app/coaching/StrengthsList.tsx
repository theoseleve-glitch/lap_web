'use client';

interface StrengthsListProps {
  strengths?: string[] | null;
}

export default function StrengthsList({ strengths }: StrengthsListProps) {
  if (!strengths || strengths.length === 0) return null;

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-6">
      <h3 className="text-xs text-steel font-body uppercase tracking-wider mb-3">Strengths</h3>
      <div className="flex flex-wrap gap-2">
        {strengths.map((s, i) => (
          <span
            key={i}
            className="text-xs font-body text-acid-green bg-acid-green/10 border border-acid-green/20 px-3 py-1.5 rounded-lg"
          >
            {s}
          </span>
        ))}
      </div>
    </div>
  );
}
