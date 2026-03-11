'use client';

interface MentalImageryPromptProps {
  prompts?: string[] | null;
}

export default function MentalImageryPrompt({ prompts }: MentalImageryPromptProps) {
  if (!prompts || prompts.length === 0) return null;

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-monument text-chalk/80 uppercase tracking-wider">
        Mental Imagery
      </h3>
      <div className="space-y-2">
        {prompts.map((prompt, i) => (
          <div
            key={i}
            className="bg-purple-500/5 border border-purple-500/20 rounded-lg px-4 py-3"
          >
            <p className="text-sm text-chalk/80 font-body italic leading-relaxed">
              {prompt}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
