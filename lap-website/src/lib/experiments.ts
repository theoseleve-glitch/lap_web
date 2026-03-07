export type ExperimentKey = 'hero' | 'pricing' | 'cta';

const variants: Record<ExperimentKey, string[]> = {
  hero: ['control', 'performance_focus'],
  pricing: ['standard_table', 'comparison_first'],
  cta: ['demo_first', 'book_first'],
};

export function getExperimentCookieName(key: ExperimentKey): string {
  return `lap_exp_${key}`;
}

export function getVariantForKey(key: ExperimentKey, fallback = 'control'): string {
  if (typeof document === 'undefined') return fallback;
  const cookie = document.cookie
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${getExperimentCookieName(key)}=`));
  if (!cookie) return fallback;
  return cookie.split('=').slice(1).join('=') || fallback;
}

export function pickRandomVariant(key: ExperimentKey): string {
  const options = variants[key];
  return options[Math.floor(Math.random() * options.length)] ?? options[0] ?? 'control';
}

export function getExperimentOptions(key: ExperimentKey): string[] {
  return variants[key];
}
