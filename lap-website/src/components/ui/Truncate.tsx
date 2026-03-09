'use client';

import { useState } from 'react';

interface TruncateProps {
  text: string;
  maxLength?: number;
  className?: string;
}

export function Truncate({ text, maxLength = 120, className = '' }: TruncateProps) {
  const [expanded, setExpanded] = useState(false);

  if (text.length <= maxLength) {
    return <span className={className}>{text}</span>;
  }

  return (
    <span className={className}>
      {expanded ? text : `${text.slice(0, maxLength).trimEnd()}...`}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="ml-1 text-acid-green text-xs hover:underline"
      >
        {expanded ? 'less' : 'more'}
      </button>
    </span>
  );
}
