'use client';

import { useState, useRef, useEffect } from 'react';
import { MonumentText } from '@/components/ui/MonumentText';
import { PipelineBlocks } from '@/components/mechanisms/PipelineBlocks';
import { ReversibleCard } from '@/components/ui/ReversibleCard';
import { s2Pipeline } from '@/data/copy';
import { trackS2PipelineComplete } from '@/lib/analytics';

export function S2Pipeline() {
  const [progress, setProgress] = useState(0);
  const sectionRef = useRef<HTMLElement>(null);
  const trackedComplete = useRef(false);

  useEffect(() => {
    const section = sectionRef.current;
    if (!section) return;

    const handleScroll = () => {
      const rect = section.getBoundingClientRect();
      const viewportHeight = window.innerHeight;
      const sectionTop = -rect.top;
      const sectionHeight = rect.height - viewportHeight;

      if (sectionHeight > 0) {
        const p = Math.max(0, Math.min(1, sectionTop / sectionHeight));
        setProgress(p);

        if (p >= 1 && !trackedComplete.current) {
          trackedComplete.current = true;
          trackS2PipelineComplete();
        }
      }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    handleScroll();
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  return (
    <section
      ref={sectionRef}
      id="s2-pipeline"
      data-accent="yellow"
      className="relative py-16 md:py-24"
      style={{ minHeight: '200vh' }}
      aria-label="Sector 2 — How it works"
    >
      <div className="sticky top-0 min-h-screen flex flex-col justify-center">
        <div className="grid-lap">
          <div className="col-span-full text-center mb-12">
            <MonumentText size="h2" as="h2" reveal>
              {s2Pipeline.monument}
            </MonumentText>
          </div>

          <div className="col-span-full mb-8">
            <PipelineBlocks progress={progress} />
          </div>

          <div className="col-span-full text-center">
            <ReversibleCard
              title="Fast Pipeline Outcome"
              description={s2Pipeline.body}
              className="max-w-xl mx-auto"
            />
          </div>
        </div>
      </div>
    </section>
  );
}
