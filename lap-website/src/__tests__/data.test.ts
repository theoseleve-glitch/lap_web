import { describe, it, expect } from 'vitest';
import { b2cPlans, b2bCard, featureEligibilityMatrix, dataLifecycle } from '@/data/pricing';
import { faqItems } from '@/data/faq';
import { pipelineStages } from '@/data/pipeline-stages';
import * as copy from '@/data/copy';

describe('Pricing data', () => {
  it('has 3 B2C plans', () => {
    expect(b2cPlans).toHaveLength(3);
    expect(b2cPlans[0].name).toBe('DEMO');
    expect(b2cPlans[1].highlighted).toBe(true);
    expect(b2cPlans[0].ctaHref).toBe('/register?source=demo');
  });

  it('has a B2B card', () => {
    expect(b2bCard.name).toBe('FOR TEAMS & CIRCUITS');
    expect(b2bCard.features.length).toBeGreaterThanOrEqual(4);
  });

  it('has a feature eligibility matrix', () => {
    expect(featureEligibilityMatrix.length).toBeGreaterThanOrEqual(15);
    const groups = [...new Set(featureEligibilityMatrix.map((r) => r.group))];
    expect(groups).toContain('coaching');
    expect(groups).toContain('strategy');
    expect(groups).toContain('data');
  });

  it('has data lifecycle items', () => {
    expect(dataLifecycle).toHaveLength(3);
    expect(dataLifecycle[0].category).toBe('RAW TELEMETRY');
  });
});

describe('FAQ data', () => {
  it('has 6 items', () => {
    expect(faqItems).toHaveLength(6);
    expect(faqItems[5].answer.toLowerCase()).toContain('roadmap');
  });
});

describe('Pipeline stages', () => {
  it('has 5 stages', () => {
    expect(pipelineStages).toHaveLength(5);
    expect(pipelineStages[0].name).toBe('INGEST');
    expect(pipelineStages[4].name).toBe('REPORT');
  });
});

describe('Copy', () => {
  it('defines all room copy objects', () => {
    expect(copy.startGrid.monument).toHaveLength(2);
    expect(copy.s1Pain.monument).toHaveLength(2);
    expect(copy.s2Proof.plates).toHaveLength(3);
    expect(copy.s3Product.coaching.tiles).toHaveLength(3);
    expect(copy.s3Product.strategy.tiles).toHaveLength(3);
    expect(copy.pitStop.riskReversal).toHaveLength(6);
    expect(copy.garage.panels).toHaveLength(4);
    expect(copy.podium.monument).toHaveLength(2);
  });
});
