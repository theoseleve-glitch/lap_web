'use client';

import { useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { LeadType } from '@/lib/lead-types';
import { b2cPlans, b2bCard } from '@/data/pricing';
import {
  getAttributionFromCookie,
  getSessionIdFromCookie,
  trackFormFieldBlur,
  trackFormSubmitError,
  trackFormSubmitStart,
  trackFormSubmitSuccess,
  trackFormSubmitTiming,
} from '@/lib/analytics';
import { PitButton } from '@/components/ui/PitButton';
import { useTranslation } from '@/i18n';

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
  website: string;
  challengeToken: string;
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
  const { t } = useTranslation();

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
    website: '',
    challengeToken: '',
  });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const startedAtRef = useRef(Date.now());

  const requiredFields = useMemo(() => requiredFieldsFor(type), [type]);
  const planOptions = useMemo(() => {
    const options = b2cPlans.map((plan) => ({ label: plan.name, value: plan.name }));
    options.push({ label: b2bCard.name, value: b2bCard.name });
    return options;
  }, []);

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
        nextErrors[field] = t('form.required');
      }
    }
    if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
      nextErrors.email = t('form.invalidEmail');
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
          startedAt: startedAtRef.current,
          sourcePath,
          utm: getAttributionFromCookie(),
          sessionId: getSessionIdFromCookie(),
          challengeToken: form.challengeToken,
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

      trackFormSubmitTiming(type, Date.now() - startedAtRef.current);
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
          {t('form.name')}
        </label>
        <input
          id={`${type}-name`}
          value={form.name}
          onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
          onBlur={() => trackFormFieldBlur(type, 'name')}
          className="w-full bg-concrete border border-steel/30 px-3 py-2 text-chalk"
        />
        {fieldErrors.name && <p className="text-safety-red text-xs mt-1">{fieldErrors.name}</p>}
      </div>

      <div>
        <label className="block font-telemetry text-steel mb-1" htmlFor={`${type}-email`}>
          {t('form.email')}
        </label>
        <input
          id={`${type}-email`}
          type="email"
          value={form.email}
          onChange={(event) => setForm((prev) => ({ ...prev, email: event.target.value }))}
          onBlur={() => trackFormFieldBlur(type, 'email')}
          className="w-full bg-concrete border border-steel/30 px-3 py-2 text-chalk"
        />
        {fieldErrors.email && <p className="text-safety-red text-xs mt-1">{fieldErrors.email}</p>}
      </div>

      {showCompany && (
        <div>
          <label className="block font-telemetry text-steel mb-1" htmlFor={`${type}-company`}>
            {t('form.company')}
          </label>
          <input
            id={`${type}-company`}
            value={form.company}
            onChange={(event) => setForm((prev) => ({ ...prev, company: event.target.value }))}
            onBlur={() => trackFormFieldBlur(type, 'company')}
            className="w-full bg-concrete border border-steel/30 px-3 py-2 text-chalk"
          />
          {fieldErrors.company && (
            <p className="text-safety-red text-xs mt-1">{fieldErrors.company}</p>
          )}
        </div>
      )}

      <div>
        <label className="block font-telemetry text-steel mb-1" htmlFor={`${type}-phone`}>
          {t('form.phone')}
        </label>
        <input
          id={`${type}-phone`}
          value={form.phone}
          onChange={(event) => setForm((prev) => ({ ...prev, phone: event.target.value }))}
          onBlur={() => trackFormFieldBlur(type, 'phone')}
          className="w-full bg-concrete border border-steel/30 px-3 py-2 text-chalk"
        />
      </div>

      {showPlan && (
        <div>
          <label className="block font-telemetry text-steel mb-1" htmlFor={`${type}-plan`}>
            {t('form.plan')}
          </label>
          <select
            id={`${type}-plan`}
            value={form.plan}
            onChange={(event) => setForm((prev) => ({ ...prev, plan: event.target.value }))}
            onBlur={() => trackFormFieldBlur(type, 'plan')}
            className="w-full bg-concrete border border-steel/30 px-3 py-2 text-chalk"
          >
            <option value="">{t('form.planPlaceholder')}</option>
            {planOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      )}

      {showSeats && (
        <div>
          <label className="block font-telemetry text-steel mb-1" htmlFor={`${type}-seats`}>
            {t('form.teamSize')}
          </label>
          <input
            id={`${type}-seats`}
            value={form.seats}
            onChange={(event) => setForm((prev) => ({ ...prev, seats: event.target.value }))}
            onBlur={() => trackFormFieldBlur(type, 'seats')}
            className="w-full bg-concrete border border-steel/30 px-3 py-2 text-chalk"
          />
        </div>
      )}

      <div>
        <label className="block font-telemetry text-steel mb-1" htmlFor={`${type}-persona`}>
          {t('form.persona')}
        </label>
        <select
          id={`${type}-persona`}
          value={form.persona}
          onChange={(event) => setForm((prev) => ({ ...prev, persona: event.target.value }))}
          onBlur={() => trackFormFieldBlur(type, 'persona')}
          className="w-full bg-concrete border border-steel/30 px-3 py-2 text-chalk"
        >
          <option value="">{t('form.personaPlaceholder')}</option>
          <option value="drivers">{t('form.personaDrivers')}</option>
          <option value="circuits">{t('form.personaCircuits')}</option>
          <option value="teams">{t('form.personaTeams')}</option>
          <option value="endurance">{t('form.personaEndurance')}</option>
        </select>
      </div>

      {showPreferredDate && (
        <div>
          <label className="block font-telemetry text-steel mb-1" htmlFor={`${type}-date`}>
            {t('form.preferredDate')}
          </label>
          <input
            id={`${type}-date`}
            type="date"
            value={form.preferredDate}
            onChange={(event) =>
              setForm((prev) => ({ ...prev, preferredDate: event.target.value }))
            }
            onBlur={() => trackFormFieldBlur(type, 'preferredDate')}
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
            {type === 'waitlist' ? t('form.messageWaitlist') : t('form.messageContact')}
          </label>
          <textarea
            id={`${type}-message`}
            value={form.message}
            onChange={(event) => setForm((prev) => ({ ...prev, message: event.target.value }))}
            onBlur={() => trackFormFieldBlur(type, 'message')}
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


      <input
        type="hidden"
        value={form.challengeToken}
        onChange={(event) =>
          setForm((prev) => ({ ...prev, challengeToken: event.target.value }))
        }
      />

      <input
        aria-hidden="true"
        tabIndex={-1}
        autoComplete="off"
        type="text"
        value={form.website}
        onChange={(event) => setForm((prev) => ({ ...prev, website: event.target.value }))}
        className="hidden"
      />

      <PitButton type="submit" className="w-full sm:w-auto">
        {isSubmitting ? t('form.submitting') : submitLabel}
      </PitButton>
    </form>
  );
}
