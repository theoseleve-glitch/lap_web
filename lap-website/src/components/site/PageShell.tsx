import type { ReactNode } from 'react';

interface PageShellProps {
  eyebrow?: string;
  title: string;
  description: string;
  children: ReactNode;
  tone?: 'default' | 'document';
}

export function PageShell({
  eyebrow,
  title,
  description,
  children,
  tone = 'default',
}: PageShellProps) {
  const isDocument = tone === 'document';

  return (
    <main className={`mx-auto px-4 py-10 md:py-14 ${isDocument ? 'max-w-4xl' : 'max-w-6xl'}`}>
      <section className={`mb-10 ${isDocument ? 'border border-steel/20 bg-concrete/25 p-5 md:p-7' : ''}`}>
        {eyebrow && (
          <p className="font-telemetry text-steel text-[11px] tracking-[0.12em] uppercase mb-3">
            {eyebrow}
          </p>
        )}
        <h1 className="font-monument text-[clamp(44px,8vw,80px)] leading-[0.9] mb-4">{title}</h1>
        <p className="max-w-3xl text-steel text-lg">{description}</p>
      </section>

      {children}
    </main>
  );
}
