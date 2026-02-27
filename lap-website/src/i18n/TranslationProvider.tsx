'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { I18nContext, getTranslator, type Locale } from './index';

function getCookie(name: string): string | undefined {
  if (typeof document === 'undefined') return undefined;
  const raw = document.cookie
    .split(';')
    .map((p) => p.trim())
    .find((p) => p.startsWith(`${name}=`));
  return raw ? raw.split('=').slice(1).join('=') : undefined;
}

export function TranslationProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>('en');

  useEffect(() => {
    const cookie = getCookie('lap_locale');
    if (cookie === 'fr' || cookie === 'en') setLocale(cookie);
  }, []);

  const t = getTranslator(locale);

  return (
    <I18nContext.Provider value={{ locale, t }}>
      {children}
    </I18nContext.Provider>
  );
}
