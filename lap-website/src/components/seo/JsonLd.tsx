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

interface HowToStep {
  name: string;
  text: string;
}

interface HowToData {
  name: string;
  description: string;
  steps: HowToStep[];
}

interface ReviewData {
  author: string;
  reviewBody: string;
}

interface JsonLdProps {
  pathname: string;
  faqItems?: FaqItem[];
  article?: ArticleData;
  softwareApp?: boolean;
  howTo?: HowToData;
  reviews?: ReviewData[];
  organization?: boolean;
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

export function JsonLd({ pathname, faqItems, article, softwareApp, howTo, reviews, organization }: JsonLdProps) {
  const entry = routeMap[pathname];
  if (!entry && !article) return null;

  const siteUrl = getSiteUrl();
  const jsonLdType = entry?.jsonLdType ?? 'WebPage';
  const graph: Record<string, unknown>[] = [];

  if (organization) {
    graph.push({
      '@type': 'Organization',
      name: 'LAP Coach',
      url: siteUrl,
      description: 'Motorsport telemetry analysis platform used by 850+ drivers across 140+ tracks worldwide.',
      foundingDate: '2025',
      numberOfEmployees: { '@type': 'QuantitativeValue', value: 5 },
      slogan: 'Turn raw data into faster laps',
    });
  }

  if (howTo) {
    graph.push({
      '@type': 'HowTo',
      name: howTo.name,
      description: howTo.description,
      step: howTo.steps.map((s, i) => ({
        '@type': 'HowToStep',
        position: i + 1,
        name: s.name,
        text: s.text,
      })),
    });
  }

  if (reviews?.length) {
    for (const r of reviews) {
      graph.push({
        '@type': 'Review',
        author: { '@type': 'Person', name: r.author },
        reviewBody: r.reviewBody,
        itemReviewed: { '@type': 'SoftwareApplication', name: 'LAP Coach' },
      });
    }
  }

  if (softwareApp) {
    graph.push({
      '@type': 'SoftwareApplication',
      name: 'LAP Coach',
      applicationCategory: 'SportsApplication',
      operatingSystem: 'Web',
      url: siteUrl,
      description: 'Motorsport telemetry analysis platform for kart and car racing. Upload CSV data and get coaching insights, corner analysis, and performance scoring.',
      offers: {
        '@type': 'AggregateOffer',
        lowPrice: '0',
        highPrice: '14',
        priceCurrency: 'EUR',
        offerCount: 3,
      },
      aggregateRating: {
        '@type': 'AggregateRating',
        ratingValue: '4.7',
        ratingCount: '48',
      },
    });
  }

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
