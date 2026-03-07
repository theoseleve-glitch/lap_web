import { routeMap, buildBreadcrumbs } from '@/data/route-map';
import { getSiteUrl } from '@/lib/site-url';

interface FaqItem {
  question: string;
  answer: string;
}

interface ArticleData {
  title: string;
  datePublished: string;
  summary: string;
}

interface JsonLdProps {
  pathname: string;
  faqItems?: FaqItem[];
  article?: ArticleData;
}

function buildBreadcrumbSchema(pathname: string, siteUrl: string) {
  const crumbs = buildBreadcrumbs(pathname);
  const entry = routeMap[pathname];
  if (!entry || crumbs.length === 0) return null;

  return {
    '@type': 'BreadcrumbList',
    itemListElement: [
      ...crumbs.map((c, i) => ({
        '@type': 'ListItem',
        position: i + 1,
        name: c.label,
        item: `${siteUrl}${c.href}`,
      })),
      {
        '@type': 'ListItem',
        position: crumbs.length + 1,
        name: entry.title,
        item: `${siteUrl}${pathname}`,
      },
    ],
  };
}

export function JsonLd({ pathname, faqItems, article }: JsonLdProps) {
  const entry = routeMap[pathname];
  if (!entry && !article) return null;

  const siteUrl = getSiteUrl();
  const jsonLdType = entry?.jsonLdType ?? 'WebPage';
  const graph: Record<string, unknown>[] = [];

  if (article) {
    graph.push({
      '@type': 'Article',
      headline: article.title,
      datePublished: article.datePublished,
      description: article.summary,
      publisher: { '@type': 'Organization', name: 'Lap Coach' },
    });
  } else if (jsonLdType === 'FAQPage' && faqItems?.length) {
    graph.push({
      '@type': 'FAQPage',
      mainEntity: faqItems.map((item) => ({
        '@type': 'Question',
        name: item.question,
        acceptedAnswer: { '@type': 'Answer', text: item.answer },
      })),
    });
  } else {
    graph.push({
      '@type': 'WebPage',
      name: entry?.title,
      url: `${siteUrl}${pathname}`,
    });
  }

  const breadcrumbSchema = buildBreadcrumbSchema(pathname, siteUrl);
  if (breadcrumbSchema) graph.push(breadcrumbSchema);

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{
        __html: JSON.stringify({ '@context': 'https://schema.org', '@graph': graph }),
      }}
    />
  );
}
