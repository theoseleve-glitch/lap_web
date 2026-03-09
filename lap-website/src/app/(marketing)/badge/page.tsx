'use client';

import { useState } from 'react';
import { PageIntro } from '@/components/ui/PageIntro';

const BADGE_VARIANTS = [
  {
    name: 'Dark',
    bg: '#0d1117',
    text: '#e6edf3',
    accent: '#B6FF2E',
  },
  {
    name: 'Light',
    bg: '#ffffff',
    text: '#1a1f2e',
    accent: '#ff6b35',
  },
];

function getBadgeSvgUrl(v: typeof BADGE_VARIANTS[number]) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="160" height="28" viewBox="0 0 160 28"><rect width="160" height="28" rx="4" fill="${v.bg}" stroke="${v.accent}" stroke-width="1"/><text x="10" y="18" font-family="monospace" font-size="10" fill="${v.accent}" font-weight="bold">POWERED BY</text><text x="102" y="18" font-family="monospace" font-size="11" fill="${v.text}" font-weight="bold">LAP</text></svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function getEmbedCode(v: typeof BADGE_VARIANTS[number]) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="160" height="28" viewBox="0 0 160 28"><rect width="160" height="28" rx="4" fill="${v.bg}" stroke="${v.accent}" stroke-width="1"/><text x="10" y="18" font-family="monospace" font-size="10" fill="${v.accent}" font-weight="bold">POWERED BY</text><text x="102" y="18" font-family="monospace" font-size="11" fill="${v.text}" font-weight="bold">LAP</text></svg>`;
  return `<a href="https://lap-coach.racing" target="_blank" rel="noopener">${svg}</a>`;
}

export default function BadgePage() {
  const [selected, setSelected] = useState(0);
  const [copied, setCopied] = useState(false);

  const variant = BADGE_VARIANTS[selected];
  const embed = getEmbedCode(variant);

  const handleCopy = () => {
    navigator.clipboard.writeText(embed);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <main className="mx-auto max-w-4xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow="Badge"
        title="Powered by LAP Badge"
        subtitle="Add a badge to your team website to show you use LAP for telemetry analysis."
      />

      <section className="mb-8">
        <h2 className="font-monument text-[var(--text-h3)] mb-4">Choose a Style</h2>
        <div className="flex gap-4 mb-6">
          {BADGE_VARIANTS.map((v, i) => (
            <button
              key={v.name}
              type="button"
              onClick={() => setSelected(i)}
              className={`px-4 py-2 border rounded text-sm transition-colors ${
                i === selected
                  ? 'border-acid-green text-acid-green'
                  : 'border-steel/30 text-steel hover:text-chalk'
              }`}
            >
              {v.name}
            </button>
          ))}
        </div>

        {/* Preview — using img tag with data URI to avoid dangerouslySetInnerHTML */}
        <div className="border border-steel/20 p-8 flex items-center justify-center bg-concrete/30 rounded-lg mb-6">
          <img src={getBadgeSvgUrl(variant)} alt={`Powered by LAP badge — ${variant.name} variant`} width={160} height={28} />
        </div>

        {/* Embed code */}
        <div className="relative">
          <pre className="bg-asphalt border border-steel/20 rounded p-4 text-xs text-steel overflow-x-auto">
            {embed}
          </pre>
          <button
            type="button"
            onClick={handleCopy}
            className="absolute top-2 right-2 px-3 py-1 bg-steel/10 border border-steel/20 rounded text-[10px] font-telemetry uppercase text-steel hover:text-chalk transition-colors"
          >
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
      </section>

      <section className="border border-steel/20 p-5">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">Usage Guidelines</h2>
        <ul className="text-sm text-steel space-y-1 list-disc list-inside">
          <li>Place the badge in your website footer or sidebar</li>
          <li>Do not modify the badge colors or proportions</li>
          <li>Keep the link pointing to lap-coach.racing</li>
          <li>The badge is free to use for all LAP customers</li>
        </ul>
      </section>
    </main>
  );
}
