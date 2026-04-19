'use client';

import Link from 'next/link';

const DOWNLOAD_URL = 'https://api.lap-coach.racing/downloads/LapCoachLogger-Setup-1.1.0.exe';
const VERSION = '1.1.0';

const features = [
  {
    icon: '🖥',
    title: 'iRacing & ACC',
    description: 'Native shared-memory adapters for iRacing and Assetto Corsa Competizione. No plugins, no overlays — just start driving.',
  },
  {
    icon: '💾',
    title: 'Local-First',
    description: 'All data stays on your machine. Sessions are saved as CSV + Parquet bundles, ready for analysis even without internet.',
  },
  {
    icon: '📡',
    title: 'Auto-Sync',
    description: 'Link your logger to your Lap Coach account. Sessions upload automatically after each run — no manual file handling.',
  },
  {
    icon: '⚡',
    title: 'Instant Analysis',
    description: 'World-Class plan users get automatic pipeline analysis as soon as a session syncs. Results appear in your dashboard within minutes.',
  },
  {
    icon: '⏱',
    title: 'Live Recording',
    description: 'Real-time session state machine with sub-100ms sampling. Automatic session detection, lap counting, and quality scoring.',
  },
  {
    icon: '🔒',
    title: 'Secure Pairing',
    description: 'Six-character code links your PC to your account. Device tokens are SHA-256 hashed — we never store plaintext credentials.',
  },
];

const tierComparison = [
  { feature: 'Local recording', demo: true, racer: true, worldClass: true },
  { feature: 'CSV + Parquet export', demo: true, racer: true, worldClass: true },
  { feature: 'Session quality scoring', demo: true, racer: true, worldClass: true },
  { feature: 'Account linking', demo: false, racer: true, worldClass: true },
  { feature: 'Auto-sync upload', demo: false, racer: true, worldClass: true },
  { feature: 'Max linked devices', demo: '0', racer: '2', worldClass: '3' },
  { feature: 'Auto-analyze on sync', demo: false, racer: false, worldClass: true },
];

export default function LoggerDownloadPage() {
  return (
    <main className="min-h-screen bg-asphalt">
      {/* Hero */}
      <section className="relative overflow-hidden pt-24 pb-20 sm:pt-32 sm:pb-28">
        <div className="mx-auto max-w-4xl px-6 text-center">
          <p className="font-telemetry text-sm uppercase tracking-widest text-gold mb-4">
            Lap Coach Logger v{VERSION}
          </p>
          <h1 className="font-monument text-4xl sm:text-5xl lg:text-6xl text-chalk leading-tight mb-6">
            Capture Every Lap.<br />Automatically.
          </h1>
          <p className="font-body text-lg text-steel max-w-2xl mx-auto mb-10">
            A lightweight Windows app that records telemetry from iRacing and ACC,
            saves sessions locally, and optionally syncs them to your Lap Coach dashboard
            for instant analysis.
          </p>
          <a
            href={DOWNLOAD_URL}
            className="inline-flex items-center gap-3 bg-gold text-white font-telemetry text-sm uppercase tracking-wider px-8 py-4 rounded hover:bg-gold/80 transition-colors"
          >
            ↓ Download for Windows
          </a>
          <p className="font-telemetry text-xs text-steel mt-4">
            Windows 10 / 11 &middot; 60 MB &middot; No admin required
          </p>
        </div>
      </section>

      {/* Feature Grid */}
      <section className="py-20 border-t border-steel/10">
        <div className="mx-auto max-w-6xl px-6">
          <h2 className="font-monument text-2xl sm:text-3xl text-chalk text-center mb-14">
            Built for Sim Racers
          </h2>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-8">
            {features.map((f) => (
              <div
                key={f.title}
                className="bg-concrete rounded-lg border border-steel/10 p-6"
              >
                <span className="text-2xl mb-4 block">{f.icon}</span>
                <h3 className="font-monument text-lg text-chalk mb-2">{f.title}</h3>
                <p className="font-body text-sm text-steel leading-relaxed">
                  {f.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Tier Comparison */}
      <section className="py-20 border-t border-steel/10">
        <div className="mx-auto max-w-3xl px-6">
          <h2 className="font-monument text-2xl sm:text-3xl text-chalk text-center mb-4">
            What You Get Per Plan
          </h2>
          <p className="font-body text-steel text-center mb-12">
            The logger is free to download. Sync features unlock with a paid plan.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-steel/20">
                  <th className="font-telemetry text-xs uppercase text-steel py-3 pr-4">Feature</th>
                  <th className="font-telemetry text-xs uppercase text-steel py-3 px-4 text-center">Demo</th>
                  <th className="font-telemetry text-xs uppercase text-steel py-3 px-4 text-center">Racer</th>
                  <th className="font-telemetry text-xs uppercase text-steel py-3 pl-4 text-center">World-Class</th>
                </tr>
              </thead>
              <tbody>
                {tierComparison.map((row) => (
                  <tr key={row.feature} className="border-b border-steel/10">
                    <td className="font-body text-sm text-chalk py-3 pr-4">{row.feature}</td>
                    {[row.demo, row.racer, row.worldClass].map((val, i) => (
                      <td key={i} className="font-telemetry text-sm text-center py-3 px-4">
                        {typeof val === 'string' ? (
                          <span className="text-chalk">{val}</span>
                        ) : val ? (
                          <span className="text-acid-green">&#10003;</span>
                        ) : (
                          <span className="text-steel/40">&mdash;</span>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex justify-center gap-4 mt-10">
            <Link
              href="/pricing"
              className="border border-steel/30 text-chalk font-telemetry text-sm uppercase tracking-wider px-6 py-3 rounded hover:bg-concrete transition-colors"
            >
              View Plans
            </Link>
            <a
              href={DOWNLOAD_URL}
              className="bg-gold text-white font-telemetry text-sm uppercase tracking-wider px-6 py-3 rounded hover:bg-gold/80 transition-colors"
            >
              ↓ Download Logger
            </a>
          </div>
        </div>
      </section>

      {/* System Requirements */}
      <section className="py-16 border-t border-steel/10">
        <div className="mx-auto max-w-2xl px-6 text-center">
          <h2 className="font-monument text-xl text-chalk mb-6">System Requirements</h2>
          <div className="grid grid-cols-2 gap-6 text-left">
            <div>
              <p className="font-telemetry text-xs uppercase text-steel mb-1">OS</p>
              <p className="font-body text-sm text-chalk">Windows 10 / 11</p>
            </div>
            <div>
              <p className="font-telemetry text-xs uppercase text-steel mb-1">RAM</p>
              <p className="font-body text-sm text-chalk">4 GB minimum</p>
            </div>
            <div>
              <p className="font-telemetry text-xs uppercase text-steel mb-1">Disk</p>
              <p className="font-body text-sm text-chalk">~100 MB + session data</p>
            </div>
            <div>
              <p className="font-telemetry text-xs uppercase text-steel mb-1">Sims</p>
              <p className="font-body text-sm text-chalk">iRacing, ACC</p>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
