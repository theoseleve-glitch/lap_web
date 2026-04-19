'use client';

import dynamic from 'next/dynamic';
import {
  startTransition,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from 'react';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { registerGsap } from '@/lib/gsap-config';
import { Lap3DProgress, type Lap3DBeat } from './Lap3DProgress';
import { Lap3DTrackMotif } from './Lap3DTrackMotif';
import styles from './Lap3DConceptV2.module.css';

const Lap3DWorld = dynamic(
  () => import('./Lap3DWorld').then((mod) => mod.Lap3DWorld),
  { ssr: false, loading: () => null },
);

const BEATS = [
  { id: 'hero', label: 'Start / Finish', title: 'Opening surge' },
  { id: 'braking', label: 'Braking Zone', title: 'Hidden time under load' },
  { id: 'pipeline', label: 'Pipeline', title: 'Telemetry in motion' },
  { id: 'coaching', label: 'Coaching', title: 'Data becomes instruction' },
  { id: 'difference', label: 'Differentiation', title: 'Instrument-grade brand' },
  { id: 'cta', label: 'Checkered Flag', title: 'Premium close' },
] as const satisfies readonly Lap3DBeat[];

const ROOT_STYLE = {
  '--lap-progress': '0',
} as CSSProperties & Record<'--lap-progress', string>;

export function Lap3DConceptV2() {
  const rootRef = useRef<HTMLDivElement>(null);
  const progressRef = useRef(0);
  const [worldProgress, setWorldProgress] = useState(0);
  const [activeBeat, setActiveBeat] = useState<(typeof BEATS)[number]['id']>('hero');
  const { reducedMotion } = useReducedMotion();

  const activeIndex = useMemo(
    () => Math.max(0, BEATS.findIndex((beat) => beat.id === activeBeat)),
    [activeBeat],
  );

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
          const next = self.progress;
          root.style.setProperty('--lap-progress', next.toFixed(3));

          if (Math.abs(next - progressRef.current) < 0.003) {
            return;
          }

          progressRef.current = next;
          startTransition(() => setWorldProgress(next));
        },
      });

      const sections = gsap.utils.toArray<HTMLElement>('[data-v2-section]');
      sections.forEach((section, index) => {
        ScrollTrigger.create({
          trigger: section,
          start: 'top 50%',
          end: 'bottom 50%',
          onToggle: (self) => {
            if (!self.isActive) return;
            const nextBeat = BEATS[index];
            if (nextBeat) {
              startTransition(() => setActiveBeat(nextBeat.id));
            }
          },
        });

        if (reducedMotion) {
          return;
        }

        section.querySelectorAll<HTMLElement>('[data-immersive-panel]').forEach((panel) => {
          gsap.fromTo(
            panel,
            {
              opacity: 0.18,
              yPercent: 8,
              scale: 0.965,
              filter: 'blur(18px)',
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
                scrub: 0.9,
              },
            },
          );
        });

        section.querySelectorAll<HTMLElement>('[data-spatial-layer]').forEach((layer) => {
          const depth = Number(layer.dataset.spatialLayer ?? '0');
          if (!depth) return;

          gsap.fromTo(
            layer,
            { yPercent: depth * -18, rotateZ: depth * -2.5 },
            {
              yPercent: depth * 18,
              rotateZ: depth * 2.5,
              ease: 'none',
              scrollTrigger: {
                trigger: section,
                start: 'top bottom',
                end: 'bottom top',
                scrub: 0.75,
              },
            },
          );
        });
      });

      if (!reducedMotion) {
        const brakingCards = gsap.utils.toArray<HTMLElement>('[data-brake-card]');
        if (brakingCards.length > 0) {
          gsap.fromTo(
            brakingCards,
            { opacity: 0.24, y: 42, rotateX: -14, filter: 'blur(12px)' },
            {
              opacity: 1,
              y: 0,
              rotateX: 0,
              filter: 'blur(0px)',
              stagger: 0.08,
              ease: 'none',
              scrollTrigger: {
                trigger: '[data-beat="braking"]',
                start: 'top 76%',
                end: 'center center',
                scrub: 0.7,
              },
            },
          );
        }

        const pipelineCards = gsap.utils.toArray<HTMLElement>('[data-flow-card]');
        const pipelineSection = root.querySelector<HTMLElement>('[data-beat="pipeline"]');
        if (pipelineSection && pipelineCards.length > 0) {
          const timeline = gsap.timeline({
            defaults: { ease: 'none' },
            scrollTrigger: {
              trigger: pipelineSection,
              start: 'top top',
              end: 'bottom bottom',
              scrub: 0.95,
            },
          });

          pipelineCards.forEach((card, index) => {
            timeline.fromTo(
              card,
              {
                opacity: index === 0 ? 1 : 0.14,
                xPercent: 34 + index * 5,
                yPercent: 18 - index * 3,
                scale: 0.82 + index * 0.04,
                filter: 'blur(14px)',
              },
              {
                opacity: 1,
                xPercent: 0,
                yPercent: 0,
                scale: 1,
                filter: 'blur(0px)',
                duration: 0.11,
              },
              0.12 + index * 0.12,
            );

            if (index > 0) {
              timeline.to(
                pipelineCards[index - 1],
                {
                  opacity: 0.34,
                  yPercent: -10,
                  scale: 0.95,
                  duration: 0.11,
                },
                0.12 + index * 0.12,
              );
            }
          });
        }

        const coachCards = gsap.utils.toArray<HTMLElement>('[data-coach-card]');
        if (coachCards.length > 0) {
          gsap.fromTo(
            coachCards,
            { opacity: 0.2, y: 36, x: 16, filter: 'blur(12px)' },
            {
              opacity: 1,
              y: 0,
              x: 0,
              filter: 'blur(0px)',
              stagger: 0.08,
              ease: 'none',
              scrollTrigger: {
                trigger: '[data-beat="coaching"]',
                start: 'top 76%',
                end: 'center center',
                scrub: 0.7,
              },
            },
          );
        }

        const proofCards = gsap.utils.toArray<HTMLElement>('[data-proof-card]');
        if (proofCards.length > 0) {
          gsap.fromTo(
            proofCards,
            { opacity: 0.18, y: 40, filter: 'blur(12px)' },
            {
              opacity: 1,
              y: 0,
              filter: 'blur(0px)',
              stagger: 0.08,
              ease: 'none',
              scrollTrigger: {
                trigger: '[data-beat="difference"]',
                start: 'top 76%',
                end: 'center center',
                scrub: 0.6,
              },
            },
          );
        }

        const finalCards = gsap.utils.toArray<HTMLElement>('[data-final-card]');
        if (finalCards.length > 0) {
          gsap.fromTo(
            finalCards,
            { opacity: 0.16, y: 46, filter: 'blur(14px)' },
            {
              opacity: 1,
              y: 0,
              filter: 'blur(0px)',
              stagger: 0.1,
              ease: 'none',
              scrollTrigger: {
                trigger: '[data-beat="cta"]',
                start: 'top 78%',
                end: 'center center',
                scrub: 0.65,
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
      <Lap3DWorld progress={worldProgress} activeIndex={activeIndex} reducedMotion={reducedMotion} />
      <div className={styles.worldVeil} aria-hidden="true" />

      <div className={styles.utilityBar}>
        <span className={styles.utilityLabel}>LAP experimental route</span>
        <div className={styles.utilityLinks}>
          <a className={styles.utilityLink} href="/concept/lap-3d-v1">
            Compare v1
          </a>
          <a className={styles.utilityLink} href="/">
            Return to production home
          </a>
        </div>
      </div>

      <div className={styles.telemetryDeck} aria-hidden="true">
        <div className={styles.telemetryReadout}>
          <span className={styles.telemetryLabel}>Variant</span>
          <span className={styles.telemetryValue}>v2 / spatial camera</span>
        </div>
        <div className={styles.telemetryReadout}>
          <span className={styles.telemetryLabel}>Lap progress</span>
          <span className={styles.telemetryValue}>{Math.round(worldProgress * 100)}%</span>
        </div>
        <div className={styles.telemetryReadout}>
          <span className={styles.telemetryLabel}>Current beat</span>
          <span className={styles.telemetryValue}>{BEATS[activeIndex]?.label ?? 'Start / Finish'}</span>
        </div>
      </div>

      <Lap3DProgress beats={BEATS} activeBeat={activeBeat} />

      <main id="main-content" className={styles.main}>
        <section
          id="lap-v2-hero"
          data-v2-section
          data-beat="hero"
          className={`${styles.section} ${styles.heroSection}`}
          aria-label="Start / finish hero"
        >
          <div className={styles.stickyStage}>
            <div className={styles.heroHalo} data-spatial-layer="0.14" />
            <Lap3DTrackMotif className={styles.heroMotif} variant="hero" />
            <div className={styles.heroLayout}>
              <div className={styles.heroCopyBlock} data-immersive-panel>
                <p className={styles.eyebrow}>Start / Finish</p>
                <div className={styles.finishMarker} aria-hidden="true" />
                <h1 className={styles.heroTitle}>
                  Hidden speed.
                  <br />
                  Revealed in one lap.
                </h1>
                <p className={styles.sectionCopy}>
                  A stronger premium direction where the site behaves like a physical journey through
                  the track, with camera motion, engineered atmosphere, and data emerging from the
                  dark at the moment it matters.
                </p>
                <div className={styles.actionRow}>
                  <a className={styles.primaryAction} href="#lap-v2-braking">
                    Roll into the braking zone
                  </a>
                  <a className={styles.secondaryAction} href="/concept/lap-3d-v1">
                    View the lighter variant
                  </a>
                </div>
              </div>

              <aside className={styles.heroSignalCard} data-immersive-panel>
                <p className={styles.cardEyebrow}>Designed for depth</p>
                <h2 className={styles.cardTitle}>A cleaner, more spatial direction for the brand.</h2>
                <div className={styles.signalList}>
                  <div className={styles.signalItem}>
                    <span className={styles.telemetryLabel}>World</span>
                    <span className={styles.signalValue}>Route-scoped WebGL track</span>
                  </div>
                  <div className={styles.signalItem}>
                    <span className={styles.telemetryLabel}>Motion</span>
                    <span className={styles.signalValue}>Camera-led scroll progress</span>
                  </div>
                  <div className={styles.signalItem}>
                    <span className={styles.telemetryLabel}>Tone</span>
                    <span className={styles.signalValue}>Apple restraint, motorsport precision</span>
                  </div>
                </div>
              </aside>
            </div>
          </div>
        </section>

        <section
          id="lap-v2-braking"
          data-v2-section
          data-beat="braking"
          className={`${styles.section} ${styles.brakingSection}`}
          aria-label="Braking-zone tension"
        >
          <div className={styles.stickyStage}>
            <div className={styles.cornerWave} data-spatial-layer="-0.1" />
            <Lap3DTrackMotif className={styles.brakingMotif} variant="problem" />
            <div className={styles.sectionShell}>
              <div className={styles.sectionIntro} data-immersive-panel>
                <p className={styles.eyebrow}>Braking-zone tension</p>
                <h2 className={styles.sectionTitle}>The lap loses time before the eye notices.</h2>
                <p className={styles.sectionCopy}>
                  Pressure builds in the braking phase, not at the headline number. This section is
                  about invisible loss under load: where the driver thinks the lap is stable while the
                  delta is already escaping.
                </p>
              </div>

              <div className={styles.brakeGrid}>
                <article className={styles.tensionCard} data-brake-card>
                  <p className={styles.cardEyebrow}>Marker</p>
                  <p className={styles.tensionValue}>120m</p>
                  <p className={styles.cardCopy}>Brake release arrives one fraction too late.</p>
                </article>
                <article className={styles.tensionCard} data-brake-card>
                  <p className={styles.cardEyebrow}>Delta</p>
                  <p className={styles.tensionValue}>+0.31s</p>
                  <p className={styles.cardCopy}>Minimum speed looks composed while the lap bleeds time.</p>
                </article>
                <article className={styles.tensionCard} data-brake-card>
                  <p className={styles.cardEyebrow}>Load</p>
                  <p className={styles.tensionValue}>1.87g</p>
                  <p className={styles.cardCopy}>The tension is hidden in the data, not the screenshot.</p>
                </article>
              </div>
            </div>
          </div>
        </section>

        <section
          id="lap-v2-pipeline"
          data-v2-section
          data-beat="pipeline"
          className={`${styles.section} ${styles.pipelineSection}`}
          aria-label="Telemetry pipeline in motion"
        >
          <div className={styles.stickyStage}>
            <div className={styles.pipelineGlow} data-spatial-layer="0.12" />
            <Lap3DTrackMotif className={styles.pipelineMotif} variant="pipeline" />
            <div className={styles.sectionShell}>
              <div className={styles.sectionIntro} data-immersive-panel>
                <p className={styles.eyebrow}>Telemetry pipeline in motion</p>
                <h2 className={styles.sectionTitle}>Telemetry pipeline, not a process diagram.</h2>
                <p className={styles.sectionCopy}>
                  The pipeline should feel like the lap is still moving underneath it. Raw data,
                  alignment, modelling, and coaching advance as a controlled flow instead of stacked
                  enterprise boxes.
                </p>
              </div>

              <div className={styles.flowStage} data-immersive-panel>
                <div className={styles.flowRail} />
                <article className={styles.flowCard} data-flow-card>
                  <p className={styles.cardEyebrow}>01 / Capture</p>
                  <h3 className={styles.flowTitle}>Raw lap sources enter with pace intact.</h3>
                  <p className={styles.cardCopy}>AiM, MoTeC, RaceChrono, and venue feeds stay anchored to the track.</p>
                </article>
                <article className={styles.flowCard} data-flow-card>
                  <p className={styles.cardEyebrow}>02 / Normalize</p>
                  <h3 className={styles.flowTitle}>Events collapse into one aligned track truth.</h3>
                  <p className={styles.cardCopy}>Sectors and curves match the same physical world.</p>
                </article>
                <article className={styles.flowCard} data-flow-card>
                  <p className={styles.cardEyebrow}>03 / Model</p>
                  <h3 className={styles.flowTitle}>Hidden pressure becomes legible signal.</h3>
                  <p className={styles.cardCopy}>Curvature, delta, grip, and confidence gain a narrative role.</p>
                </article>
                <article className={styles.flowCard} data-flow-card>
                  <p className={styles.cardEyebrow}>04 / Coach</p>
                  <h3 className={styles.flowTitle}>The product ends at conviction, not raw output.</h3>
                  <p className={styles.cardCopy}>The visitor arrives at next actions, not more telemetry debt.</p>
                </article>
              </div>
            </div>
          </div>
        </section>

        <section
          id="lap-v2-coaching"
          data-v2-section
          data-beat="coaching"
          className={`${styles.section} ${styles.coachingSection}`}
          aria-label="Data becomes coaching"
        >
          <div className={styles.stickyStage}>
            <div className={styles.coachingAura} data-spatial-layer="0.12" />
            <Lap3DTrackMotif className={styles.coachingMotif} variant="cta" />
            <div className={styles.sectionShell}>
              <div className={styles.sectionIntro} data-immersive-panel>
                <p className={styles.eyebrow}>Data becomes coaching</p>
                <h2 className={styles.sectionTitle}>The data becomes coaching while the car is still alive.</h2>
                <p className={styles.sectionCopy}>
                  This beat closes the gap between analysis and instruction. Instead of a passive report,
                  the brand experience shows how pace, line, and guidance resolve into one usable answer.
                </p>
              </div>

              <div className={styles.coachingBoard}>
                <article className={styles.coachCard} data-coach-card>
                  <p className={styles.cardEyebrow}>Trace</p>
                  <h3 className={styles.flowTitle}>Brake release drifts two frames late.</h3>
                  <p className={styles.cardCopy}>The problem is seen on the line, not buried in a chart legend.</p>
                </article>
                <article className={styles.coachCard} data-coach-card>
                  <p className={styles.cardEyebrow}>Instruction</p>
                  <h3 className={styles.flowTitle}>Release earlier, let the nose take rotation.</h3>
                  <p className={styles.cardCopy}>The output lands as a coaching move, not a diagnostic sentence.</p>
                </article>
                <article className={styles.coachCard} data-coach-card>
                  <p className={styles.cardEyebrow}>Outcome</p>
                  <h3 className={styles.flowTitle}>The same corner comes back with less drama.</h3>
                  <p className={styles.cardCopy}>Data resolves into confidence, which is what the product actually sells.</p>
                </article>
              </div>
            </div>
          </div>
        </section>

        <section
          id="lap-v2-difference"
          data-v2-section
          data-beat="difference"
          className={`${styles.section} ${styles.differenceSection}`}
          aria-label="Differentiation statement"
        >
          <div className={styles.stickyStage}>
            <div className={styles.differenceField} data-spatial-layer="-0.08" />
            <div className={styles.sectionShell}>
              <div className={styles.differenceStatement} data-immersive-panel>
                <p className={styles.eyebrow}>Differentiation statement</p>
                <h2 className={styles.sectionTitle}>Designed like an instrument, not a dashboard.</h2>
                <p className={styles.sectionCopy}>
                  The strongest direction is not louder graphics. It is a controlled visual system that
                  feels engineered, premium, and native to motorsport without borrowing gaming language.
                </p>
              </div>

              <div className={styles.proofGrid}>
                <article className={styles.proofCard} data-proof-card>
                  <p className={styles.cardEyebrow}>Restraint</p>
                  <p className={styles.cardCopy}>White and charcoal do most of the work. Red only marks pressure.</p>
                </article>
                <article className={styles.proofCard} data-proof-card>
                  <p className={styles.cardEyebrow}>Spatiality</p>
                  <p className={styles.cardCopy}>The route carries a world, not just floating sections.</p>
                </article>
                <article className={styles.proofCard} data-proof-card>
                  <p className={styles.cardEyebrow}>Signal</p>
                  <p className={styles.cardCopy}>Copy stays short, and the motion carries the explanation.</p>
                </article>
              </div>
            </div>
          </div>
        </section>

        <section
          id="lap-v2-cta"
          data-v2-section
          data-beat="cta"
          className={`${styles.section} ${styles.ctaSection}`}
          aria-label="Final premium call to action"
        >
          <div className={styles.stickyStage}>
            <div className={styles.ctaGlow} data-spatial-layer="0.1" />
            <div className={styles.sectionShell}>
              <div className={styles.finalPanel} data-immersive-panel data-final-card>
                <p className={styles.eyebrow}>Final premium CTA</p>
                <h2 className={styles.sectionTitle}>Choose the direction worth productionizing.</h2>
                <p className={styles.sectionCopy}>
                  Variant two is the stronger expression if the goal is a world-class brand presence.
                  It proves the stack can support a spatial, camera-led LAP experience while keeping the
                  experiment isolated from the current homepage.
                </p>
                <div className={styles.finalActions}>
                  <a className={styles.primaryAction} href="/concept/lap-3d-v1">
                    Compare both concepts
                  </a>
                  <a className={styles.secondaryAction} href="/product">
                    Return to the live product surface
                  </a>
                </div>
              </div>

              <aside className={styles.finalMeta} data-final-card>
                <div className={styles.finalMetaRow}>
                  <span className={styles.telemetryLabel}>Base route</span>
                  <span className={styles.telemetryValue}>/concept/lap-3d-v2</span>
                </div>
                <div className={styles.finalMetaRow}>
                  <span className={styles.telemetryLabel}>Rendering</span>
                  <span className={styles.telemetryValue}>Route-scoped R3F atmosphere</span>
                </div>
                <div className={styles.finalMetaRow}>
                  <span className={styles.telemetryLabel}>Production use</span>
                  <span className={styles.telemetryValue}>Best candidate for hero-led adoption</span>
                </div>
              </aside>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
