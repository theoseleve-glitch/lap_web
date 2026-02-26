import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { ChromeLayout } from '@/components/chrome/ChromeLayout';
import './globals.css';

export const metadata: Metadata = {
  title: 'LAP — Motorsport Telemetry Analysis | Find Time.',
  description:
    'Upload your telemetry. Get a score, corner-by-corner coaching, and a plan to go faster. Physics-based analysis for kart, car, and sim drivers. Free starter plan.',
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
      </body>
    </html>
  );
}
