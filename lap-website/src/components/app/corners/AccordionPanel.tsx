'use client';

import { useState, useId } from 'react';

interface AccordionPanelProps {
  title: string;
  subtitle: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}

export function AccordionPanel({ title, subtitle, children, defaultOpen = false }: AccordionPanelProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const id = useId();
  const panelId = `${id}-panel`;
  const buttonId = `${id}-btn`;

  return (
    <div className="border-b border-steel/10">
      <button
        type="button"
        id={buttonId}
        onClick={() => setIsOpen((o) => !o)}
        aria-expanded={isOpen}
        aria-controls={panelId}
        className="w-full flex items-center justify-between py-4 px-1 text-left group"
      >
        <div>
          <span className="font-monument text-sm text-chalk tracking-tight">{title}</span>
          <p className="text-[11px] text-steel font-body mt-0.5">{subtitle}</p>
        </div>
        <span
          className="text-steel text-lg transition-transform duration-200 shrink-0 ml-4"
          style={{ transform: isOpen ? 'rotate(90deg)' : 'rotate(0deg)' }}
          aria-hidden="true"
        >
          ▸
        </span>
      </button>
      <div
        id={panelId}
        role="region"
        aria-labelledby={buttonId}
        className="grid transition-all duration-200 ease-out"
        style={{ gridTemplateRows: isOpen ? '1fr' : '0fr' }}
      >
        <div className="overflow-hidden">
          <div className="pb-4 px-1">{children}</div>
        </div>
      </div>
    </div>
  );
}
