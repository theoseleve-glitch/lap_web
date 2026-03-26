import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { ChunkErrorRecovery } from '@/components/providers/ChunkErrorRecovery';
import { ConsentGatedAnalytics } from '@/components/providers/ConsentGatedAnalytics';
import { SentryInit } from '@/components/providers/SentryInit';
import { WebVitalsInit } from '@/components/providers/WebVitalsInit';
import { TranslationProvider } from '@/i18n/TranslationProvider';
import { NavigationProgress } from '@/components/providers/NavigationProgress';
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
  icons: {
    icon: [
      { url: '/favicon.ico', sizes: '32x32' },
      { url: '/icon.svg', type: 'image/svg+xml' },
    ],
    apple: '/icon.svg',
  },
  manifest: '/manifest.json',
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
        {/* Critical CSS — inlined to prevent FOUC before stylesheet loads */}
        <style dangerouslySetInnerHTML={{ __html: [
          'html{background:#000;color:#F0EDE5;font-size:16px}',
          'body{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased;margin:0;overflow-x:hidden}',
          '.font-monument{font-family:"Space Grotesk","Arial Black",sans-serif;font-weight:700;text-transform:uppercase}',
          '.room{position:relative;min-height:100vh;display:flex;flex-direction:column;justify-content:center;overflow:hidden}',
          '.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);border:0}',
        ].join('') }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link rel="preconnect" href="https://api.lap-coach.racing" crossOrigin="anonymous" />
        <link rel="dns-prefetch" href="https://api.lap-coach.racing" />
        <link
          rel="preload"
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=Space+Grotesk:wght@600;700&family=Space+Mono:wght@400&display=swap&subset=latin"
          as="style"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=Space+Grotesk:wght@600;700&family=Space+Mono:wght@400&display=swap&subset=latin"
          rel="stylesheet"
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      </head>
      <body className="relative bg-black text-chalk">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[9999] focus:bg-acid-green focus:text-black focus:px-4 focus:py-2 focus:rounded focus:font-body focus:text-sm"
        >
          Skip to main content
        </a>
        <TranslationProvider>
          <NavigationProgress />
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
