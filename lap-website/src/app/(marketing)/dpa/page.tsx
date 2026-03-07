import { JsonLd } from '@/components/seo/JsonLd';
import { PageIntro } from '@/components/ui/PageIntro';
import Link from 'next/link';
import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/dpa');

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="font-monument text-[var(--text-h3)] mb-3">{title}</h2>
      <div className="text-steel text-sm leading-relaxed space-y-3">{children}</div>
    </section>
  );
}

export default function DpaPage() {
  return (
    <>
    <JsonLd pathname="/dpa" />
    <main className="mx-auto max-w-4xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow="Legal"
        title="Data Processing Addendum"
        subtitle="This DPA governs how LAP processes personal data on behalf of customers acting as data controllers."
      />
      <div className="border border-steel/20 bg-concrete/30 p-6 mb-8">
        <p className="text-steel text-sm leading-relaxed">
          This Data Processing Addendum (&ldquo;DPA&rdquo;) forms part of the agreement between the
          Customer (&ldquo;Controller&rdquo;) and Lap Coach (&ldquo;Processor&rdquo;) for
          the provision of telemetry analysis services. It applies to any processing of personal data
          where the Controller determines the purposes and means, and the Processor acts solely on
          documented instructions.
        </p>
      </div>

      <Section title="1. Definitions">
        <p>
          &ldquo;Personal Data&rdquo;, &ldquo;Processing&rdquo;, &ldquo;Data Subject&rdquo;, and
          &ldquo;Supervisory Authority&rdquo; have the meanings given in the EU General Data
          Protection Regulation (EU) 2016/679 (&ldquo;GDPR&rdquo;).
        </p>
        <p>
          &ldquo;Sub-processor&rdquo; means any third party engaged by the Processor to process
          Personal Data on behalf of the Controller.
        </p>
      </Section>

      <Section title="2. Subject Matter and Duration">
        <p>
          The Processor processes Personal Data for the purpose of providing motorsport telemetry
          analysis, including CSV ingestion, lap scoring, corner analysis, race strategy computation,
          and session reporting. Processing continues for the duration of the service agreement.
        </p>
        <p>
          Categories of data subjects include: team drivers, team managers, and account
          administrators. Categories of personal data include: names, email addresses, telemetry
          session metadata (timestamps, GPS coordinates), and billing identifiers.
        </p>
      </Section>

      <Section title="3. Controller Instructions">
        <p>
          The Processor shall process Personal Data only on documented instructions from the
          Controller, including with regard to transfers to third countries, unless required to do so
          by EU or Member State law. In such a case, the Processor shall inform the Controller of
          that legal requirement before processing unless that law prohibits such notification.
        </p>
      </Section>

      <Section title="4. Confidentiality">
        <p>
          The Processor shall ensure that persons authorised to process Personal Data have committed
          themselves to confidentiality or are under an appropriate statutory obligation of
          confidentiality.
        </p>
      </Section>

      <Section title="5. Security Measures (Article 32)">
        <p>The Processor implements appropriate technical and organisational measures including:</p>
        <ul className="list-disc list-inside space-y-1 ml-2">
          <li>TLS 1.2+ encryption for all data in transit</li>
          <li>AES-256 encryption for data at rest (database and backups)</li>
          <li>Argon2id password hashing (time cost 3, memory 64 KiB)</li>
          <li>Row-Level Security (RLS) policies isolating workspace data at the database level</li>
          <li>JWT-based authentication with single-use refresh token rotation</li>
          <li>Daily encrypted backups with 7-day retention</li>
          <li>Redis-backed rate limiting across 5 severity tiers</li>
        </ul>
      </Section>

      <Section title="6. Sub-processors">
        <p>
          The Controller grants general written authorisation for the Processor to engage
          sub-processors. The Processor shall notify the Controller at least 30 days before adding or
          replacing a sub-processor. The current sub-processor list is maintained at{' '}
          <Link href="/subprocessors" className="text-pit-orange hover:underline">
            /subprocessors
          </Link>
          .
        </p>
        <p>
          Where a sub-processor fails to fulfil its data protection obligations, the Processor
          remains fully liable to the Controller for the performance of that sub-processor&rsquo;s
          obligations.
        </p>
      </Section>

      <Section title="7. Data Subject Rights (Articles 15–22)">
        <p>
          The Processor shall assist the Controller by appropriate technical and organisational
          measures, insofar as this is possible, for the fulfilment of the Controller&rsquo;s
          obligation to respond to requests for exercising the data subject&rsquo;s rights: access,
          rectification, erasure, restriction, portability, and objection.
        </p>
        <p>
          Self-service data export and account erasure are available through the application. GDPR
          requests that cannot be handled through self-service may be directed to{' '}
          <span className="text-chalk">privacy@lap-coach.racing</span>.
        </p>
      </Section>

      <Section title="8. Breach Notification">
        <p>
          The Processor shall notify the Controller without undue delay, and no later than 72 hours,
          after becoming aware of a personal data breach. Notification shall include the nature of
          the breach, categories and approximate number of data subjects affected, likely
          consequences, and measures taken or proposed to address the breach.
        </p>
      </Section>

      <Section title="9. International Transfers">
        <p>
          Primary data processing occurs in EU data centres (Hetzner, Falkenstein, Germany). Where
          sub-processors process data outside the EEA, Standard Contractual Clauses (SCCs) approved
          by the European Commission apply. Details of each sub-processor&rsquo;s data location are
          listed on the{' '}
          <Link href="/subprocessors" className="text-pit-orange hover:underline">
            subprocessors page
          </Link>
          .
        </p>
      </Section>

      <Section title="10. Deletion and Return">
        <p>
          Upon termination of the service agreement, the Processor shall, at the choice of the
          Controller, delete or return all Personal Data and delete existing copies unless EU or
          Member State law requires storage of the Personal Data. Workspace data is retained for the
          configured retention period and then permanently deleted.
        </p>
      </Section>

      <Section title="11. Audit Rights">
        <p>
          The Processor shall make available to the Controller all information necessary to
          demonstrate compliance with Article 28 obligations and allow for and contribute to audits,
          including inspections, conducted by the Controller or another auditor mandated by the
          Controller. Enterprise customers may request a formal audit through the contact route.
        </p>
      </Section>

      <div className="border border-steel/20 p-4 mt-8">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">Request a Signed DPA</h2>
        <p className="text-steel text-sm leading-relaxed mb-3">
          Enterprise and team customers who require a countersigned DPA or custom addenda may request
          one through the contact form.
        </p>
        <Link
          href="/contact"
          className="inline-block border border-pit-orange text-pit-orange px-4 py-2 text-sm font-telemetry uppercase tracking-wider hover:bg-pit-orange/10 transition-colors"
        >
          Request DPA
        </Link>
      </div>
    </main>
    </>
  );
}
