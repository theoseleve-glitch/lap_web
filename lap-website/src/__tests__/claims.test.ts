import { describe, expect, it } from 'vitest';
import { capabilityClaims, claimsByStatus, getClaimsForSurface } from '@/data/claim-registry';

describe('Claim registry', () => {
  it('contains uniquely identified claims', () => {
    const ids = capabilityClaims.map((claim) => claim.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('separates statuses for availability messaging', () => {
    expect(claimsByStatus.available_now.length).toBeGreaterThan(0);
    expect(claimsByStatus.enterprise_on_request.length).toBeGreaterThan(0);
    expect(claimsByStatus.roadmap.length).toBeGreaterThan(0);
  });

  it('returns product claims for product surface', () => {
    const productClaims = getClaimsForSurface('product');
    expect(productClaims.length).toBeGreaterThan(0);
  });
});
