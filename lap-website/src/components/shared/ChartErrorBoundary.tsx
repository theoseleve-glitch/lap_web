'use client';

import { Component, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  chartName?: string;
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
    console.error(`Chart error (${this.props.chartName ?? 'unknown'}):`, error);
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback ?? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-6 text-center">
          <p className="text-steel text-sm">
            Chart failed to render.{' '}
            <button
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
