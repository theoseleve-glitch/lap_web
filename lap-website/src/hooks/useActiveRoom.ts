'use client';

import { useState, useEffect } from 'react';
import { rooms } from '@/lib/tokens';

export function useActiveRoom(): string {
  const [active, setActive] = useState<string>(rooms[0].id);

  useEffect(() => {
    const observers: IntersectionObserver[] = [];

    rooms.forEach((room) => {
      const el = document.getElementById(room.id);
      if (!el) return;

      const observer = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) setActive(room.id);
        },
        { threshold: 0.5 },
      );
      observer.observe(el);
      observers.push(observer);
    });

    return () => observers.forEach((o) => o.disconnect());
  }, []);

  return active;
}
