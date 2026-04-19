import Link from 'next/link';
import type { ReactNode } from 'react';

interface ShowcaseLink {
  href: string;
  label: string;
}

interface ShowcaseShellProps {
  eyebrow: string;
  title: string;
  description: string;
  links: ShowcaseLink[];
  children: ReactNode;
}

interface ShowcaseSurfaceProps {
  eyebrow: string;
  title: string;
  children: ReactNode;
  className?: string;
}

export function ShowcaseShell({
  eyebrow,
  title,
  description,
  links,
  children,
}: ShowcaseShellProps) {
  return (
    <main
      id="main-content"
      className="relative min-h-screen overflow-hidden bg-black text-chalk"
    >
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(182,255,46,0.16),transparent_24%),radial-gradient(circle_at_86%_12%,rgba(0,212,255,0.12),transparent_22%),linear-gradient(180deg,#040404_0%,#090909_44%,#000_100%)]" />
      <div className="relative mx-auto flex w-full max-w-7xl flex-col gap-8 px-6 py-10 lg:px-10">
        <header className="rounded-[32px] border border-white/10 bg-[linear-gradient(135deg,rgba(182,255,46,0.08),rgba(0,0,0,0.24)_42%,rgba(0,212,255,0.08))] p-7 shadow-[0_36px_90px_-46px_rgba(182,255,46,0.35)]">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl">
              <p className="font-telemetry text-[11px] uppercase tracking-[0.3em] text-acid-green/80">
                {eyebrow}
              </p>
              <h1 className="mt-3 font-monument text-3xl text-chalk sm:text-4xl">{title}</h1>
              <p className="mt-4 max-w-2xl font-body text-sm leading-6 text-steel">
                {description}
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              {links.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className="inline-flex min-h-[44px] items-center rounded-full border border-white/15 px-4 py-2 font-body text-sm text-chalk transition-colors hover:border-acid-green/50 hover:text-acid-green"
                >
                  {link.label}
                </Link>
              ))}
            </div>
          </div>
        </header>

        {children}
      </div>
    </main>
  );
}

export function ShowcaseSurface({
  eyebrow,
  title,
  children,
  className = '',
}: ShowcaseSurfaceProps) {
  return (
    <section
      className={`rounded-[28px] border border-white/10 bg-[linear-gradient(180deg,rgba(20,20,20,0.92),rgba(8,8,8,0.96))] p-6 shadow-[0_24px_80px_-32px_rgba(0,0,0,0.8)] ${className}`}
    >
      <p className="font-telemetry text-[11px] uppercase tracking-[0.24em] text-acid-green/80">
        {eyebrow}
      </p>
      <h2 className="mt-2 font-monument text-xl text-chalk">{title}</h2>
      <div className="mt-5">{children}</div>
    </section>
  );
}
