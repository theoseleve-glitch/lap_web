import type { LeadPayload } from '@/lib/lead-types';

interface DeliveryOutcome {
  destination: string;
  status: 'sent' | 'skipped' | 'failed';
  error?: string;
}

async function postToEndpoint(
  endpoint: string | undefined,
  destination: string,
  payload: LeadPayload,
): Promise<DeliveryOutcome> {
  if (!endpoint) {
    return { destination, status: 'skipped' };
  }

  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        ...(process.env.LEAD_WEBHOOK_BEARER
          ? { authorization: `Bearer ${process.env.LEAD_WEBHOOK_BEARER}` }
          : {}),
      },
      body: JSON.stringify({
        submittedAt: new Date().toISOString(),
        lead: payload,
      }),
    });

    if (!response.ok) {
      return {
        destination,
        status: 'failed',
        error: `HTTP ${response.status}`,
      };
    }

    return { destination, status: 'sent' };
  } catch (error) {
    return {
      destination,
      status: 'failed',
      error: error instanceof Error ? error.message : 'Unknown error',
    };
  }
}

export async function deliverLead(payload: LeadPayload): Promise<{
  crm: DeliveryOutcome;
  email: DeliveryOutcome;
}> {
  const [crm, email] = await Promise.all([
    postToEndpoint(process.env.CRM_WEBHOOK_URL, 'crm', payload),
    postToEndpoint(process.env.EMAIL_WEBHOOK_URL, 'email', payload),
  ]);

  return { crm, email };
}
