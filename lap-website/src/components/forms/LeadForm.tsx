'use client';

import { useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { LeadType } from '@/lib/lead-types';
import {
  getAttributionFromCookie,
  getSessionIdFromCookie,
  trackFormSubmitError,
  trackFormSubmitStart,
  trackFormSubmitSuccess,
} from '@/lib/analytics';
import { PitButton } from '@/components/ui/PitButton';

interface LeadFormProps {
  type: LeadType;
  submitLabel: string;
  className?: string;
}

interface FormState {
  name: string;
  email: string;
  company: string;
  phone: string;
  message: string;
  plan: string;
  persona: string;
  seats: string;
  preferredDate: string;
}

function requiredFieldsFor(type: LeadType): Array<keyof FormState> {
  if (type === 'waitlist') return ['name', 'email', 'message'];
  if (type === 'contact') return ['name', 'email', 'message'];
  if (type === 'book') return ['name', 'email', 'company', 'preferredDate'];
  return ['name', 'email', 'company'];
}

export function LeadForm({ type, submitLabel, className = '' }: LeadFormProps) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const [form, setForm] = useState<FormState>({
    name: '',
    email: '',
    company: '',
    phone: '',
    message: '',
    plan: params.get('plan') ?? '',
    persona: params.get('persona') ?? '',
    seats: '',
    preferredDate: '',
  });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const requiredFields = useMemo(() => requiredFieldsFor(type), [type]);

  const showCompany = type === 'demo' || type === 'book' || type === 'contact';
  const showMessage = type === 'contact' || type === 'waitlist';
  const showPlan = type === 'book' || type === 'demo';
  const showPreferredDate = type === 'book';
  const showSeats = type === 'demo' || type === 'book';

  function validateClient(): boolean {
    const nextErrors: Record<string, string> = {};
    for (const field of requiredFields) {
      const value = form[field];
      if (!value || value.trim().length === 0) {
        nextErrors[field] = 'Required';
      }
    }
    if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
      nextErrors.email = 'Invalid email';
    }
    setFieldErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError('');
    if (!validateClient()) return;

    const sourcePath = `${pathname}${params.toString() ? `?${params.toString()}` : ''}`;
    trackFormSubmitStart(type, sourcePath);
    setIsSubmitting(true);

    try {
      const response = await fetch('/api/leads', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          type,
          ...form,
          sourcePath,
          utm: getAttributionFromCookie(),
          sessionId: getSessionIdFromCookie(),
        }),
      });

      const payload = (await response.json().catch(() => null)) as
        | { ok?: boolean; message?: string; fieldErrors?: Record<string, string> }
        | null;

      if (!response.ok || !payload?.ok) {
        setFieldErrors(payload?.fieldErrors ?? {});
        const reason = payload?.message ?? 'Submission failed';
        setSubmitError(reason);
        trackFormSubmitError(type, sourcePath, reason);
        return;
      }

      await trackFormSubmitSuccess(type, sourcePath);
      router.push(`/thank-you/${type}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unexpected error';
      setSubmitError(message);
      trackFormSubmitError(type, sourcePath, message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className={`space-y-4 ${className}`} noValidate>
      <div>
        <label className="block font-telemetry text-steel mb-1" htmlFor={`${type}-name`}>
          Name
        </label>
        <input
          id={`${type}-name`}
          value={form.name}
          onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
          className="w-full bg-concrete border border-steel/30 px-3 py-2 text-chalk"
        />
        {fieldErrors.name && <p className="text-safety-red text-xs mt-1">{fieldErrors.name}</p>}
      </div>

      <div>
        <label className="block font-telemetry text-steel mb-1" htmlFor={`${type}-email`}>
          Email
        </label>
        <input
          id={`${type}-email`}
          type="email"
          value={form.email}
          onChange={(event) => setForm((prev) => ({ ...prev, email: event.target.value }))}
          className="w-full bg-concrete border border-steel/30 px-3 py-2 text-chalk"
        />
        {fieldErrors.email && <p className="text-safety-red text-xs mt-1">{fieldErrors.email}</p>}
      </div>

      {showCompany && (
        <div>
          <label className="block font-telemetry text-steel mb-1" htmlFor={`${type}-company`}>
            Company
          </label>
          <input
            id={`${type}-company`}
            value={form.company}
            onChange={(event) => setForm((prev) => ({ ...prev, company: event.target.value }))}
            className="w-full bg-concrete border border-steel/30 px-3 py-2 text-chalk"
          />
          {fieldErrors.company && (
            <p className="text-safety-red text-xs mt-1">{fieldErrors.company}</p>
          )}
        </div>
      )}

      <div>
        <label className="block font-telemetry text-steel mb-1" htmlFor={`${type}-phone`}>
          Phone (optional)
        </label>
        <input
          id={`${type}-phone`}
          value={form.phone}
          onChange={(event) => setForm((prev) => ({ ...prev, phone: event.target.value }))}
          className="w-full bg-concrete border border-steel/30 px-3 py-2 text-chalk"
        />
      </div>

      {showPlan && (
        <div>
          <label className="block font-telemetry text-steel mb-1" htmlFor={`${type}-plan`}>
            Interested plan
          </label>
          <input
            id={`${type}-plan`}
            value={form.plan}
            onChange={(event) => setForm((prev) => ({ ...prev, plan: event.target.value }))}
            className="w-full bg-concrete border border-steel/30 px-3 py-2 text-chalk"
          />
        </div>
      )}

      {showSeats && (
        <div>
          <label className="block font-telemetry text-steel mb-1" htmlFor={`${type}-seats`}>
            Team size (optional)
          </label>
          <input
            id={`${type}-seats`}
            value={form.seats}
            onChange={(event) => setForm((prev) => ({ ...prev, seats: event.target.value }))}
            className="w-full bg-concrete border border-steel/30 px-3 py-2 text-chalk"
          />
        </div>
      )}

      <div>
        <label className="block font-telemetry text-steel mb-1" htmlFor={`${type}-persona`}>
          Persona (optional)
        </label>
        <input
          id={`${type}-persona`}
          value={form.persona}
          onChange={(event) => setForm((prev) => ({ ...prev, persona: event.target.value }))}
          className="w-full bg-concrete border border-steel/30 px-3 py-2 text-chalk"
        />
      </div>

      {showPreferredDate && (
        <div>
          <label className="block font-telemetry text-steel mb-1" htmlFor={`${type}-date`}>
            Preferred booking date
          </label>
          <input
            id={`${type}-date`}
            type="date"
            value={form.preferredDate}
            onChange={(event) =>
              setForm((prev) => ({ ...prev, preferredDate: event.target.value }))
            }
            className="w-full bg-concrete border border-steel/30 px-3 py-2 text-chalk"
          />
          {fieldErrors.preferredDate && (
            <p className="text-safety-red text-xs mt-1">{fieldErrors.preferredDate}</p>
          )}
        </div>
      )}

      {showMessage && (
        <div>
          <label className="block font-telemetry text-steel mb-1" htmlFor={`${type}-message`}>
            {type === 'waitlist' ? 'What are you waiting for?' : 'How can we help?'}
          </label>
          <textarea
            id={`${type}-message`}
            value={form.message}
            onChange={(event) => setForm((prev) => ({ ...prev, message: event.target.value }))}
            rows={5}
            className="w-full bg-concrete border border-steel/30 px-3 py-2 text-chalk"
          />
          {fieldErrors.message && (
            <p className="text-safety-red text-xs mt-1">{fieldErrors.message}</p>
          )}
        </div>
      )}

      {submitError && (
        <div className="border border-safety-red/50 bg-safety-red/10 px-3 py-2 text-safety-red text-sm">
          {submitError}
        </div>
      )}

      <PitButton type="submit" className="w-full sm:w-auto">
        {isSubmitting ? 'Submitting...' : submitLabel}
      </PitButton>
    </form>
  );
}
