'use client';

import { useEffect, useRef } from 'react';

interface Message {
  msg_id: number;
  author: string;
  message: string;
  category: string;
  created_at: string;
}

interface MessageLogProps {
  messages: Message[];
}

const CATEGORY_COLORS: Record<string, string> = {
  info: 'bg-steel/20 text-steel',
  strategy: 'bg-pit-orange/20 text-pit-orange',
  incident: 'bg-flag-red/20 text-flag-red',
  weather: 'bg-marshal-yellow/20 text-marshal-yellow',
};

export function MessageLog({ messages }: MessageLogProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  if (!messages.length) {
    return (
      <div className="text-center text-steel text-sm py-4">
        No messages yet. Team messages will appear here.
      </div>
    );
  }

  return (
    <div className="max-h-64 overflow-y-auto space-y-2 scrollbar-thin scrollbar-track-transparent scrollbar-thumb-steel/30">
      {messages.map((m) => (
        <div key={m.msg_id} className="flex items-start gap-2 text-sm">
          <span className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-telemetry uppercase ${CATEGORY_COLORS[m.category] || CATEGORY_COLORS.info}`}>
            {m.category}
          </span>
          <div className="min-w-0">
            <span className="font-medium text-chalk">{m.author}</span>
            <span className="text-steel ml-2">{m.message}</span>
          </div>
          <span className="shrink-0 text-[10px] text-steel/60 tabular-nums">
            {new Date(m.created_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
          </span>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
