import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { ChunkErrorRecovery } from '@/components/providers/ChunkErrorRecovery';
import { ConsentGatedAnalytics } from '@/components/providers/ConsentGatedAnalytics';
import { SentryInit } from '@/components/providers/SentryInit';
import { WebVitalsInit } from '@/components/providers/WebVitalsInit';
import { TranslationProvider } from '@/i18n/TranslationProvider';
import { getSiteHostname, getSiteUrlAsUrl } from '@/lib/site-url';
import { BRAND, BRAND_USAGE } from '@/data/brand';
import './globals.css';

const siteUrl = getSiteUrlAsUrl();
const siteHostname = getSiteHostname();

const metaTitle = `${BRAND.productName} — ${BRAND.tagline}`;
const metaDescription = `${BRAND_USAGE.metaDescriptionOpening} ${BRAND.positioning.split(',').slice(1).join(',').trim()}`;

export const metadata: Metadata = {
  metadataBase: siteUrl,
  title: { default: metaTitle, template: `%s | ${BRAND.productName}` },
  description: metaDescription,
  openGraph: {
    type: 'website',
    siteName: BRAND.productName,
    title: metaTitle,
    description: BRAND_USAGE.ogCardSubtitle,
    locale: 'en_US',
  },
  twitter: {
    card: 'summary_large_image',
    title: metaTitle,
    description: BRAND_USAGE.ogCardSubtitle,
  },
  robots: {
    index: true,
    follow: true,
  },
};

const jsonLd = {
  '@context': 'https://schema.org',
  '@graph': [
    {
      '@type': 'SoftwareApplication',
      name: 'LAP',
      applicationCategory: 'SportsApplication',
      operatingSystem: 'Web',
      description: 'Motorsport telemetry analysis platform for kart and car drivers',
      offers: [
        { '@type': 'Offer', name: 'Demo', price: '0', priceCurrency: 'EUR' },
        { '@type': 'Offer', name: 'Racer', price: '69', priceCurrency: 'EUR', billingPeriod: 'P1Y' },
        { '@type': 'Offer', name: 'World-Class', price: '109', priceCurrency: 'EUR', billingPeriod: 'P1Y' },
      ],
    },
    {
      '@type': 'Organization',
      name: 'Lap Coach',
      url: siteUrl.href,
      address: {
        '@type': 'PostalAddress',
        streetAddress: '5 rue Paré',
        addressLocality: 'Nantes',
        postalCode: '44000',
        addressCountry: 'FR',
      },
    },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          rel="preload"
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500&family=Space+Grotesk:wght@600;700&family=Space+Mono:wght@400&display=swap&subset=latin"
          as="style"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500&family=Space+Grotesk:wght@600;700&family=Space+Mono:wght@400&display=swap&subset=latin"
          rel="stylesheet"
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      </head>
      <body className="relative bg-asphalt text-chalk texture-grain">
        <TranslationProvider>
          <SentryInit />
          <WebVitalsInit />
          <ChunkErrorRecovery />
          {children}
        </TranslationProvider>
        <ConsentGatedAnalytics dataDomain={siteHostname} />
      </body>
    </html>
  );
}
