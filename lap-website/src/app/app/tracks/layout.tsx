import type { Metadata } from 'next';
import type { ReactNode } from 'react';

export const metadata: Metadata = {
  title: 'Tracks',
};

export default function TracksLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
