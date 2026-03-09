import { forwardRef, type InputHTMLAttributes } from 'react';

type InputVariant = 'default' | 'ghost' | 'filled';
type InputSize = 'sm' | 'md' | 'lg';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  variant?: InputVariant;
  inputSize?: InputSize;
  error?: boolean;
}

const VARIANT_CLASSES: Record<InputVariant, string> = {
  default: 'bg-asphalt border border-steel/30 focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50',
  ghost: 'bg-transparent border border-transparent focus:border-steel/30 focus:ring-1 focus:ring-steel/20',
  filled: 'bg-concrete border border-steel/10 focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50',
};

const SIZE_CLASSES: Record<InputSize, string> = {
  sm: 'px-2 py-1.5 text-xs',
  md: 'px-3 py-2.5 text-sm',
  lg: 'px-4 py-3 text-base',
};

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ variant = 'default', inputSize = 'md', error, className = '', ...props }, ref) => {
    return (
      <input
        ref={ref}
        className={`w-full rounded text-chalk font-body placeholder:text-steel/50 focus:outline-none transition-colors ${VARIANT_CLASSES[variant]} ${SIZE_CLASSES[inputSize]} ${error ? 'border-safety-red' : ''} ${className}`}
        {...props}
      />
    );
  },
);
Input.displayName = 'Input';
