import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/book');

export default function BookLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
