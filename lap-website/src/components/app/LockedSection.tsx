import Link from 'next/link';

interface LockedSectionProps {
  title: string;
  description: string;
  children: React.ReactNode;
}

export function LockedSection({ title, description, children }: LockedSectionProps) {
  return (
    <div className="relative rounded-lg overflow-hidden">
      {/* Blurred content */}
      <div className="blur-sm opacity-30 pointer-events-none select-none" aria-hidden="true">
        {children}
      </div>

      {/* Overlay */}
      <div className="absolute inset-0 flex flex-col items-center justify-center bg-asphalt/60 backdrop-blur-[1px]">
        <div className="w-12 h-12 rounded-full bg-steel/20 flex items-center justify-center mb-3">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="text-steel">
            <rect x="3" y="9" width="14" height="9" rx="2" stroke="currentColor" strokeWidth="1.5" />
            <path d="M6 9V6a4 4 0 1 1 8 0v3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </div>
        <p className="font-monument text-lg text-chalk mb-1">{title}</p>
        <p className="text-steel font-body text-sm mb-4 text-center max-w-xs">{description}</p>
        <Link
          href="/pricing"
          className="px-5 py-2 bg-pit-orange text-asphalt font-monument text-sm tracking-wider rounded hover:brightness-110 transition-all"
        >
          Unlock with Performance
        </Link>
      </div>
    </div>
  );
}
