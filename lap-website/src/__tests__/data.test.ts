import { describe, it, expect } from 'vitest';
import { b2cPlans, b2bPlans, addons } from '@/data/pricing';
import { faqItems } from '@/data/faq';
import { pipelineStages } from '@/data/pipeline-stages';
import * as copy from '@/data/copy';

describe('Pricing data', () => {
  it('has 3 B2C plans', () => {
    expect(b2cPlans).toHaveLength(3);
    expect(b2cPlans[0].name).toBe('STARTER');
    expect(b2cPlans[1].highlighted).toBe(true);
    expect(b2cPlans[0].ctaHref).toBe('/book?plan=STARTER');
  });

  it('has 3 B2B plans', () => {
    expect(b2bPlans).toHaveLength(3);
    expect(b2bPlans[1].highlighted).toBe(true);
    expect(b2bPlans[0].name).toBe('TRACK ESSENTIAL');
  });

  it('has 5 add-ons', () => {
    expect(addons).toHaveLength(5);
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
    expect(copy.s3Product.b2b.placards).toHaveLength(4);
    expect(copy.pitStop.riskReversal).toHaveLength(6);
    expect(copy.garage.panels).toHaveLength(4);
    expect(copy.podium.monument).toHaveLength(2);
  });
});
