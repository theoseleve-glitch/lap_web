import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/pricing');

export default function PricingLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
