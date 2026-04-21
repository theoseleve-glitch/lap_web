import type { SourceLiteral } from '@/types/contracts';

const LABELS: Record<SourceLiteral, string> = {
  real_life: 'GPS',
  iracing: 'iRacing',
  ac: 'AC',
};

export function SourceBadge({ source }: { source: SourceLiteral | null | undefined }) {
  if (!source) return null;
  return (
    <span
      className="inline-flex items-center px-1.5 py-0.5 rounded
        text-[9px] font-telemetry uppercase tracking-wider
        text-steel border border-steel/30 bg-steel/5"
      title={`Data source: ${LABELS[source]}`}
    >
      {LABELS[source]}
    </span>
  );
}
