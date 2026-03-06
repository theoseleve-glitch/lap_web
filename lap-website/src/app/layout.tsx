import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import Script from 'next/script';
import { ChunkErrorRecovery } from '@/components/providers/ChunkErrorRecovery';
import { SentryInit } from '@/components/providers/SentryInit';
import { WebVitalsInit } from '@/components/providers/WebVitalsInit';
import { TranslationProvider } from '@/i18n/TranslationProvider';
import { getSiteHostname, getSiteUrlAsUrl } from '@/lib/site-url';
import './globals.css';

const siteUrl = getSiteUrlAsUrl();
const siteHostname = getSiteHostname();

export const metadata: Metadata = {
  metadataBase: siteUrl,
  title: { default: 'LAP — Find Time.', template: '%s | LAP' },
  description: 'Motorsport telemetry analysis for kart and car drivers.',
  openGraph: {
    type: 'website',
    siteName: 'LAP',
    title: 'LAP — Find Time.',
    description: 'Motorsport telemetry analysis for kart and car drivers.',
    locale: 'en_US',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'LAP — Find Time.',
    description: 'Motorsport telemetry analysis for kart and car drivers.',
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
      name: 'LAP Racing',
      url: siteUrl.href,
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
        <Script
          defer
          data-domain={siteHostname}
          src="https://plausible.io/js/script.js"
          strategy="afterInteractive"
        />
      </body>
    </html>
  );
}
