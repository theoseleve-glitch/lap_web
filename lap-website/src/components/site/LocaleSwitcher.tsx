'use client';

import { useEffect, useState } from 'react';

type Locale = 'en' | 'fr';
type Currency = 'eur' | 'usd';

function getCookie(name: string): string | undefined {
  if (typeof document === 'undefined') return undefined;
  const raw = document.cookie
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${name}=`));
  if (!raw) return undefined;
  return raw.split('=').slice(1).join('=');
}

function setCookie(name: string, value: string) {
  document.cookie = `${name}=${value}; path=/; max-age=${60 * 60 * 24 * 180}; samesite=lax`;
}

export function LocaleSwitcher() {
  const [locale, setLocale] = useState<Locale>('en');
  const [currency, setCurrency] = useState<Currency>('eur');

  useEffect(() => {
    const cookieLocale = getCookie('lap_locale');
    const cookieCurrency = getCookie('lap_currency');
    if (cookieLocale === 'fr' || cookieLocale === 'en') setLocale(cookieLocale);
    if (cookieCurrency === 'usd' || cookieCurrency === 'eur') setCurrency(cookieCurrency);
  }, []);

  return (
    <div className="flex items-center gap-2">
      <label className="sr-only" htmlFor="header-language">Language</label>
      <select
        id="header-language"
        value={locale}
        onChange={(event) => {
          const next = event.target.value as Locale;
          setLocale(next);
          setCookie('lap_locale', next);
          window.location.reload();
        }}
        className="bg-asphalt border border-steel/30 px-2 py-1 text-[11px] text-steel font-telemetry uppercase"
      >
        <option value="en">EN</option>
        <option value="fr">FR</option>
      </select>

      <label className="sr-only" htmlFor="header-currency">Currency</label>
      <select
        id="header-currency"
        value={currency}
        onChange={(event) => {
          const next = event.target.value as Currency;
          setCurrency(next);
          setCookie('lap_currency', next);
          window.location.reload();
        }}
        className="bg-asphalt border border-steel/30 px-2 py-1 text-[11px] text-steel font-telemetry uppercase"
      >
        <option value="eur">EUR</option>
        <option value="usd">USD</option>
      </select>
    </div>
  );
}
