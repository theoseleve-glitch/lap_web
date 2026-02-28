'use client';

import { type InputHTMLAttributes, type ReactNode, forwardRef } from 'react';

interface FormFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: string;
  children?: ReactNode;
}

export const FormField = forwardRef<HTMLInputElement, FormFieldProps>(
  function FormField({ label, error, hint, children, className, ...inputProps }, ref) {
    const inputId = inputProps.id ?? `field-${label.toLowerCase().replace(/\s+/g, '-')}`;

    return (
      <div className="space-y-1.5">
        <label
          htmlFor={inputId}
          className="block text-sm font-telemetry text-steel"
        >
          {label}
        </label>
        {children ?? (
          <input
            ref={ref}
            id={inputId}
            className={`w-full bg-asphalt border rounded-md px-3 py-2 text-chalk font-body text-sm focus:outline-none transition-colors ${
              error
                ? 'border-safety-red/50 focus:border-safety-red'
                : 'border-steel/30 focus:border-acid-green/40'
            } ${className ?? ''}`}
            {...inputProps}
          />
        )}
        {error && (
          <p className="text-xs text-safety-red font-body">{error}</p>
        )}
        {hint && !error && (
          <p className="text-xs text-steel font-body">{hint}</p>
        )}
      </div>
    );
  },
);
