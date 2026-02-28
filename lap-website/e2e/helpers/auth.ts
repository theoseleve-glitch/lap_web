import { Page } from '@playwright/test';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://api.lap-coach.racing';

export interface TestUser {
  email: string;
  password: string;
  tier: 'demo' | 'racer' | 'world_class';
}

// Credentials loaded from environment variables — never hardcode in source.
// Set E2E_DEMO_EMAIL, E2E_RACER_EMAIL, E2E_WC_EMAIL, E2E_TEST_PASSWORD.
export const TEST_USERS: Record<string, TestUser> = {
  demo: {
    email: process.env.E2E_DEMO_EMAIL || '',
    password: process.env.E2E_TEST_PASSWORD || '',
    tier: 'demo',
  },
  racer: {
    email: process.env.E2E_RACER_EMAIL || '',
    password: process.env.E2E_TEST_PASSWORD || '',
    tier: 'racer',
  },
  world_class: {
    email: process.env.E2E_WC_EMAIL || '',
    password: process.env.E2E_TEST_PASSWORD || '',
    tier: 'world_class',
  },
};

/**
 * Login via the real API (not mocked) and return the access token.
 */
export async function loginAsUser(page: Page, tier: keyof typeof TEST_USERS): Promise<string> {
  const user = TEST_USERS[tier];

  const response = await page.request.post(`${API_URL}/auth/login`, {
    data: { email: user.email, password: user.password },
  });

  const body = await response.json();
  if (!body.ok) {
    throw new Error(`Login failed for ${user.email}: ${JSON.stringify(body.error)}`);
  }

  return body.data.access_token;
}

/**
 * Login via the UI login form (real E2E flow).
 */
export async function loginViaUI(page: Page, tier: keyof typeof TEST_USERS): Promise<void> {
  const user = TEST_USERS[tier];

  await page.goto('/login');
  await page.getByPlaceholder('driver@example.com').fill(user.email);
  await page.getByPlaceholder(/password|••••/i).fill(user.password);
  await page.getByRole('button', { name: /sign in/i }).click();

  await page.waitForURL(/\/app/, { timeout: 15000 });
}

/**
 * Make an authenticated API request.
 */
export async function apiRequest(
  page: Page,
  method: string,
  path: string,
  token: string,
  body?: any,
) {
  const url = `${API_URL}${path}`;
  const options: any = {
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  };
  if (body) {
    options.data = body;
  }

  if (method === 'GET') return page.request.get(url, options);
  if (method === 'POST') return page.request.post(url, options);
  if (method === 'PUT') return page.request.put(url, options);
  if (method === 'DELETE') return page.request.delete(url, options);

  throw new Error(`Unsupported method: ${method}`);
}
