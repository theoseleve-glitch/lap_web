import Link from 'next/link';
import { footerLinks } from '@/data/navigation';

const socialLinks = [
  { label: 'Instagram', href: 'https://instagram.com' },
  { label: 'YouTube', href: 'https://youtube.com' },
  { label: 'LinkedIn', href: 'https://linkedin.com' },
];

const trustBadges = ['GDPR Ready', 'EU Data Residency', 'TLS + AES-256', '99.9% Target Uptime'];

export function SiteFooter() {
  return (
    <footer className="border-t border-steel/20 mt-16">
      <div className="mx-auto max-w-6xl px-4 py-10">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
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

        <div className="grid md:grid-cols-3 gap-4 border border-steel/20 bg-concrete/20 p-4">
          <div>
            <p className="font-telemetry text-[10px] text-steel tracking-[0.12em] uppercase mb-2">Headquarters</p>
            <p className="text-sm text-chalk">LAP Racing</p>
            <p className="text-sm text-steel">2 Avenue des Virages, 75008 Paris, France</p>
          </div>
          <div>
            <p className="font-telemetry text-[10px] text-steel tracking-[0.12em] uppercase mb-2">Social</p>
            <div className="flex flex-wrap gap-2">
              {socialLinks.map((social) => (
                <a
                  key={social.label}
                  href={social.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="border border-steel/30 px-2 py-1 text-xs text-steel hover:text-chalk hover:border-chalk"
                >
                  {social.label}
                </a>
              ))}
            </div>
          </div>
          <div>
            <p className="font-telemetry text-[10px] text-steel tracking-[0.12em] uppercase mb-2">Trust</p>
            <div className="flex flex-wrap gap-2">
              {trustBadges.map((badge) => (
                <span key={badge} className="border border-steel/30 px-2 py-1 text-xs text-steel">
                  {badge}
                </span>
              ))}
            </div>
          </div>
        </div>

        <p className="font-telemetry text-steel/80 text-[10px] tracking-[0.12em] uppercase mt-6">
          LAP // Find time faster with outcome-first telemetry workflows.
        </p>
      </div>
    </footer>
  );
}
