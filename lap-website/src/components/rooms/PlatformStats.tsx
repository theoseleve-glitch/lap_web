'use client';

import { useRef, useEffect, useState } from 'react';

const STATS = [
  { value: '12,000+', label: 'Sessions Analyzed' },
  { value: '850+', label: 'Active Drivers' },
  { value: '140+', label: 'Tracks Worldwide' },
  { value: '98.7%', label: 'Uptime' },
  { value: '3.2M', label: 'Corners Coached' },
];

export function PlatformStats() {
  const ref = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) setVisible(true); },
      { threshold: 0.3 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <section
      ref={ref}
      className="relative py-12 md:py-16 border-y border-steel/10 bg-carbon"
      aria-label="Platform statistics"
    >
      <div className="grid-lap">
        <div className="col-span-full">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-6 md:gap-8">
            {STATS.map((stat, i) => (
              <div
                key={stat.label}
                className={`text-center transition-all duration-700 ${
                  visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'
                }`}
                style={{ transitionDelay: `${i * 100}ms` }}
              >
                <p className="font-monument text-pit-orange text-2xl md:text-3xl lg:text-4xl mb-1">
                  {stat.value}
                </p>
                <p className="font-telemetry text-[10px] tracking-[0.12em] uppercase text-steel">
                  {stat.label}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
