import { describe, it, expect } from 'vitest';
import { b2cPlans, featureEligibilityMatrix, dataLifecycle } from '@/data/pricing';
import { faqItems } from '@/data/faq';
import { pipelineStages } from '@/data/pipeline-stages';
import * as copy from '@/data/copy';

describe('Pricing data', () => {
  it('has one membership (June-8 model)', () => {
    expect(b2cPlans).toHaveLength(1);
    expect(b2cPlans[0].name).toBe('LAP COACH');
    expect(b2cPlans[0].highlighted).toBe(true);
    expect(b2cPlans[0].priceMonthly).toContain('19.90');
    expect(b2cPlans[0].foundingPriceMonthly).toContain('14.90');
    expect(b2cPlans[0].foundingLimit).toBe(50);
    expect(b2cPlans[0].trialDays).toBe(30);
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
