# Immersive Lap Mockup

## What Was Added
- New isolated experimental route: `/concept/lap-3d-v1`
- New isolated experimental route: `/concept/lap-3d-v2`
- New concept components under `src/components/concepts/lap3d/`
- One route-scoped CSS module for the mockup look and motion treatment
- Light smoke tests covering route metadata and core narrative beats for both variants

## Existing Stack Reused
- Next.js App Router for the route itself
- Tailwind-era design tokens and global font/color system from `src/styles/tokens.css` and `src/app/globals.css`
- Existing `gsap` + `ScrollTrigger` setup for scroll choreography
- Existing `useReducedMotion` and GSAP registration helper

## Dependencies Added
- None

## Implementation Notes
- The mockup intentionally does **not** reuse the homepage `ExperienceKernel`.
- The current immersive homepage shell is tightly coupled to `/`, its room IDs, and its own chrome assumptions.
- This route instead proves the design direction with a lighter pseudo-3D approach: sticky sections, parallax layers, racing-line motifs, and scrubbed GSAP transitions.
- The v2 route adds a route-scoped React Three Fiber world so the track, camera, and telemetry atmosphere move physically with scroll progress.
- No production homepage files were changed for the concept.

## Variant Comparison
- `v1` is the lighter pseudo-3D proof: lower implementation cost, faster to adapt, good for validating composition and section rhythm.
- `v2` is the stronger brand direction: deeper spatial presence, camera-led motion, and a more convincing sense that the website itself is one lap.
- Recommended base for production: `v2`, with a staged rollout that first ports the hero world, braking-zone sequence, and final CTA language into shared homepage primitives.

## Next Step Toward Production
- Lift the strongest pieces into shared marketing primitives first:
  - hero composition and start/finish rhythm
  - pinned telemetry pipeline choreography
  - progress rail / racing-line motifs
  - premium CTA close
- After that, either:
  - replace selected homepage rooms one by one, or
  - generalize the existing `ExperienceShell` so non-home concept routes can opt into it safely.

The recommended path is incremental adoption into `/`, not a direct copy-paste replacement of the experimental route.
