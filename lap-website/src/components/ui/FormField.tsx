/**
 * Standardized form field with error display.
 *
 * - Error color token + border token + helper text placement
 * - ARIA role=alert for error messages
 * - Consistent spacing and typography tokens
 * - 44px minimum touch target
 *
 * Note: This is an enhanced version that re-exports from the existing
 * app/FormField.tsx with standardized error patterns.
 */

import { type InputHTMLAttributes, type ReactNode, useId } from 'react';

interface FormFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> {
  label: string;
  error?: string;
  hint?: string;
  children?: ReactNode;
}

export function FormField({ label, error, hint, children, className = '', ...inputProps }: FormFieldProps) {
  const id = useId();
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;

  return (
    <div className="mb-4">
      <label htmlFor={id} className="block font-telemetry text-xs tracking-widest uppercase text-steel mb-2">
        {label}
      </label>
      {children ?? (
        <input
          id={id}
          aria-invalid={!!error}
          aria-describedby={error ? errorId : hint ? hintId : undefined}
          className={`
            w-full min-h-[44px] px-3 py-2.5
            bg-concrete border
            ${error ? 'border-safety-red' : 'border-steel/20'}
            rounded-2 text-chalk text-sm
            placeholder:text-steel/50
            transition-colors
            focus:outline-none focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)]
            ${className}
          `}
          {...inputProps}
        />
      )}
      {error && (
        <p id={errorId} role="alert" className="mt-1.5 text-safety-red text-xs">
          {error}
        </p>
      )}
      {hint && !error && (
        <p id={hintId} className="mt-1.5 text-steel text-xs">
          {hint}
        </p>
      )}
    </div>
  );
}
