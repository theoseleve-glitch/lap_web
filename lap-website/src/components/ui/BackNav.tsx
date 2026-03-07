import Link from 'next/link';

interface BackNavProps { href: string; label?: string; }

export function BackNav({ href, label = 'Back' }: BackNavProps) {
  return (
    <Link href={href} className="inline-flex items-center gap-1 font-telemetry text-[var(--text-caption)] text-steel hover:text-chalk transition-colors mb-[var(--space-1)]">
      <span aria-hidden="true">&larr;</span>
      {label}
    </Link>
  );
}
