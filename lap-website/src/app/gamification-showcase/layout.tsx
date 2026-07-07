import type { Metadata } from 'next';
import type { ReactNode } from 'react';

// Internal dev/concept showcase -- keep reachable but out of the index.
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function GamificationShowcaseLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
