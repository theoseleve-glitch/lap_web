'use client';

import { useState, useCallback } from 'react';
import type { FaqItem } from '@/data/faq';

interface FaqAccordionProps {
  items: FaqItem[];
  onExpand?: (index: number) => void;
  className?: string;
}

export function FaqAccordion({ items, onExpand, className = '' }: FaqAccordionProps) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  const toggle = useCallback(
    (index: number) => {
      const next = openIndex === index ? null : index;
      setOpenIndex(next);
      if (next !== null) onExpand?.(next);
    },
    [openIndex, onExpand],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent, index: number) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        const next = Math.min(index + 1, items.length - 1);
        (document.querySelector(`[data-faq="${next}"]`) as HTMLElement)?.focus();
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        const prev = Math.max(index - 1, 0);
        (document.querySelector(`[data-faq="${prev}"]`) as HTMLElement)?.focus();
      }
    },
    [items.length],
  );

  return (
    <div className={`divide-y divide-steel/20 ${className}`}>
      {items.map((item, i) => (
        <div key={i}>
          <button
            data-faq={i}
            className="w-full flex items-center justify-between py-4 px-2 text-left font-body text-chalk hover:text-[var(--accent)] transition-colors duration-[420ms]"
            onClick={() => toggle(i)}
            onKeyDown={(e) => handleKeyDown(e, i)}
            aria-expanded={openIndex === i}
          >
            <span>{item.question}</span>
            <span
              className="text-steel text-xl transition-transform duration-[420ms] ml-4 shrink-0"
              style={{ transform: openIndex === i ? 'rotate(45deg)' : 'rotate(0deg)' }}
            >
              +
            </span>
          </button>

          <div
            className="grid transition-all duration-[420ms] ease-[cubic-bezier(0.16,1,0.3,1)]"
            style={{
              gridTemplateRows: openIndex === i ? '1fr' : '0fr',
            }}
          >
            <div className="overflow-hidden">
              <p className="font-body text-steel text-sm px-2 pb-4">
                {item.answer}
              </p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
