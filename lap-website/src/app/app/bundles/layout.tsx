import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Session Analysis | Lap',
  description: 'Upload and analyze telemetry session bundles.',
};

export default function BundlesLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
