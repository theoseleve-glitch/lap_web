export type LeadType = 'contact' | 'demo' | 'book' | 'waitlist';

export interface LeadPayload {
  type: LeadType;
  name: string;
  email: string;
  company?: string;
  phone?: string;
  message?: string;
  plan?: string;
  persona?: string;
  seats?: string;
  preferredDate?: string;
  sourcePath?: string;
  utm?: Record<string, string>;
  sessionId?: string;
}

export interface LeadApiSuccess {
  ok: true;
  message: string;
}

export interface LeadApiError {
  ok: false;
  message: string;
  fieldErrors?: Record<string, string>;
}
