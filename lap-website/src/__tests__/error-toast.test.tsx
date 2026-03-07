/**
 * Tests for ErrorToast component.
 *
 * Verifies:
 *  - Renders error message and request_id
 *  - Shows "unknown" when requestId is missing
 *  - Copy button copies request_id to clipboard
 *  - Dismiss button hides the toast
 *  - Auto-dismiss after duration
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { ErrorToast } from '@/components/shared/ErrorToast';

describe('ErrorToast', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders error message', () => {
    render(<ErrorToast message="Something went wrong" requestId="req_abc" />);
    expect(screen.getByText('Something went wrong')).toBeDefined();
  });

  it('renders request_id when provided', () => {
    render(<ErrorToast message="Error" requestId="req_abc123" />);
    expect(screen.getByText(/req_abc123/)).toBeDefined();
  });

  it('shows "unknown" when requestId is missing', () => {
    render(<ErrorToast message="Error" />);
    expect(screen.getByText(/unknown/)).toBeDefined();
  });

  it('has role="alert" for accessibility', () => {
    render(<ErrorToast message="Error" requestId="req_1" />);
    expect(screen.getByRole('alert')).toBeDefined();
  });

  it('calls onDismiss when dismiss button is clicked', () => {
    const onDismiss = vi.fn();
    render(<ErrorToast message="Error" onDismiss={onDismiss} duration={0} />);
    fireEvent.click(screen.getByLabelText('Dismiss error'));
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it('auto-dismisses after duration', () => {
    const onDismiss = vi.fn();
    render(<ErrorToast message="Error" duration={3000} onDismiss={onDismiss} />);
    expect(screen.getByRole('alert')).toBeDefined();

    act(() => { vi.advanceTimersByTime(3000); });

    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it('copy button has accessible label with request_id', () => {
    render(<ErrorToast message="Error" requestId="req_xyz" />);
    expect(screen.getByLabelText('Copy request ID req_xyz')).toBeDefined();
  });

  it('copy button copies requestId to clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: { writeText },
    });

    vi.useRealTimers();
    render(<ErrorToast message="Error" requestId="req_copy_me" duration={0} />);
    fireEvent.click(screen.getByLabelText('Copy request ID req_copy_me'));

    // Wait for async clipboard call
    await vi.waitFor(() => {
      expect(writeText).toHaveBeenCalledWith('req_copy_me');
    });
  });
});
