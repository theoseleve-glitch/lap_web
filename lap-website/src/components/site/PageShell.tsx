import type { ReactNode } from 'react';

interface PageShellProps {
  eyebrow?: string;
  title: string;
  description: string;
  children: ReactNode;
}

export function PageShell({ eyebrow, title, description, children }: PageShellProps) {
  return (
    <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
      <section className="mb-10">
        {eyebrow && (
          <p className="font-telemetry text-steel text-[11px] tracking-[0.12em] uppercase mb-3">
            {eyebrow}
          </p>
        )}
        <h1 className="font-monument text-[clamp(44px,8vw,80px)] leading-[0.9] mb-4">{title}</h1>
        <p className="max-w-3xl text-steel">{description}</p>
      </section>

      {children}
    </main>
  );
}
