'use client';
import * as Sentry from '@sentry/browser';

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
let initialized = false;

export function initSentry() {
  if (initialized || !dsn || typeof window === 'undefined') return;
  Sentry.init({
    dsn,
    environment: process.env.NODE_ENV,
    tracesSampleRate: 0.1,
  });
  initialized = true;
}

export { Sentry };
