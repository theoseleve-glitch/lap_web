/**
 * Component-level test for the Turnstile step-up challenge on the login
 * page: a 428 challenge_required result from useAuth().login() must render
 * the widget, and completing the widget must resubmit login with the
 * obtained token.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const loginMock = vi.fn();

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    login: loginMock,
    verify2fa: vi.fn(),
    loading: false,
    error: null,
  }),
}));

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('@/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// Real TurnstileWidget loads a third-party script + iframe -- not something
// jsdom can meaningfully render. Stub it with a button that, when clicked,
// simulates the widget having obtained a token.
vi.mock('@/components/auth/TurnstileWidget', () => ({
  TurnstileWidget: ({ sitekey, onToken }: { sitekey: string; onToken: (t: string) => void }) => (
    <button type="button" data-sitekey={sitekey} onClick={() => onToken('mock-turnstile-token')}>
      complete-turnstile-challenge
    </button>
  ),
}));

import LoginPage from '@/app/(auth)/login/page';

beforeEach(() => {
  loginMock.mockReset();
});

describe('LoginPage Turnstile step-up challenge', () => {
  it('renders the Turnstile widget when login() returns challenge_required', async () => {
    loginMock.mockResolvedValueOnce({ challenge_required: true, sitekey: '1x00000000000000000000AA' });

    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText('auth.login.email'), {
      target: { value: 'flagged@example.com' },
    });
    fireEvent.change(screen.getByLabelText('auth.login.password'), {
      target: { value: 'whatever-password' },
    });
    fireEvent.click(screen.getByText('auth.login.submit'));

    await waitFor(() => {
      expect(screen.getByText('complete-turnstile-challenge')).toBeInTheDocument();
    });
    expect(screen.getByText('complete-turnstile-challenge')).toHaveAttribute(
      'data-sitekey',
      '1x00000000000000000000AA',
    );
  });

  it('does not render the widget on a normal (non-challenged) login', async () => {
    loginMock.mockResolvedValueOnce({
      access_token: 'tok',
      refresh_token: 'refresh',
      user: { id: 1, email: 'normal@example.com', display_name: 'Normal' },
    });

    render(<LoginPage />);
    fireEvent.change(screen.getByLabelText('auth.login.email'), {
      target: { value: 'normal@example.com' },
    });
    fireEvent.change(screen.getByLabelText('auth.login.password'), {
      target: { value: 'correct-password' },
    });
    fireEvent.click(screen.getByText('auth.login.submit'));

    await waitFor(() => expect(loginMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByText('complete-turnstile-challenge')).not.toBeInTheDocument();
  });

  it('resubmits login with the token once the widget completes the challenge', async () => {
    loginMock.mockResolvedValueOnce({ challenge_required: true, sitekey: 'site-key-xyz' });

    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText('auth.login.email'), {
      target: { value: 'flagged@example.com' },
    });
    fireEvent.change(screen.getByLabelText('auth.login.password'), {
      target: { value: 'correct-password' },
    });
    fireEvent.click(screen.getByText('auth.login.submit'));

    await waitFor(() => screen.getByText('complete-turnstile-challenge'));

    loginMock.mockResolvedValueOnce({
      access_token: 'tok-2',
      refresh_token: 'refresh-2',
      user: { id: 1, email: 'flagged@example.com', display_name: 'Flagged' },
    });

    fireEvent.click(screen.getByText('complete-turnstile-challenge'));

    await waitFor(() => expect(loginMock).toHaveBeenCalledTimes(2));
    const secondCallArgs = loginMock.mock.calls[1];
    expect(secondCallArgs[0]).toBe('flagged@example.com');
    expect(secondCallArgs[1]).toBe('correct-password');
    expect(secondCallArgs[3]).toBe('mock-turnstile-token');
  });
});
