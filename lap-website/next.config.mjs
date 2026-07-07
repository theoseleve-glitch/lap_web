// Build-time environment validation — fail fast if critical vars are missing
if (process.env.NODE_ENV === 'production' && !process.env.NEXT_PUBLIC_API_URL) {
  throw new Error(
    'Missing NEXT_PUBLIC_API_URL — set it before building for production.\n' +
    'Example: NEXT_PUBLIC_API_URL=https://api.lap-coach.racing npm run build',
  );
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  compiler: {
    removeConsole: process.env.NODE_ENV === 'production' ? { exclude: ['error', 'warn'] } : false,
  },
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: true },  // App Router type-gen race condition on Windows
  images: { unoptimized: true },
  trailingSlash: false,
  poweredByHeader: false,
  output: 'standalone',
  experimental: {
    workerThreads: false,
    cpus: 1,
  },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
          { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains' },
          { key: 'X-XSS-Protection', value: '1; mode=block' },
          {
            key: 'Content-Security-Policy',
            value: [
              "default-src 'self'",
              // challenges.cloudflare.com: Turnstile step-up challenge widget
              // script (auth/turnstile.py + auth/lockout.py::challenge_required
              // on the backend gate WHEN it's shown; unconfigured = never shown).
              "script-src 'self' 'unsafe-inline' https://plausible.io https://challenges.cloudflare.com",
              "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
              "font-src 'self' https://fonts.gstatic.com",
              "img-src 'self' data: blob: https://*.tile.openstreetmap.org https://*.basemaps.cartocdn.com",
              "connect-src 'self' https://api.lap-coach.racing https://plausible.io https://*.ingest.sentry.io https://challenges.cloudflare.com",
              // Turnstile renders its interactive challenge in an iframe.
              "frame-src https://challenges.cloudflare.com",
              "worker-src 'self' blob:",
              "object-src 'none'",
              "frame-ancestors 'none'",
              "base-uri 'self'",
              "form-action 'self'",
              "upgrade-insecure-requests",
              "report-uri https://api.lap-coach.racing/csp-report",
            ].join('; '),
          },
        ],
      },
    ];
  },
};

export default nextConfig;
