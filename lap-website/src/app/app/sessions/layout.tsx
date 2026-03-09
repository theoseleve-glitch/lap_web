import type { Metadata } from 'next';
import type { ReactNode } from 'react';

export const metadata: Metadata = {
  title: 'Sessions',
};

export default function SessionsLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
