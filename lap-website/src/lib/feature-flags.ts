/**
 * Feature flags for the experience layer.
 *
 * NEXT_PUBLIC_EXPERIENCE_V2 gates all new narrative/reveal/HUD systems.
 * When off (default in production until validated), existing behavior is unchanged.
 */
export const EXPERIENCE_V2 =
  typeof process !== 'undefined'
    ? process.env.NEXT_PUBLIC_EXPERIENCE_V2 === '1'
    : false;
