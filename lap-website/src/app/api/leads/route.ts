import { NextResponse } from 'next/server';
import { validateLeadPayload } from '@/lib/lead-validation';
import { deliverLead } from '@/lib/lead-delivery';
import { sendServerConversion } from '@/lib/server-conversions';

function parseAttributionCookie(value: string | undefined): Record<string, string> | undefined {
  if (!value) return undefined;
  try {
    return JSON.parse(decodeURIComponent(value)) as Record<string, string>;
  } catch {
    return undefined;
  }
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const validation = validateLeadPayload(body);

  if (!validation.valid) {
    return NextResponse.json(
      {
        ok: false,
        message: 'Validation failed',
        fieldErrors: validation.fieldErrors,
      },
      { status: 400 },
    );
  }

  const attribution = parseAttributionCookie(
    request.headers
      .get('cookie')
      ?.split(';')
      .map((part) => part.trim())
      .find((part) => part.startsWith('lap_attribution='))
      ?.split('=')[1],
  );

  const payload = {
    ...validation.data,
    utm: validation.data.utm ?? attribution,
    sessionId:
      validation.data.sessionId ??
      request.headers
        .get('cookie')
        ?.split(';')
        .map((part) => part.trim())
        .find((part) => part.startsWith('lap_session_id='))
        ?.split('=')[1],
  };

  const delivery = await deliverLead(payload);
  const sentCount = [delivery.crm, delivery.email].filter((item) => item.status === 'sent').length;
  const failedCount = [delivery.crm, delivery.email].filter((item) => item.status === 'failed').length;

  await sendServerConversion({
    event: 'lead_submitted',
    leadType: payload.type,
    sourcePath: payload.sourcePath,
    attribution: payload.utm,
    sessionId: payload.sessionId,
  });

  if (failedCount > 0 && sentCount === 0) {
    return NextResponse.json(
      {
        ok: false,
        message: 'Lead could not be delivered to CRM/email endpoints.',
      },
      { status: 502 },
    );
  }

  return NextResponse.json({
    ok: true,
    message:
      sentCount > 0
        ? 'Lead captured and forwarded successfully.'
        : 'Lead captured. CRM/email endpoints are not configured yet.',
  });
}
