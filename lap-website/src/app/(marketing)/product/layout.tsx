import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/product');

export default function ProductLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
