/**
 * FormSection + PremiumInput + PremiumSelect — consistent form primitives.
 *
 * Every settings/account/upload form uses these instead of raw <input>
 * and <select>. Consistent dark styling, label placement, and focus states.
 *
 * Usage:
 *   <FormSection title="Profile" description="Your identity on the platform">
 *     <PremiumInput label="Name" value={name} onChange={setName} />
 *     <PremiumInput label="Email" value={email} onChange={setEmail} type="email" />
 *     <PremiumSelect label="Role" value={role} onChange={setRole} options={roleOptions} />
 *   </FormSection>
 */

import type { ReactNode, ChangeEvent } from 'react';

// ── FormSection ────────────────────────────────────────────

export interface FormSectionProps {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
}

export function FormSection({
  title,
  description,
  children,
  className = '',
}: FormSectionProps) {
  return (
    <section
      className={`border border-steel/8 rounded-xl p-5 space-y-4 ${className}`}
      style={{ background: 'linear-gradient(180deg, #080808 0%, #040404 100%)' }}
    >
      <div className="pb-3 border-b border-steel/8">
        <h3 className="text-[13px] font-monument text-chalk">{title}</h3>
        {description && (
          <p className="mt-0.5 text-xs font-body text-steel">{description}</p>
        )}
      </div>
      <div className="space-y-4">
        {children}
      </div>
    </section>
  );
}

// ── PremiumInput ───────────────────────────────────────────

export interface PremiumInputProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: 'text' | 'email' | 'password' | 'number' | 'url';
  placeholder?: string;
  disabled?: boolean;
  error?: string;
  hint?: string;
  required?: boolean;
}

export function PremiumInput({
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
  disabled = false,
  error,
  hint,
  required = false,
}: PremiumInputProps) {
  return (
    <div>
      <label className="block text-[11px] font-telemetry text-steel/80 uppercase tracking-[0.12em] mb-1.5">
        {label}
        {required && <span className="text-safety-red ml-0.5">*</span>}
      </label>
      <input
        type={type}
        value={value}
        onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        required={required}
        className={`w-full px-3 py-2 text-sm font-body text-chalk rounded-lg border transition-colors focus:outline-none ${
          error
            ? 'border-safety-red/40 focus:border-safety-red'
            : 'border-steel/12 focus:border-gold/40'
        } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
        style={{ backgroundColor: '#060606' }}
      />
      {error && (
        <p className="mt-1 text-[10px] font-telemetry text-safety-red">{error}</p>
      )}
      {hint && !error && (
        <p className="mt-1 text-[10px] font-telemetry text-steel/50">{hint}</p>
      )}
    </div>
  );
}

// ── PremiumSelect ──────────────────────────────────────────

export interface SelectOption {
  value: string;
  label: string;
}

export interface PremiumSelectProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  disabled?: boolean;
  error?: string;
}

export function PremiumSelect({
  label,
  value,
  onChange,
  options,
  disabled = false,
  error,
}: PremiumSelectProps) {
  return (
    <div>
      <label className="block text-[11px] font-telemetry text-steel/80 uppercase tracking-[0.12em] mb-1.5">
        {label}
      </label>
      <select
        value={value}
        onChange={(e: ChangeEvent<HTMLSelectElement>) => onChange(e.target.value)}
        disabled={disabled}
        className={`w-full px-3 py-2 text-sm font-body text-chalk rounded-lg border transition-colors focus:outline-none appearance-none cursor-pointer pr-8 ${
          error
            ? 'border-safety-red/40 focus:border-safety-red'
            : 'border-steel/12 focus:border-gold/40'
        } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
        style={{
          backgroundColor: '#060606',
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23949494'/%3E%3C/svg%3E\")",
          backgroundRepeat: 'no-repeat',
          backgroundPosition: 'right 10px center',
        }}
      >
        {options.map((opt) => (
          <option
            key={opt.value}
            value={opt.value}
            style={{ backgroundColor: '#141414', color: '#F0EDE5' }}
          >
            {opt.label}
          </option>
        ))}
      </select>
      {error && (
        <p className="mt-1 text-[10px] font-telemetry text-safety-red">{error}</p>
      )}
    </div>
  );
}
