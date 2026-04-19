import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { AppShell } from './AppShell';
import { AppEventTracker } from '@/components/app/AppEventTracker';

export const metadata: Metadata = {
  title: { default: 'Dashboard', template: '%s | LAP Coach Dashboard' },
  robots: { index: false, follow: false },
};

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <AppShell>
      <AppEventTracker />
      {children}
    </AppShell>
  );
}
