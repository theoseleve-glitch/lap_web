import Link from 'next/link';
import { footerLinks } from '@/data/navigation';

export function SiteFooter() {
  return (
    <footer className="border-t border-steel/20 mt-16">
      <div className="mx-auto max-w-6xl px-4 py-10">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {footerLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="font-telemetry text-steel text-[11px] tracking-[0.12em] uppercase hover:text-chalk"
            >
              {link.label}
            </Link>
          ))}
        </div>

        <p className="font-telemetry text-steel/80 text-[10px] tracking-[0.12em] uppercase mt-8">
          LAP // Conversion infrastructure with route-first CTAs and tracked lead flows.
        </p>
      </div>
    </footer>
  );
}
