import type { LeadPayload, LeadType } from '@/lib/lead-types';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type ValidationResult =
  | { valid: true; data: LeadPayload }
  | { valid: false; fieldErrors: Record<string, string> };

function validateRequiredString(
  value: unknown,
  field: string,
  fieldErrors: Record<string, string>,
): string {
  if (typeof value !== 'string' || value.trim().length === 0) {
    fieldErrors[field] = 'Required';
    return '';
  }
  return value.trim();
}

function optionalString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : undefined;
}

export function validateLeadPayload(raw: unknown): ValidationResult {
  if (!raw || typeof raw !== 'object') {
    return { valid: false, fieldErrors: { form: 'Invalid request body' } };
  }

  const input = raw as Record<string, unknown>;
  const fieldErrors: Record<string, string> = {};
  const type = validateRequiredString(input.type, 'type', fieldErrors) as LeadType;

  const name = validateRequiredString(input.name, 'name', fieldErrors);
  const email = validateRequiredString(input.email, 'email', fieldErrors).toLowerCase();

  if (email && !EMAIL_RE.test(email)) {
    fieldErrors.email = 'Invalid email format';
  }

  if (!['contact', 'demo', 'book', 'waitlist'].includes(type)) {
    fieldErrors.type = 'Unsupported lead type';
  }

  if (type === 'waitlist' && !optionalString(input.message)) {
    fieldErrors.message = 'Please share what you want early access to';
  }

  if (type === 'book' && !optionalString(input.preferredDate)) {
    fieldErrors.preferredDate = 'Please provide a preferred date';
  }

  if ((type === 'demo' || type === 'book') && !optionalString(input.company)) {
    fieldErrors.company = 'Company is required for demo bookings';
  }

  if (Object.keys(fieldErrors).length > 0) {
    return { valid: false, fieldErrors };
  }

  return {
    valid: true,
    data: {
      type,
      name,
      email,
      company: optionalString(input.company),
      phone: optionalString(input.phone),
      message: optionalString(input.message),
      plan: optionalString(input.plan),
      persona: optionalString(input.persona),
      seats: optionalString(input.seats),
      preferredDate: optionalString(input.preferredDate),
      sourcePath: optionalString(input.sourcePath),
      utm:
        input.utm && typeof input.utm === 'object'
          ? (input.utm as Record<string, string>)
          : undefined,
      sessionId: optionalString(input.sessionId),
    },
  };
}
