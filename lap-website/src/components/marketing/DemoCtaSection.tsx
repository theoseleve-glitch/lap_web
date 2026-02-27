'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { PitButton } from '@/components/ui/PitButton';
import { silentRefresh } from '@/lib/auth';

export function DemoCtaSection() {
  const [authChecked, setAuthChecked] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  useEffect(() => {
    silentRefresh().then((user) => {
      setIsAuthenticated(user !== null);
      setAuthChecked(true);
    });
  }, []);

  if (!authChecked) {
    return <div className="h-12" />;
  }

  if (isAuthenticated) {
    return (
      <div className="flex flex-wrap gap-3">
        <PitButton href="/app/analyze">Go to Analysis Page</PitButton>
        <Link
          href="/app/dashboard"
          className="border border-steel/30 px-4 py-3 text-sm text-steel hover:text-chalk transition-colors"
        >
          Dashboard
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-3">
      <PitButton href="/register?redirect=/app/analyze&source=demo">
        Create Free Account
      </PitButton>
    </div>
  );
}
