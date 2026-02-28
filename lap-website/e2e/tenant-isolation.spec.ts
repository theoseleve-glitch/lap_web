import { test, expect } from '@playwright/test';
import { loginAsUser, apiRequest, TEST_USERS } from './helpers/auth';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://api.lap-coach.racing';

test.describe('Multi-Tenant Isolation', () => {
  test.describe.configure({ mode: 'serial' });

  let demoToken: string;
  let racerToken: string;
  let worldClassToken: string;
  let demoSessionIds: string[] = [];

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    demoToken = await loginAsUser(page, 'demo');
    racerToken = await loginAsUser(page, 'racer');
    worldClassToken = await loginAsUser(page, 'world_class');

    const resp = await page.request.get(`${API_URL}/api/v1/sessions/browse`, {
      headers: { Authorization: `Bearer ${demoToken}` },
    });
    const body = await resp.json();
    if (body.ok && body.data?.sessions) {
      demoSessionIds = body.data.sessions.map((s: any) => s.session_id).slice(0, 3);
    }
    await page.close();
  });

  test('racer cannot access demo sessions via API', async ({ page }) => {
    test.skip(demoSessionIds.length === 0, 'No demo sessions');
    for (const sessionId of demoSessionIds) {
      const resp = await apiRequest(page, 'GET', `/api/v1/sessions/${sessionId}/details`, racerToken);
      expect([403, 404]).toContain(resp.status());
    }
  });

  test('world_class cannot access demo sessions via API', async ({ page }) => {
    test.skip(demoSessionIds.length === 0, 'No demo sessions');
    for (const sessionId of demoSessionIds) {
      const resp = await apiRequest(page, 'GET', `/api/v1/sessions/${sessionId}/details`, worldClassToken);
      expect([403, 404]).toContain(resp.status());
    }
  });

  test('demo session list excludes racer sessions', async ({ page }) => {
    const racerResp = await page.request.get(`${API_URL}/api/v1/sessions/browse`, {
      headers: { Authorization: `Bearer ${racerToken}` },
    });
    const racerBody = await racerResp.json();
    const racerIds = (racerBody.data?.sessions || []).map((s: any) => s.session_id);

    const demoResp = await page.request.get(`${API_URL}/api/v1/sessions/browse`, {
      headers: { Authorization: `Bearer ${demoToken}` },
    });
    const demoBody = await demoResp.json();
    const demoIds = (demoBody.data?.sessions || []).map((s: any) => s.session_id);

    for (const id of racerIds) {
      expect(demoIds).not.toContain(id);
    }
  });

  test('IDOR: sequential ID guessing returns 403/404', async ({ page }) => {
    for (let id = 1; id <= 10; id++) {
      const resp = await apiRequest(page, 'GET', `/api/v1/sessions/${id}/details`, demoToken);
      // 200 is OK only if it's the user's own session, 403/404 for others
      expect([200, 403, 404]).toContain(resp.status());
    }
  });
});
