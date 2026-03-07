import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/contact');

export default function ContactLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
