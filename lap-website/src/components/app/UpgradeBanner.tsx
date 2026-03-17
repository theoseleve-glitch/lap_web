import Link from 'next/link';

export function UpgradeBanner() {
  return (
    <div className="bg-pit-orange/10 border border-pit-orange/30 rounded-lg px-6 py-4 flex items-center justify-between mb-6">
      <div>
        <p className="font-monument text-sm text-pit-orange tracking-wider">FREE REPORT</p>
        <p className="text-chalk font-body text-sm mt-0.5">
          You&apos;re viewing a free report. Upgrade to Performance for the full analysis.
        </p>
      </div>
      <Link
        href="/pricing"
        className="shrink-0 px-5 py-2.5 bg-pit-orange text-white font-monument text-sm tracking-wider rounded hover:brightness-110 transition-all"
      >
        Upgrade Now
      </Link>
    </div>
  );
}
