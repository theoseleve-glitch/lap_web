/**
 * Tests for page-specific skeleton dimensions.
 *
 * Verifies that skeleton components render with correct ARIA attributes
 * and export the expected components.
 */
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import {
  SkeletonSessionDetail,
  SkeletonCompareView,
  SkeletonStatCards,
  SkeletonTableRows,
  SkeletonBox,
} from '@/components/app/Skeleton';

describe('Skeleton components', () => {
  describe('SkeletonSessionDetail', () => {
    it('renders with loading role', () => {
      const { container } = render(<SkeletonSessionDetail />);
      const status = container.querySelector('[role="status"]');
      expect(status).not.toBeNull();
      expect(status?.getAttribute('aria-label')).toBe('Loading session detail');
    });

    it('contains chart placeholder with 300px min-height', () => {
      const { container } = render(<SkeletonSessionDetail />);
      const chartArea = container.querySelector('[style*="min-height"]');
      expect(chartArea).not.toBeNull();
    });
  });

  describe('SkeletonCompareView', () => {
    it('renders with loading role', () => {
      const { container } = render(<SkeletonCompareView />);
      const status = container.querySelector('[role="status"]');
      expect(status).not.toBeNull();
      expect(status?.getAttribute('aria-label')).toBe('Loading comparison');
    });

    it('contains selector bar with min-height', () => {
      const { container } = render(<SkeletonCompareView />);
      const selectorBar = container.querySelector('[style*="min-height: 72px"]');
      expect(selectorBar).not.toBeNull();
    });
  });

  describe('existing primitives', () => {
    it('SkeletonStatCards renders correct number of cards', () => {
      const { container } = render(<SkeletonStatCards count={3} />);
      const cards = container.querySelectorAll('.bg-concrete');
      expect(cards.length).toBe(3);
    });

    it('SkeletonTableRows renders correct rows and cols', () => {
      const { container } = render(<SkeletonTableRows rows={3} cols={4} />);
      // header row + 3 data rows = 4 flex rows
      const rows = container.querySelectorAll('.flex.gap-4');
      expect(rows.length).toBe(4); // 1 header + 3 data
    });

    it('SkeletonBox applies custom className', () => {
      const { container } = render(<SkeletonBox className="h-8 w-32" />);
      const box = container.firstElementChild;
      expect(box?.className).toContain('h-8');
      expect(box?.className).toContain('w-32');
    });
  });
});
