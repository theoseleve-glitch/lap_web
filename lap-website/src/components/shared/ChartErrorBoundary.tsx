'use client';

import { Component, type ReactNode } from 'react';
import { logger } from '@/lib/logger';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  chartName?: string;
  /** Preserve this height in error state to prevent CLS. */
  minHeight?: string;
}

interface State {
  hasError: boolean;
}

export class ChartErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error) {
    logger.error(`Chart error (${this.props.chartName ?? 'unknown'}):`, error);
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback ?? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-6 text-center" style={{ minHeight: this.props.minHeight }}>
          <p className="text-steel text-sm">
            Chart failed to render.{' '}
            <button
              type="button"
              onClick={() => this.setState({ hasError: false })}
              className="text-pit-orange hover:underline"
            >
              Retry
            </button>
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}
