import Link from 'next/link';

interface ComingSoonProps {
  title: string;
  description?: string;
  backHref: string;
  backLabel?: string;
}

export function ComingSoon({ title, description, backHref, backLabel = 'Back to Analytics Hub' }: ComingSoonProps) {
  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-center max-w-md">
        <div className="inline-block px-3 py-1 bg-amber-500/10 text-amber-400 text-xs font-medium rounded-full mb-4">
          Coming Soon
        </div>
        <h1 className="text-2xl font-bold text-zinc-100 mb-2">{title}</h1>
        {description && <p className="text-zinc-400 mb-6">{description}</p>}
        <Link href={backHref} className="text-sm text-[#3ddc84] hover:underline">
          {backLabel}
        </Link>
      </div>
    </div>
  );
}
