'use client';

import { Component, type ReactNode } from 'react';
import { logger } from '@/lib/logger';

interface Props {
  children: ReactNode;
  /** Section name for logging. */
  name?: string;
  /** Custom fallback UI. If omitted, a default recovery card is shown. */
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Lightweight error boundary for page sections.
 *
 * Catches render errors in its subtree and shows a recovery UI
 * instead of crashing the entire page. Reports errors to the logger
 * (which forwards to Sentry in production).
 *
 * Usage:
 *   <SectionErrorBoundary name="scores">
 *     <ScoresPanel />
 *   </SectionErrorBoundary>
 */
export class SectionErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error) {
    logger.error(`Section error (${this.props.name ?? 'unknown'}):`, error);
  }

  private handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="bg-concrete rounded-lg border border-steel/20 p-6">
          <p className="text-steel text-sm mb-2">
            This section failed to load.
          </p>
          <button
            type="button"
            onClick={this.handleRetry}
            className="text-pit-orange text-sm font-telemetry uppercase tracking-wider hover:underline"
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
