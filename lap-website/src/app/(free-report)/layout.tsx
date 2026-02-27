'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { QueryProvider } from '@/providers/query-provider';

const steps = [
  { label: 'Upload', path: '/free-report/analyze' },
  { label: 'Results', path: '/free-report/report' },
] as const;

export default function FreeReportLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const currentStepIndex = steps.findIndex((s) => pathname.startsWith(s.path));

  return (
    <div className="min-h-screen bg-asphalt flex flex-col">
      {/* Minimal header */}
      <header className="border-b border-steel/20 bg-concrete">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link href="/" className="font-monument text-2xl text-chalk tracking-tight">
            LAP
          </Link>

          {/* Step indicator */}
          <div className="flex items-center gap-3">
            {steps.map((step, i) => {
              const isActive = i === currentStepIndex;
              const isComplete = i < currentStepIndex;
              return (
                <div key={step.label} className="flex items-center gap-3">
                  {i > 0 && (
                    <div className={`w-8 h-0.5 ${isComplete ? 'bg-acid-green' : 'bg-steel/30'}`} />
                  )}
                  <div className="flex items-center gap-2">
                    <div
                      className={`w-6 h-6 rounded-full flex items-center justify-center font-telemetry text-xs ${
                        isActive
                          ? 'bg-acid-green text-asphalt'
                          : isComplete
                            ? 'bg-acid-green/20 text-acid-green'
                            : 'bg-concrete text-steel border border-steel/30'
                      }`}
                    >
                      {isComplete ? '✓' : i + 1}
                    </div>
                    <span className={`font-body text-sm ${isActive ? 'text-chalk' : 'text-steel'}`}>
                      {step.label}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="w-12" />
        </div>
      </header>

      <QueryProvider>
        <main className="flex-1">
          <div className="max-w-5xl mx-auto px-6 py-8">
            {children}
          </div>
        </main>
      </QueryProvider>
    </div>
  );
}
