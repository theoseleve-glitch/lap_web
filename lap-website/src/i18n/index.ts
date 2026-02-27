'use client';

import { createContext, useContext } from 'react';
import en from './en.json';
import fr from './fr.json';

export type Locale = 'en' | 'fr';

const dictionaries: Record<Locale, Record<string, string>> = { en, fr };

interface TranslationContextValue {
  locale: Locale;
  t: (key: string, fallback?: string) => string;
}

export const I18nContext = createContext<TranslationContextValue>({
  locale: 'en',
  t: (key: string, fallback?: string) => (en as Record<string, string>)[key] ?? fallback ?? key,
});

export function useTranslation() {
  return useContext(I18nContext);
}

export function getTranslator(locale: Locale) {
  const dict = dictionaries[locale] ?? dictionaries.en;
  const enDict = dictionaries.en;
  return (key: string, fallback?: string): string =>
    dict[key] ?? enDict[key] ?? fallback ?? key;
}

export { dictionaries };
