/**
 * Web Vitals collection — LCP, CLS, INP.
 *
 * Uses the web-vitals library (or PerformanceObserver fallback).
 * Reports to Plausible custom events and console in dev.
 *
 * Tagged with build version + route for per-release tracking.
 */

import { hasAnalyticsConsent } from '@/lib/consent';

const BUILD_VERSION = process.env.NEXT_PUBLIC_BUILD_VERSION ?? 'dev';

interface VitalMetric {
  name: string;
  value: number;
  rating: 'good' | 'needs-improvement' | 'poor';
  navigationType: string;
}

type ReportFn = (metric: VitalMetric) => void;

/**
 * Collect a single Web Vital via PerformanceObserver.
 * Lightweight alternative to the web-vitals package.
 */
function observeLCP(onReport: ReportFn): void {
  if (typeof PerformanceObserver === 'undefined') return;
  try {
    const observer = new PerformanceObserver((list) => {
      const entries = list.getEntries();
      const last = entries[entries.length - 1] as PerformanceEntry & { startTime: number };
      if (!last) return;
      const value = last.startTime;
      onReport({
        name: 'LCP',
        value,
        rating: value <= 2500 ? 'good' : value <= 4000 ? 'needs-improvement' : 'poor',
        navigationType: getNavigationType(),
      });
    });
    observer.observe({ type: 'largest-contentful-paint', buffered: true });
  } catch { /* unsupported */ }
}

function observeCLS(onReport: ReportFn): void {
  if (typeof PerformanceObserver === 'undefined') return;
  try {
    let clsValue = 0;
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const layoutShift = entry as PerformanceEntry & { hadRecentInput: boolean; value: number };
        if (!layoutShift.hadRecentInput) {
          clsValue += layoutShift.value;
        }
      }
    });
    observer.observe({ type: 'layout-shift', buffered: true });

    // Report on page hide
    const report = () => {
      onReport({
        name: 'CLS',
        value: clsValue,
        rating: clsValue <= 0.1 ? 'good' : clsValue <= 0.25 ? 'needs-improvement' : 'poor',
        navigationType: getNavigationType(),
      });
    };
    addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') report();
    }, { once: true });
  } catch { /* unsupported */ }
}

function observeINP(onReport: ReportFn): void {
  if (typeof PerformanceObserver === 'undefined') return;
  try {
    let maxDuration = 0;
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const evt = entry as PerformanceEntry & { duration: number };
        if (evt.duration > maxDuration) maxDuration = evt.duration;
      }
    });
    observer.observe({ type: 'event', buffered: true });

    addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden' && maxDuration > 0) {
        onReport({
          name: 'INP',
          value: maxDuration,
          rating: maxDuration <= 200 ? 'good' : maxDuration <= 500 ? 'needs-improvement' : 'poor',
          navigationType: getNavigationType(),
        });
      }
    }, { once: true });
  } catch { /* unsupported */ }
}

function getNavigationType(): string {
  if (typeof performance === 'undefined') return 'unknown';
  const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined;
  return nav?.type ?? 'unknown';
}

function sendToPlausible(metric: VitalMetric): void {
  if (!hasAnalyticsConsent()) return;

  const plausible = (window as Record<string, unknown>).plausible as
    | ((event: string, opts: { props: Record<string, string | number> }) => void)
    | undefined;

  if (plausible) {
    plausible('Web Vital', {
      props: {
        metric: metric.name,
        value: Math.round(metric.name === 'CLS' ? metric.value * 1000 : metric.value),
        rating: metric.rating,
        version: BUILD_VERSION,
        path: location.pathname,
      },
    });
  }
}

/**
 * Initialize Web Vitals collection.
 * Call once from root layout (client-side only).
 */
export function initWebVitals(): void {
  if (typeof window === 'undefined') return;

  const report: ReportFn = (metric) => {
    if (process.env.NODE_ENV === 'development') {
      const color = metric.rating === 'good' ? '#22c55e' : metric.rating === 'needs-improvement' ? '#f59e0b' : '#ef4444';
      // eslint-disable-next-line no-console
      console.log(
        `%c${metric.name} %c${metric.name === 'CLS' ? metric.value.toFixed(3) : Math.round(metric.value) + 'ms'} %c${metric.rating}`,
        'font-weight:bold',
        `color:${color};font-weight:bold`,
        `color:${color}`,
      );
    }
    sendToPlausible(metric);
  };

  observeLCP(report);
  observeCLS(report);
  observeINP(report);
}
