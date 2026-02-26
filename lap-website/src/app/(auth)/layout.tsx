import type { ReactNode } from 'react';
import Link from 'next/link';

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-asphalt">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <Link href="/" className="font-monument text-4xl text-chalk tracking-tight">
            LAP
          </Link>
        </div>
        <div className="bg-concrete rounded-lg border border-steel/20 p-8">
          {children}
        </div>
      </div>
    </div>
  );
}
