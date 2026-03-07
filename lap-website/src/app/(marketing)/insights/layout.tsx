import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/insights');

export default function InsightsLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
