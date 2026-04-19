import Link from 'next/link';
import { footerLinks } from '@/data/navigation';
import { BRAND, BRAND_USAGE } from '@/data/brand';

const socialLinks = [
  { label: 'Instagram', href: 'https://instagram.com' },
  { label: 'YouTube', href: 'https://youtube.com' },
  { label: 'LinkedIn', href: 'https://linkedin.com' },
];

const trustBadges = ['GDPR Ready', 'EU Data Residency', 'TLS + AES-256', '99.9% Target Uptime'];

export function SiteFooter() {
  return (
    <footer className="relative mt-16">
      {/* Gradient top border instead of flat line */}
      <div className="section-divider" aria-hidden="true" />

      <div className="mx-auto max-w-6xl px-4 py-16">
        {/* Large ghost wordmark */}
        <div className="relative mb-12">
          <span
            className="font-monument text-gold/[0.04] select-none block"
            style={{ fontSize: 'clamp(80px, 15vw, 180px)', lineHeight: 0.85 }}
            aria-hidden="true"
          >
            LAP
          </span>
          <p className="font-telemetry text-steel/80 text-[10px] tracking-[0.12em] uppercase mt-4">
            {BRAND_USAGE.footerTagline}
          </p>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-10">
          {footerLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="link-reveal font-telemetry text-steel text-[11px] tracking-[0.12em] uppercase hover:text-chalk"
            >
              {link.label}
            </Link>
          ))}
        </div>

        <div className="grid md:grid-cols-3 gap-4 border border-chalk/10 bg-concrete/40 p-5">
          <div>
            <p className="font-telemetry text-[10px] text-steel tracking-[0.12em] uppercase mb-2">Headquarters</p>
            <p className="text-sm text-chalk">{BRAND.companyName}</p>
            <p className="text-sm text-steel">{BRAND.address.full}</p>
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
                  className="link-reveal border border-chalk/15 px-2 py-1 text-xs text-steel hover:text-chalk hover:border-chalk/30 transition-colors duration-300"
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
                <span key={badge} className="border border-chalk/15 px-2 py-1 text-xs text-steel">
                  {badge}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}
