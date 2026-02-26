interface ConversionEvent {
  event: string;
  sourcePath?: string;
  leadType?: string;
  sessionId?: string;
  attribution?: Record<string, string>;
}

export async function sendServerConversion(event: ConversionEvent): Promise<void> {
  const endpoint = process.env.CONVERSION_WEBHOOK_URL;
  if (!endpoint) return;

  try {
    await fetch(endpoint, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        ...(process.env.CONVERSION_WEBHOOK_BEARER
          ? { authorization: `Bearer ${process.env.CONVERSION_WEBHOOK_BEARER}` }
          : {}),
      },
      body: JSON.stringify({
        ...event,
        timestamp: new Date().toISOString(),
      }),
    });
  } catch {
    // Conversion forwarding should not block UX or lead capture.
  }
}
