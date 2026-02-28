'use client';

import { useState, useCallback, useId } from 'react';
import type { FaqItem } from '@/data/faq';

interface FaqAccordionProps {
  items: FaqItem[];
  onExpand?: (index: number) => void;
  className?: string;
}

export function FaqAccordion({ items, onExpand, className = '' }: FaqAccordionProps) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const baseId = useId();

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
      if (e.key === 'Home') {
        e.preventDefault();
        (document.querySelector(`[data-faq="0"]`) as HTMLElement)?.focus();
      }
      if (e.key === 'End') {
        e.preventDefault();
        (document.querySelector(`[data-faq="${items.length - 1}"]`) as HTMLElement)?.focus();
      }
    },
    [items.length],
  );

  return (
    <div className={`divide-y divide-steel/20 ${className}`}>
      {items.map((item, i) => {
        const panelId = `${baseId}-panel-${i}`;
        const buttonId = `${baseId}-btn-${i}`;
        const isOpen = openIndex === i;

        return (
          <div key={i}>
            <button
              id={buttonId}
              data-faq={i}
              className="w-full flex items-center justify-between py-4 px-2 text-left font-body text-chalk hover:text-[var(--accent)] transition-colors duration-[420ms]"
              onClick={() => toggle(i)}
              onKeyDown={(e) => handleKeyDown(e, i)}
              aria-expanded={isOpen}
              aria-controls={panelId}
            >
              <span>{item.question}</span>
              <span
                className="text-steel text-xl transition-transform duration-[420ms] ml-4 shrink-0"
                style={{ transform: isOpen ? 'rotate(45deg)' : 'rotate(0deg)' }}
                aria-hidden="true"
              >
                +
              </span>
            </button>

            <div
              id={panelId}
              role="region"
              aria-labelledby={buttonId}
              className="grid transition-all duration-[420ms] ease-[cubic-bezier(0.16,1,0.3,1)]"
              style={{
                gridTemplateRows: isOpen ? '1fr' : '0fr',
              }}
            >
              <div className="overflow-hidden">
                <p className="font-body text-steel text-sm px-2 pb-4">
                  {item.answer}
                </p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
