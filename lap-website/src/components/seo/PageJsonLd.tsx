import { getSiteUrl } from '@/lib/site-url';

type SchemaType = 'FAQPage' | 'Article' | 'WebPage';

interface FAQItem {
  question: string;
  answer: string;
}

interface Props {
  type: SchemaType;
  title: string;
  description: string;
  pathname: string;
  faqItems?: FAQItem[];
  datePublished?: string;
  dateModified?: string;
  author?: string;
}

export function PageJsonLd({
  type, title, description, pathname,
  faqItems, datePublished, dateModified, author,
}: Props) {
  const siteUrl = getSiteUrl();
  const url = `${siteUrl}${pathname}`;
  const schemas: object[] = [];

  if (type === 'FAQPage' && faqItems?.length) {
    schemas.push({
      '@context': 'https://schema.org',
      '@type': 'FAQPage',
      mainEntity: faqItems.map((item) => ({
        '@type': 'Question',
        name: item.question,
        acceptedAnswer: { '@type': 'Answer', text: item.answer },
      })),
    });
  }

  if (type === 'Article') {
    schemas.push({
      '@context': 'https://schema.org',
      '@type': 'Article',
      headline: title,
      description,
      url,
      datePublished: datePublished ?? new Date().toISOString(),
      dateModified: dateModified ?? new Date().toISOString(),
      author: author
        ? { '@type': 'Person', name: author }
        : { '@type': 'Organization', name: 'Lap Coach' },
    });
  }

  if (type === 'WebPage' || schemas.length === 0) {
    schemas.push({
      '@context': 'https://schema.org',
      '@type': 'WebPage',
      name: title,
      description,
      url,
    });
  }

  return (
    <>
      {schemas.map((schema, i) => (
        <script
          key={i}
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(schema) }}
        />
      ))}
    </>
  );
}
