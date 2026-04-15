import type { LeadPayload } from '@/lib/lead-types';

const RESEND_API_KEY = process.env.RESEND_API_KEY ?? '';
const CONTACT_EMAIL = 'contact@lap-coach.racing';
const EMAIL_FROM = process.env.EMAIL_FROM ?? 'LAP <noreply@lap-coach.racing>';

interface DeliveryOutcome {
  destination: string;
  status: 'sent' | 'skipped' | 'failed';
  error?: string;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function buildLeadEmailHtml(payload: LeadPayload): string {
  const rows: string[] = [];
  const add = (label: string, value: string | undefined) => {
    if (value && value.trim()) {
      rows.push(
        `<tr><td style="color:#8A8F98;padding:6px 12px 6px 0;vertical-align:top;white-space:nowrap">${label}</td>` +
        `<td style="color:#F3F0E8;padding:6px 0">${escapeHtml(value)}</td></tr>`
      );
    }
  };

  add('Type', payload.type);
  add('Name', payload.name);
  add('Email', payload.email);
  add('Company', payload.company);
  add('Phone', payload.phone);
  add('Plan', payload.plan);
  add('Seats', payload.seats);
  add('Preferred Date', payload.preferredDate);
  add('Source', payload.sourcePath);

  const messageHtml = payload.message
    ? `<div style="margin:16px 0;padding:12px;background:#1A1A1A;border:1px solid #2A2D35;color:#F3F0E8;white-space:pre-wrap">${escapeHtml(payload.message)}</div>`
    : '';

  return `
<div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto;background:#0B0C0F;padding:24px;color:#F3F0E8">
  <h2 style="color:#C9A84C;margin:0 0 16px">New ${escapeHtml(payload.type || 'contact')} lead</h2>
  <table style="border-collapse:collapse;width:100%">${rows.join('')}</table>
  ${messageHtml}
  <p style="color:#8A8F98;font-size:12px;margin-top:16px">
    Submitted ${new Date().toISOString()} via lap-coach.racing
  </p>
</div>`;
}

async function sendViaResend(payload: LeadPayload): Promise<DeliveryOutcome> {
  if (!RESEND_API_KEY) {
    return { destination: 'resend', status: 'skipped' };
  }

  try {
    const response = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        authorization: `Bearer ${RESEND_API_KEY}`,
      },
      body: JSON.stringify({
        from: EMAIL_FROM,
        to: [CONTACT_EMAIL],
        reply_to: payload.email || undefined,
        subject: `[LAP] New ${payload.type || 'contact'} from ${payload.name || 'unknown'}`,
        html: buildLeadEmailHtml(payload),
      }),
    });

    if (!response.ok) {
      const text = await response.text().catch(() => '');
      return { destination: 'resend', status: 'failed', error: `HTTP ${response.status}: ${text.slice(0, 200)}` };
    }

    return { destination: 'resend', status: 'sent' };
  } catch (error) {
    return {
      destination: 'resend',
      status: 'failed',
      error: error instanceof Error ? error.message : 'Unknown error',
    };
  }
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
      return { destination, status: 'failed', error: `HTTP ${response.status}` };
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
    // Primary: Resend direct email to contact@lap-coach.racing
    // Fallback: EMAIL_WEBHOOK_URL if configured
    RESEND_API_KEY
      ? sendViaResend(payload)
      : postToEndpoint(process.env.EMAIL_WEBHOOK_URL, 'email', payload),
  ]);

  return { crm, email };
}
