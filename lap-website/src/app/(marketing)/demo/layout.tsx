import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/demo');

export default function DemoLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
