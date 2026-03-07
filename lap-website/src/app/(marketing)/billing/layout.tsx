import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/billing');

export default function BillingLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
