import { describe, it, expect, vi } from 'vitest';

const redirectMock = vi.fn();

vi.mock('next/navigation', () => ({
  redirect: (path: string) => redirectMock(path),
}));

describe('/billing marketing page', () => {
  it('redirects to the real, authenticated billing page', async () => {
    const { default: BillingPage } = await import('./page');
    BillingPage();
    expect(redirectMock).toHaveBeenCalledWith('/app/account/billing');
  });
});
