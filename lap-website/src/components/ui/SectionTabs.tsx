'use client';

import { useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import { routeMap } from '@/data/route-map';

export function SectionTabs() {
  const pathname = usePathname();
  const entry = routeMap[pathname];
  const anchors = entry?.sectionAnchors;
  const [activeId, setActiveId] = useState<string | null>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    if (!anchors?.length) return;
    observerRef.current = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) setActiveId(e.target.id);
        }
      },
      { rootMargin: '-80px 0px -60% 0px', threshold: 0 },
    );
    for (const anchor of anchors) {
      const el = document.getElementById(anchor.id);
      if (el) observerRef.current.observe(el);
    }
    return () => observerRef.current?.disconnect();
  }, [anchors]);

  if (!anchors?.length) return null;

  return (
    <nav aria-label="Page sections" className="sticky top-0 z-[var(--z-nav)] bg-asphalt/95 backdrop-blur border-b border-steel/10" style={{ minHeight: '44px' }}>
      <div className="mx-auto max-w-6xl px-4 flex items-center gap-1 overflow-x-auto h-11">
        {anchors.map((anchor) => (
          <a key={anchor.id} href={`#${anchor.id}`}
            className={`font-telemetry text-[11px] tracking-[0.12em] uppercase px-3 py-2 whitespace-nowrap transition-colors ${
              activeId === anchor.id ? 'text-chalk border-b-2 border-acid-green' : 'text-steel hover:text-chalk'
            }`}>
            {anchor.label}
          </a>
        ))}
      </div>
    </nav>
  );
}
