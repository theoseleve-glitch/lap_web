'use client';

import { useEffect, createContext, useContext, useState, type ReactNode } from 'react';
import { registerGsap } from '@/lib/gsap-config';

const GsapContext = createContext(false);

export function useGsapReady() {
  return useContext(GsapContext);
}

export function GsapProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    registerGsap();
    setReady(true);
  }, []);

  return <GsapContext.Provider value={ready}>{children}</GsapContext.Provider>;
}
