import { ApiError } from './api-client';

interface EnvelopeError {
  code?: string;
  message?: string;
  details?: Array<{ field?: string; message: string }>;
}

interface Envelope<T> {
  ok?: boolean;
  data?: T;
  error?: EnvelopeError;
  meta?: { request_id?: string };
}

function looksLikeEnvelope<T>(value: unknown): value is Envelope<T> {
  return typeof value === 'object' && value !== null && ('ok' in value || 'data' in value || 'error' in value);
}

/** Extract request_id from JSON meta or X-Request-Id header. */
function extractRequestId(response: Response, body: unknown): string | undefined {
  if (looksLikeEnvelope(body) && body.meta?.request_id) {
    return body.meta.request_id;
  }
  return response.headers.get('X-Request-Id') ?? undefined;
}

export async function parseEnvelopeOrThrow<T>(response: Response): Promise<T> {
  const contentType = response.headers.get('content-type') || '';
  const isJson = contentType.includes('application/json');
  const rawBody = await response.text();

  let parsedBody: unknown = null;
  if (isJson && rawBody) {
    try {
      parsedBody = JSON.parse(rawBody);
    } catch {
      parsedBody = null;
    }
  }

  const requestId = extractRequestId(response, parsedBody);

  if (looksLikeEnvelope<T>(parsedBody) && parsedBody.ok) {
    return parsedBody.data as T;
  }

  if (looksLikeEnvelope<T>(parsedBody)) {
    throw new ApiError(
      parsedBody.error?.code ?? 'UNKNOWN',
      parsedBody.error?.message ?? 'Request failed',
      response.status,
      parsedBody.error?.details,
      requestId,
    );
  }

  const fallbackMessage = response.ok
    ? 'Unexpected response from server.'
    : `Request failed (${response.status}).`;

  const plainMessage = rawBody.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  throw new ApiError(
    'INVALID_RESPONSE',
    plainMessage ? plainMessage.slice(0, 220) : fallbackMessage,
    response.status,
    undefined,
    requestId,
  );
}
