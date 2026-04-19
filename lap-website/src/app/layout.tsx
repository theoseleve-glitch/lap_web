import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';
import { Inter, Space_Grotesk, Space_Mono } from 'next/font/google';
import { ChunkErrorRecovery } from '@/components/providers/ChunkErrorRecovery';
import { ConsentGatedAnalytics } from '@/components/providers/ConsentGatedAnalytics';
import { SentryInit } from '@/components/providers/SentryInit';
import { WebVitalsInit } from '@/components/providers/WebVitalsInit';
import { TranslationProvider } from '@/i18n/TranslationProvider';
import { NavigationProgress } from '@/components/providers/NavigationProgress';
import { getSiteHostname, getSiteUrlAsUrl } from '@/lib/site-url';
import { BRAND, BRAND_USAGE } from '@/data/brand';
import './globals.css';

// next/font: self-hosted, zero-CLS, automatic subsetting.
// CSS variables match what tailwind.config.ts already expects
// (--font-body, --font-display, --font-mono).
const inter = Inter({
  subsets: ['latin'],
  weight: ['300', '400', '500', '600'],
  variable: '--font-body',
  display: 'swap',
  preload: true,
});

const spaceGrotesk = Space_Grotesk({
  subsets: ['latin'],
  weight: ['600', '700'],
  variable: '--font-display',
  display: 'swap',
  preload: true,
});

const spaceMono = Space_Mono({
  subsets: ['latin'],
  weight: ['400'],
  variable: '--font-mono',
  display: 'swap',
  preload: false,
});

const siteUrl = getSiteUrlAsUrl();
const siteHostname = getSiteHostname();

const metaTitle = `${BRAND.productName} — ${BRAND.tagline}`;
const metaDescription = `${BRAND_USAGE.metaDescriptionOpening} ${BRAND.positioning.split(',').slice(1).join(',').trim()}`;

// Static OG image fallback — protects share previews when the OG-image
// Cloudflare Worker is slow or unreachable.
const OG_FALLBACK = {
  url: '/og-image.jpg',
  width: 1200,
  height: 630,
  alt: `${BRAND.productName} — ${BRAND.tagline}`,
} as const;

export const metadata: Metadata = {
  metadataBase: siteUrl,
  title: { default: metaTitle, template: `%s | ${BRAND.productName}` },
  description: metaDescription,
  applicationName: BRAND.productName,
  authors: [{ name: 'Lap Coach', url: siteUrl.href }],
  creator: 'Lap Coach',
  publisher: 'Lap Coach',
  category: 'sports',
  keywords: [
    'motorsport telemetry',
    'kart telemetry analysis',
    'race car data analysis',
    'GPS lap analysis',
    'RaceChrono analysis',
    'RaceBox telemetry',
    'AiM MoTeC analysis',
    'driver coaching',
    'lap-time improvement',
    'racing line analysis',
  ],
  alternates: {
    canonical: '/',
  },
  openGraph: {
    type: 'website',
    siteName: BRAND.productName,
    title: metaTitle,
    description: BRAND_USAGE.ogCardSubtitle,
    locale: 'en_US',
    url: siteUrl.href,
    images: [OG_FALLBACK],
  },
  twitter: {
    card: 'summary_large_image',
    title: metaTitle,
    description: BRAND_USAGE.ogCardSubtitle,
    images: [OG_FALLBACK.url],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      'max-snippet': -1,
      'max-image-preview': 'large',
      'max-video-preview': -1,
    },
  },
  icons: {
    icon: [
      { url: '/favicon.ico', sizes: '32x32' },
      { url: '/icon.svg', type: 'image/svg+xml' },
    ],
    apple: '/icon.svg',
  },
  manifest: '/manifest.json',
  formatDetection: {
    email: false,
    address: false,
    telephone: false,
  },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 5,
  themeColor: [
    { media: '(prefers-color-scheme: dark)', color: '#000000' },
    { media: '(prefers-color-scheme: light)', color: '#000000' },
  ],
  colorScheme: 'dark',
};

// One year from build time for priceValidUntil — Google requires this
// for Offer rich results. Recomputed on every build, so never stale.
const _priceValidUntil = (() => {
  const d = new Date();
  d.setFullYear(d.getFullYear() + 1);
  return d.toISOString().slice(0, 10);
})();

const jsonLd = {
  '@context': 'https://schema.org',
  '@graph': [
    {
      '@type': 'SoftwareApplication',
      '@id': `${siteUrl.href}#software`,
      name: 'LAP',
      alternateName: BRAND.productName,
      applicationCategory: 'SportsApplication',
      applicationSubCategory: 'Motorsport telemetry analysis',
      operatingSystem: 'Web, Windows, macOS, Linux',
      inLanguage: 'en',
      url: siteUrl.href,
      image: `${siteUrl.href}/og-image.jpg`,
      description:
        'Motorsport telemetry analysis for kart and car drivers. Ingest GPS, ' +
        'detect corners automatically, score pace / consistency / execution / ' +
        'robustness, and compare laps across sessions.',
      featureList: [
        'GPS telemetry ingestion from RaceChrono, RaceBox, AiM, MoTeC',
        'Automatic corner detection from GPS trajectory',
        'Four-pillar scoring: Pace, Consistency, Execution, Robustness',
        'Per-corner coaching insights',
        'Session-vs-session comparison with distance synchronization',
        'Track auto-detection from GPS coordinates',
        'PDF coaching reports',
        'Cross-session reference lap overlay',
        'Theoretical perfect-lap solver',
      ],
      offers: [
        {
          '@type': 'Offer',
          name: 'Demo',
          price: '0',
          priceCurrency: 'EUR',
          availability: 'https://schema.org/InStock',
          priceValidUntil: _priceValidUntil,
          url: `${siteUrl.href}/pricing`,
        },
        {
          '@type': 'Offer',
          name: 'Racer',
          price: '69',
          priceCurrency: 'EUR',
          billingPeriod: 'P1Y',
          availability: 'https://schema.org/InStock',
          priceValidUntil: _priceValidUntil,
          url: `${siteUrl.href}/pricing`,
        },
        {
          '@type': 'Offer',
          name: 'World-Class',
          price: '109',
          priceCurrency: 'EUR',
          billingPeriod: 'P1Y',
          availability: 'https://schema.org/InStock',
          priceValidUntil: _priceValidUntil,
          url: `${siteUrl.href}/pricing`,
        },
      ],
      aggregateRating: {
        '@type': 'AggregateRating',
        ratingValue: '4.7',
        reviewCount: '48',
        bestRating: '5',
        worstRating: '1',
      },
    },
    {
      '@type': 'Organization',
      '@id': `${siteUrl.href}#organization`,
      name: 'Lap Coach',
      legalName: 'Lap Coach',
      url: siteUrl.href,
      logo: `${siteUrl.href}/logo/lap-coach-logo.svg`,
      foundingDate: '2025',
      foundingLocation: {
        '@type': 'Place',
        address: {
          '@type': 'PostalAddress',
          addressLocality: 'Nantes',
          addressCountry: 'FR',
        },
      },
      address: {
        '@type': 'PostalAddress',
        streetAddress: '5 rue Paré',
        addressLocality: 'Nantes',
        postalCode: '44000',
        addressCountry: 'FR',
      },
      contactPoint: {
        '@type': 'ContactPoint',
        contactType: 'customer support',
        email: 'support@lap-coach.racing',
        areaServed: 'Worldwide',
        availableLanguage: ['en', 'fr'],
      },
      sameAs: [
        'https://github.com/lap-coach',
      ],
    },
    {
      '@type': 'WebSite',
      '@id': `${siteUrl.href}#website`,
      name: BRAND.productName,
      url: siteUrl.href,
      inLanguage: 'en',
      publisher: { '@id': `${siteUrl.href}#organization` },
      potentialAction: {
        '@type': 'SearchAction',
        target: {
          '@type': 'EntryPoint',
          urlTemplate: `${siteUrl.href}/insights?q={search_term_string}`,
        },
        'query-input': 'required name=search_term_string',
      },
    },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  const fontVariables = `${inter.variable} ${spaceGrotesk.variable} ${spaceMono.variable}`;
  return (
    <html lang="en" className={fontVariables}>
      <head>
        {/* Critical CSS — inlined to prevent FOUC before stylesheet loads */}
        <style dangerouslySetInnerHTML={{ __html: [
          'html{background:#000;color:#F0EDE5;font-size:16px}',
          'body{font-family:var(--font-body),-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased;margin:0;overflow-x:hidden}',
          '.font-monument{font-family:var(--font-display),"Arial Black",sans-serif;font-weight:700;text-transform:uppercase}',
          '.room{position:relative;min-height:100vh;display:flex;flex-direction:column;justify-content:center;overflow:hidden}',
          '.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);border:0}',
        ].join('') }} />
        {/* Fonts self-hosted via next/font — no external CDN needed. */}
        <link rel="preconnect" href="https://api.lap-coach.racing" crossOrigin="anonymous" />
        <link rel="dns-prefetch" href="https://api.lap-coach.racing" />
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
