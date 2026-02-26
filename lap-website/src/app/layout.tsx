import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'LAP — Motorsport Telemetry Analysis | Find Time.',
  description:
    'Upload your telemetry. Get a score, corner-by-corner coaching, and a plan to go faster. Physics-based analysis for kart, car, and sim drivers. Free starter plan.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body className="relative bg-asphalt text-chalk texture-grain">
        {children}
      </body>
    </html>
  );
}
