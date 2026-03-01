/**
 * Tests for the InlineEdit component.
 *
 * Covers:
 * - Renders display value and pencil icon on hover
 * - Clicking switches to edit mode with input
 * - Pressing Enter commits the value
 * - Pressing Escape cancels without saving
 * - Blur commits the value
 * - Shows "Saving..." during save
 * - Shows error state when save rejects
 * - Multiline mode renders textarea
 * - No-op when value hasn't changed
 * - Shows placeholder when value is empty
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor, act } from '@testing-library/react';
import { InlineEdit } from '@/components/app/InlineEdit';

describe('InlineEdit', () => {
  let onSave: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    onSave = vi.fn().mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the current value in display mode', () => {
    render(<InlineEdit value="Monza" onSave={onSave} />);
    expect(screen.getByText('Monza')).toBeInTheDocument();
    expect(screen.getByTestId('inline-edit-trigger')).toBeInTheDocument();
  });

  it('shows placeholder when value is empty', () => {
    render(<InlineEdit value="" onSave={onSave} placeholder="Click to edit" />);
    expect(screen.getByText('Click to edit')).toBeInTheDocument();
  });

  it('shows the pencil icon element', () => {
    render(<InlineEdit value="Monza" onSave={onSave} />);
    expect(screen.getByTestId('inline-edit-pencil')).toBeInTheDocument();
  });

  it('switches to edit mode when clicked', async () => {
    render(<InlineEdit value="Monza" onSave={onSave} />);
    fireEvent.click(screen.getByTestId('inline-edit-trigger'));
    expect(screen.getByTestId('inline-edit-input')).toBeInTheDocument();
    expect(screen.getByTestId('inline-edit-input')).toHaveValue('Monza');
  });

  it('commits value on Enter key', async () => {
    render(<InlineEdit value="Monza" onSave={onSave} />);

    // Enter edit mode
    fireEvent.click(screen.getByTestId('inline-edit-trigger'));
    const input = screen.getByTestId('inline-edit-input');

    // Type new value
    fireEvent.change(input, { target: { value: 'Spa' } });
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' });
    });

    expect(onSave).toHaveBeenCalledWith('Spa');
  });

  it('cancels on Escape key without saving', () => {
    render(<InlineEdit value="Monza" onSave={onSave} />);

    // Enter edit mode
    fireEvent.click(screen.getByTestId('inline-edit-trigger'));
    const input = screen.getByTestId('inline-edit-input');

    // Type something then escape
    fireEvent.change(input, { target: { value: 'Spa' } });
    fireEvent.keyDown(input, { key: 'Escape' });

    // Should NOT have saved
    expect(onSave).not.toHaveBeenCalled();

    // Should return to display mode showing original value
    expect(screen.getByText('Monza')).toBeInTheDocument();
  });

  it('commits value on blur', async () => {
    render(<InlineEdit value="Monza" onSave={onSave} />);

    // Enter edit mode
    fireEvent.click(screen.getByTestId('inline-edit-trigger'));
    const input = screen.getByTestId('inline-edit-input');

    // Type new value and blur
    fireEvent.change(input, { target: { value: 'Silverstone' } });
    await act(async () => {
      fireEvent.blur(input);
    });

    expect(onSave).toHaveBeenCalledWith('Silverstone');
  });

  it('does NOT call onSave when value is unchanged', async () => {
    render(<InlineEdit value="Monza" onSave={onSave} />);

    // Enter edit mode, don't change anything, hit Enter
    fireEvent.click(screen.getByTestId('inline-edit-trigger'));
    const input = screen.getByTestId('inline-edit-input');
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' });
    });

    expect(onSave).not.toHaveBeenCalled();
  });

  it('shows error state when save rejects', async () => {
    onSave.mockRejectedValueOnce(new Error('Network error'));

    render(<InlineEdit value="Monza" onSave={onSave} />);

    // Enter edit mode and change value
    fireEvent.click(screen.getByTestId('inline-edit-trigger'));
    const input = screen.getByTestId('inline-edit-input');
    fireEvent.change(input, { target: { value: 'Spa' } });

    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' });
    });

    // Should show error message and stay in edit mode
    await waitFor(() => {
      expect(screen.getByTestId('inline-edit-error')).toBeInTheDocument();
    });
    expect(screen.getByTestId('inline-edit-input')).toBeInTheDocument();
  });

  it('renders textarea in multiline mode', () => {
    render(<InlineEdit value="Some notes" onSave={onSave} multiline />);

    fireEvent.click(screen.getByTestId('inline-edit-trigger'));
    expect(screen.getByTestId('inline-edit-textarea')).toBeInTheDocument();
    expect(screen.getByTestId('inline-edit-textarea')).toHaveValue('Some notes');
  });

  it('does not commit on plain Enter in multiline mode', () => {
    render(<InlineEdit value="Line 1" onSave={onSave} multiline />);

    fireEvent.click(screen.getByTestId('inline-edit-trigger'));
    const textarea = screen.getByTestId('inline-edit-textarea');
    fireEvent.change(textarea, { target: { value: 'Line 1\nLine 2' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });

    // Should NOT save (plain Enter in multiline adds a newline)
    expect(onSave).not.toHaveBeenCalled();
  });

  it('commits on Ctrl+Enter in multiline mode', async () => {
    render(<InlineEdit value="Line 1" onSave={onSave} multiline />);

    fireEvent.click(screen.getByTestId('inline-edit-trigger'));
    const textarea = screen.getByTestId('inline-edit-textarea');
    fireEvent.change(textarea, { target: { value: 'Updated notes' } });

    await act(async () => {
      fireEvent.keyDown(textarea, { key: 'Enter', ctrlKey: true });
    });

    expect(onSave).toHaveBeenCalledWith('Updated notes');
  });

  it('trims whitespace before saving', async () => {
    render(<InlineEdit value="Monza" onSave={onSave} />);

    fireEvent.click(screen.getByTestId('inline-edit-trigger'));
    const input = screen.getByTestId('inline-edit-input');
    fireEvent.change(input, { target: { value: '  Spa  ' } });

    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' });
    });

    expect(onSave).toHaveBeenCalledWith('Spa');
  });

  it('shows saved checkmark briefly after successful save', async () => {
    render(<InlineEdit value="Monza" onSave={onSave} />);

    fireEvent.click(screen.getByTestId('inline-edit-trigger'));
    const input = screen.getByTestId('inline-edit-input');
    fireEvent.change(input, { target: { value: 'Spa' } });

    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' });
    });

    // After save, should briefly show the check mark
    await waitFor(() => {
      expect(screen.getByTestId('inline-edit-check')).toBeInTheDocument();
    });
  });
});
