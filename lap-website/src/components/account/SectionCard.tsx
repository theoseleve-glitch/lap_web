'use client';

import { type ReactNode } from 'react';

interface SectionCardProps {
  title: string;
  description?: string;
  children: ReactNode;
  actions?: ReactNode;
}

export function SectionCard({ title, description, children, actions }: SectionCardProps) {
  return (
    <div className="bg-concrete border border-steel/10 rounded-lg">
      <div className="flex items-start justify-between px-5 py-4 border-b border-steel/10">
        <div>
          <h3 className="font-monument text-base text-chalk tracking-tight">{title}</h3>
          {description && (
            <p className="text-sm text-steel mt-0.5 font-body">{description}</p>
          )}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      <div className="px-5 py-4">{children}</div>
    </div>
  );
}
