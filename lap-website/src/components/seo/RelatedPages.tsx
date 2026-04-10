import Link from 'next/link';
import { routeMap } from '@/data/route-map';

interface Props {
  currentPath: string;
  maxLinks?: number;
}

export function RelatedPages({ currentPath, maxLinks = 4 }: Props) {
  const entry = routeMap[currentPath];
  if (!entry) return null;

  const siblings = Object.values(routeMap)
    .filter((r) =>
      r.path !== currentPath &&
      !r.noIndex &&
      r.metaDescription &&
      (r.parent === entry.parent || r.path === entry.parent),
    )
    .slice(0, maxLinks);

  if (siblings.length === 0) return null;

  return (
    <nav aria-label="Related pages" className="mt-16 border-t border-steel/20 pt-8">
      <h2 className="font-monument text-xs uppercase tracking-wider text-steel mb-4">
        Related Pages
      </h2>
      <ul className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {siblings.map((r) => (
          <li key={r.path}>
            <Link
              href={r.path}
              className="block p-3 rounded border border-steel/10 hover:border-gold/30 transition-colors"
            >
              <span className="font-monument text-sm text-chalk">{r.title}</span>
              {r.metaDescription && (
                <p className="text-xs text-steel mt-1 line-clamp-2 font-body">
                  {r.metaDescription.slice(0, 100)}
                </p>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
