import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import Script from 'next/script';
import { ChromeLayout } from '@/components/chrome/ChromeLayout';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL('https://lap.racing'),
  title: 'LAP — Find Time. Motorsport Telemetry Analysis.',
  description: 'Immersive telemetry analysis for kart and car drivers. Upload your session, find where you lose time, get actionable coaching. Trusted by tracks and drivers.',
  keywords: ['telemetry', 'motorsport', 'karting', 'lap time', 'data analysis', 'coaching', 'racing'],
  authors: [{ name: 'LAP Racing' }],
  openGraph: {
    title: 'LAP — Find Time.',
    description: 'Motorsport telemetry analysis. Upload. Analyze. Find time.',
    type: 'website',
    url: 'https://lap.racing',
    siteName: 'LAP',
    images: [{ url: '/og-image.jpg', width: 1200, height: 630, alt: 'LAP — Find Time' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'LAP — Find Time.',
    description: 'Motorsport telemetry analysis. Upload. Analyze. Find time.',
    images: ['/og-image.jpg'],
  },
  alternates: {
    canonical: 'https://lap.racing',
  },
  robots: { index: true, follow: true },
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
        { '@type': 'Offer', name: 'Starter', price: '0', priceCurrency: 'EUR' },
        { '@type': 'Offer', name: 'Performance', price: '69', priceCurrency: 'EUR', billingPeriod: 'P1Y' },
        { '@type': 'Offer', name: 'Pro Racer', price: '109', priceCurrency: 'EUR', billingPeriod: 'P1Y' },
      ],
    },
    {
      '@type': 'Organization',
      name: 'LAP Racing',
      url: 'https://lap.racing',
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
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400&family=Inter:wght@400;500&family=Teko:wght@600;700&display=swap&subset=latin"
          rel="stylesheet"
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      </head>
      <body className="relative bg-asphalt text-chalk texture-grain">
        <a
          href="#pit-stop"
          className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-1/2 focus:-translate-x-1/2 focus:z-[200] font-telemetry bg-asphalt text-chalk px-4 py-2 border-2 border-chalk"
        >
          Skip to pricing
        </a>
        <ChromeLayout>
          {children}
        </ChromeLayout>
        <Script
          defer
          data-domain="lap.racing"
          src="https://plausible.io/js/script.js"
          strategy="afterInteractive"
        />
      </body>
    </html>
  );
}
