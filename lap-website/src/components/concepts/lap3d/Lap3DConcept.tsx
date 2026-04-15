'use client';

import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { registerGsap } from '@/lib/gsap-config';
import { Lap3DProgress, type Lap3DBeat } from './Lap3DProgress';
import { Lap3DTrackMotif } from './Lap3DTrackMotif';
import styles from './Lap3DConcept.module.css';

const BEATS = [
  { id: 'hero', label: 'Start / Finish', title: 'Opening statement' },
  { id: 'problem', label: 'Problem', title: 'Invisible time loss' },
  { id: 'pipeline', label: 'Pipeline', title: 'Telemetry in motion' },
  { id: 'cta', label: 'Differentiation', title: 'Premium close' },
] as const satisfies readonly Lap3DBeat[];

const ROOT_STYLE = {
  '--lap-progress': '0',
} as CSSProperties & Record<'--lap-progress', string>;

export function Lap3DConcept() {
  const rootRef = useRef<HTMLDivElement>(null);
  const [activeBeat, setActiveBeat] = useState<(typeof BEATS)[number]['id']>('hero');
  const { reducedMotion } = useReducedMotion();

  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    registerGsap();
    gsap.registerPlugin(ScrollTrigger);

    const ctx = gsap.context(() => {
      gsap.set(root, { '--lap-progress': 0 });

      ScrollTrigger.create({
        trigger: root,
        start: 'top top',
        end: 'bottom bottom',
        onUpdate: (self) => {
          root.style.setProperty('--lap-progress', self.progress.toFixed(3));
        },
      });

      const sections = gsap.utils.toArray<HTMLElement>('[data-lap-section]');
      sections.forEach((section, index) => {
        ScrollTrigger.create({
          trigger: section,
          start: 'top 48%',
          end: 'bottom 48%',
          onToggle: (self) => {
            if (!self.isActive) return;
            const nextBeat = BEATS[index];
            if (nextBeat) {
              setActiveBeat(nextBeat.id);
            }
          },
        });

        if (reducedMotion) return;

        const panel = section.querySelector<HTMLElement>('[data-beat-panel]');
        if (panel) {
          gsap.fromTo(
            panel,
            {
              opacity: 0.22,
              yPercent: 12,
              scale: 0.96,
              filter: 'blur(16px)',
            },
            {
              opacity: 1,
              yPercent: 0,
              scale: 1,
              filter: 'blur(0px)',
              ease: 'none',
              scrollTrigger: {
                trigger: section,
                start: 'top 82%',
                end: 'center center',
                scrub: 0.8,
              },
            },
          );
        }

        section.querySelectorAll<HTMLElement>('[data-depth]').forEach((layer) => {
          const depth = Number(layer.dataset.depth ?? '0');
          if (!depth) return;

          gsap.fromTo(
            layer,
            { yPercent: depth * -20 },
            {
              yPercent: depth * 20,
              ease: 'none',
              scrollTrigger: {
                trigger: section,
                start: 'top bottom',
                end: 'bottom top',
                scrub: 0.6,
              },
            },
          );
        });
      });

      if (!reducedMotion) {
        const problemCards = gsap.utils.toArray<HTMLElement>('[data-problem-card]');
        if (problemCards.length > 0) {
          gsap.fromTo(
            problemCards,
            { opacity: 0.28, y: 36, x: 18, filter: 'blur(14px)' },
            {
              opacity: 1,
              y: 0,
              x: 0,
              filter: 'blur(0px)',
              stagger: 0.08,
              ease: 'none',
              scrollTrigger: {
                trigger: '[data-beat="problem"]',
                start: 'top 75%',
                end: 'center center',
                scrub: 0.6,
              },
            },
          );
        }

        const pipelineSection = root.querySelector<HTMLElement>('[data-beat="pipeline"]');
        const pipelineBlocks = gsap.utils.toArray<HTMLElement>('[data-pipeline-block]');
        const pipelineLine = pipelineSection?.querySelector<HTMLElement>('[data-pipeline-line]');
        const pipelinePulse = pipelineSection?.querySelector<HTMLElement>('[data-pipeline-pulse]');

        if (pipelineSection && pipelineBlocks.length > 0) {
          const timeline = gsap.timeline({
            defaults: { ease: 'none' },
            scrollTrigger: {
              trigger: pipelineSection,
              start: 'top top',
              end: 'bottom bottom',
              scrub: 0.9,
            },
          });

          if (pipelineLine) {
            timeline.fromTo(
              pipelineLine,
              { scaleX: 0.2, opacity: 0.22 },
              { scaleX: 1, opacity: 1, transformOrigin: 'left center', duration: 0.16 },
              0,
            );
          }

          if (pipelinePulse) {
            timeline.fromTo(
              pipelinePulse,
              { xPercent: -12, opacity: 0.25 },
              { xPercent: 220, opacity: 1, duration: 0.6 },
              0.08,
            );
          }

          pipelineBlocks.forEach((block, index) => {
            const stepPosition = 0.14 + index * 0.16;
            timeline.fromTo(
              block,
              {
                opacity: index === 0 ? 1 : 0.16,
                y: 82 - index * 10,
                scale: 0.8 + index * 0.04,
                filter: 'blur(12px)',
              },
              {
                opacity: 1,
                y: 0,
                scale: 1,
                filter: 'blur(0px)',
                duration: 0.1,
              },
              stepPosition,
            );

            const previous = pipelineBlocks[index - 1];
            if (previous) {
              timeline.to(
                previous,
                {
                  opacity: 0.34,
                  y: -22,
                  scale: 0.94,
                  duration: 0.1,
                },
                stepPosition,
              );
            }
          });
        }

        const ctaItems = gsap.utils.toArray<HTMLElement>('[data-cta-item]');
        if (ctaItems.length > 0) {
          gsap.fromTo(
            ctaItems,
            { opacity: 0.2, y: 40, filter: 'blur(12px)' },
            {
              opacity: 1,
              y: 0,
              filter: 'blur(0px)',
              stagger: 0.09,
              ease: 'none',
              scrollTrigger: {
                trigger: '[data-beat="cta"]',
                start: 'top 74%',
                end: 'center center',
                scrub: 0.7,
              },
            },
          );
        }
      }
    }, root);

    return () => {
      ctx.revert();
    };
  }, [reducedMotion]);

  return (
    <div ref={rootRef} className={styles.page} style={ROOT_STYLE}>
      <div className={styles.utilityBar}>
        <span className={styles.utilityLabel}>LAP experimental route</span>
        <a className={styles.utilityLink} href="/">
          Return to production home
        </a>
      </div>

      <Lap3DProgress beats={BEATS} activeBeat={activeBeat} />

      <main className={styles.main}>
        <section
          id="beat-hero"
          data-lap-section
          data-beat="hero"
          className={`${styles.section} ${styles.heroSection}`}
          aria-label="Hero"
        >
          <div className={styles.stickyStage}>
            <div className={`${styles.sectionWash} ${styles.heroWash}`} data-depth="0.2" />
            <div className={`${styles.sectionGrid} ${styles.heroGrid}`} data-depth="0.12" />
            <Lap3DTrackMotif className={styles.heroMotif} variant="hero" />
            <div className={styles.heroOrb} data-depth="0.18" />

            <div className={`${styles.panel} ${styles.heroPanel}`} data-beat-panel>
              <p className={styles.eyebrow}>Start / Finish</p>
              <div className={styles.startFinishMark} aria-hidden="true" />
              <h1 className={styles.heroTitle}>
                One lap.
                <br />
                One decisive view.
              </h1>
              <p className={styles.heroCopy}>
                A premium motorsport landing-page concept where scroll behaves like forward motion,
                each section feels spatial, and the story resolves like a timed lap instead of a
                traditional homepage.
              </p>
              <div className={styles.metricRow}>
                <div className={styles.metricChip}>
                  <span className={styles.metricLabel}>Mood</span>
                  <span className={styles.metricValue}>Dark / technical / premium</span>
                </div>
                <div className={styles.metricChip}>
                  <span className={styles.metricLabel}>Motion</span>
                  <span className={styles.metricValue}>Forward pull with restrained red accents</span>
                </div>
                <div className={styles.metricChip}>
                  <span className={styles.metricLabel}>Intent</span>
                  <span className={styles.metricValue}>Prove the homepage can feel like a lap</span>
                </div>
              </div>
              <div className={styles.actionRow}>
                <a className={styles.primaryAction} href="#beat-problem">
                  Take the first sector
                </a>
                <a className={styles.secondaryAction} href="#beat-cta">
                  Jump to the finish
                </a>
              </div>
            </div>
          </div>
        </section>

        <section
          id="beat-problem"
          data-lap-section
          data-beat="problem"
          className={`${styles.section} ${styles.problemSection}`}
          aria-label="Problem"
        >
          <div className={styles.stickyStage}>
            <div className={`${styles.sectionWash} ${styles.problemWash}`} data-depth="0.18" />
            <div className={styles.problemCurve} data-depth="-0.14" />
            <Lap3DTrackMotif className={styles.problemMotif} variant="problem" />

            <div className={styles.problemGrid}>
              <div className={`${styles.panel} ${styles.problemPanel}`} data-beat-panel>
                <p className={styles.eyebrow}>Problem</p>
                <h2 className={styles.sectionTitle}>
                  Time disappears before teams can explain it.
                </h2>
                <p className={styles.sectionCopy}>
                  Conventional telemetry pages often tell the truth too late. By the time the eye
                  understands what happened through entry, apex, and exit, the emotional momentum is
                  gone. The landing experience should make that loss legible immediately.
                </p>
                <p className={styles.problemQuote}>
                  The fast answer is not a bigger dashboard. It is a narrative that reveals where
                  the lap broke, in motion, before the visitor needs to read a paragraph.
                </p>
              </div>

              <div className={styles.deltaStack}>
                <article className={styles.deltaCard} data-problem-card data-depth="0.08">
                  <p className={styles.deltaLabel}>Entry</p>
                  <p className={styles.deltaValue}>+0.18s</p>
                  <p className={styles.deltaCopy}>Brake release hides the first error.</p>
                </article>
                <article className={styles.deltaCard} data-problem-card data-depth="0.14">
                  <p className={styles.deltaLabel}>Apex</p>
                  <p className={styles.deltaValue}>+0.42s</p>
                  <p className={styles.deltaCopy}>The line looks calm while the speed has already gone.</p>
                </article>
                <article className={styles.deltaCard} data-problem-card data-depth="0.2">
                  <p className={styles.deltaLabel}>Exit</p>
                  <p className={styles.deltaValue}>+0.11s</p>
                  <p className={styles.deltaCopy}>Traction loss lingers farther than the eye expects.</p>
                </article>
              </div>
            </div>
          </div>
        </section>

        <section
          id="beat-pipeline"
          data-lap-section
          data-beat="pipeline"
          className={`${styles.section} ${styles.pipelineSection}`}
          aria-label="Telemetry pipeline"
        >
          <div className={styles.stickyStage}>
            <div className={`${styles.sectionWash} ${styles.pipelineWash}`} data-depth="0.16" />
            <Lap3DTrackMotif className={styles.pipelineMotif} variant="pipeline" />

            <div className={styles.pipelineHeader}>
              <p className={styles.eyebrow}>Telemetry Pipeline</p>
              <h2 className={styles.sectionTitle}>
                Telemetry should move like a car, not a spreadsheet.
              </h2>
              <p className={styles.sectionCopy}>
                The middle of the concept is a pinned pipeline. Each stage advances into the next,
                showing how raw laps can become scoring, coaching, and decisions without feeling like
                a static software diagram.
              </p>
            </div>

            <div className={`${styles.panel} ${styles.pipelinePanel}`} data-beat-panel>
              <div className={styles.pipelineLane}>
                <div className={styles.pipelineLine} data-pipeline-line />
                <div className={styles.pipelinePulse} data-pipeline-pulse />
                <article
                  className={`${styles.pipelineBlock} ${styles.pipelineBlock1}`}
                  data-pipeline-block
                >
                  <p className={styles.pipelineStep}>01</p>
                  <h3 className={styles.pipelineTitle}>Capture</h3>
                  <p className={styles.pipelineCopy}>
                    RaceChrono, AiM, MoTeC, and venue feeds arrive as the opening straight.
                  </p>
                </article>
                <article
                  className={`${styles.pipelineBlock} ${styles.pipelineBlock2}`}
                  data-pipeline-block
                >
                  <p className={styles.pipelineStep}>02</p>
                  <h3 className={styles.pipelineTitle}>Normalize</h3>
                  <p className={styles.pipelineCopy}>
                    Sessions align to one track narrative instead of fragmented files.
                  </p>
                </article>
                <article
                  className={`${styles.pipelineBlock} ${styles.pipelineBlock3}`}
                  data-pipeline-block
                >
                  <p className={styles.pipelineStep}>03</p>
                  <h3 className={styles.pipelineTitle}>Model</h3>
                  <p className={styles.pipelineCopy}>
                    Time loss, confidence, and scoring become visible as motion, not just tables.
                  </p>
                </article>
                <article
                  className={`${styles.pipelineBlock} ${styles.pipelineBlock4}`}
                  data-pipeline-block
                >
                  <p className={styles.pipelineStep}>04</p>
                  <h3 className={styles.pipelineTitle}>Coach</h3>
                  <p className={styles.pipelineCopy}>
                    The visitor arrives at decisions, not raw telemetry debt.
                  </p>
                </article>
              </div>

              <div className={styles.pipelineMetrics}>
                <div className={styles.pipelineMetric}>
                  <span className={styles.metricLabel}>Narrative role</span>
                  <span className={styles.metricValue}>Pinned center sector</span>
                </div>
                <div className={styles.pipelineMetric}>
                  <span className={styles.metricLabel}>Visual tactic</span>
                  <span className={styles.metricValue}>Perspective blocks + racing line</span>
                </div>
                <div className={styles.pipelineMetric}>
                  <span className={styles.metricLabel}>Product read</span>
                  <span className={styles.metricValue}>Sophisticated without becoming sci-fi</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section
          id="beat-cta"
          data-lap-section
          data-beat="cta"
          className={`${styles.section} ${styles.ctaSection}`}
          aria-label="Product differentiation and call to action"
        >
          <div className={styles.stickyStage}>
            <div className={`${styles.sectionWash} ${styles.ctaWash}`} data-depth="0.14" />
            <div className={styles.finishGlow} data-depth="-0.08" />
            <Lap3DTrackMotif className={styles.ctaMotif} variant="cta" />

            <div className={styles.ctaGrid}>
              <div className={`${styles.panel} ${styles.ctaNarrative}`} data-beat-panel>
                <p className={styles.eyebrow}>Differentiation</p>
                <h2 className={styles.sectionTitle}>
                  The differentiator is not more data. It is faster conviction.
                </h2>
                <p className={styles.sectionCopy}>
                  This concept positions LAP as a premium motorsport product: composed, technical,
                  spatial, and native to the discipline without leaning on a gaming interface or
                  cyberpunk language.
                </p>
                <div className={styles.differentiatorList}>
                  <article className={styles.differentiatorCard} data-cta-item>
                    <p className={styles.differentiatorTitle}>Spatial story</p>
                    <p className={styles.differentiatorCopy}>
                      Sections feel like sectors of a lap, not interchangeable marketing panels.
                    </p>
                  </article>
                  <article className={styles.differentiatorCard} data-cta-item>
                    <p className={styles.differentiatorTitle}>Premium restraint</p>
                    <p className={styles.differentiatorCopy}>
                      Editorial typography, quiet surfaces, and red only where pressure matters.
                    </p>
                  </article>
                  <article className={styles.differentiatorCard} data-cta-item>
                    <p className={styles.differentiatorTitle}>Production-ready direction</p>
                    <p className={styles.differentiatorCopy}>
                      The route proves the site can adopt immersive motion without refactoring the
                      existing homepage first.
                    </p>
                  </article>
                </div>
              </div>

              <aside className={`${styles.panel} ${styles.ctaPanel}`} data-cta-item>
                <p className={styles.ctaOverline}>Checkered flag</p>
                <h3 className={styles.ctaTitle}>Use the strongest pieces, then fold them into `/`.</h3>
                <p className={styles.ctaCopy}>
                  This is a capability proof, not a production replacement. The next move is to
                  graduate the hero rhythm, pipeline choreography, and finish-line close into shared
                  marketing components.
                </p>
                <div className={styles.actionStack}>
                  <a className={styles.primaryAction} href="/product">
                    See the current product page
                  </a>
                  <a className={styles.secondaryAction} href="/demo">
                    Compare against the live demo route
                  </a>
                </div>
                <div className={styles.checkerBar} aria-hidden="true" />
              </aside>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
