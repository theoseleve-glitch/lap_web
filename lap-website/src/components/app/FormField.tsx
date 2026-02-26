import { forwardRef, type InputHTMLAttributes } from 'react';

interface FormFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
}

export const FormField = forwardRef<HTMLInputElement, FormFieldProps>(
  ({ label, error, className = '', ...props }, ref) => {
    return (
      <div className="mb-4">
        <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">
          {label}
        </label>
        <input
          ref={ref}
          className={`w-full bg-asphalt border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
            placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
            transition-colors ${error ? 'border-safety-red' : ''} ${className}`}
          {...props}
        />
        {error && (
          <p className="mt-1 text-safety-red font-telemetry text-xs">{error}</p>
        )}
      </div>
    );
  },
);
FormField.displayName = 'FormField';
