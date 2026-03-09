import { forwardRef, useId, type InputHTMLAttributes } from 'react';

interface FormFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  valid?: boolean;
}

export const FormField = forwardRef<HTMLInputElement, FormFieldProps>(
  ({ label, error, valid, className = '', id: externalId, ...props }, ref) => {
    const generatedId = useId();
    const inputId = externalId || generatedId;

    return (
      <div className="mb-4">
        <label
          htmlFor={inputId}
          className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5"
        >
          {label}
        </label>
        <div className="relative">
          <input
            ref={ref}
            id={inputId}
            className={`w-full bg-asphalt border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
              placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
              transition-colors ${error ? 'border-safety-red' : valid ? 'border-acid-green/50' : ''} ${className}`}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${inputId}-error` : undefined}
            {...props}
          />
          {valid && !error && (
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-acid-green text-sm" aria-hidden="true">&#10003;</span>
          )}
        </div>
        {error && (
          <p id={`${inputId}-error`} className="mt-1 text-safety-red font-telemetry text-xs" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  },
);
FormField.displayName = 'FormField';
