# Marble Generator: WebGL Fluid Engine + Color Distribution + Velocity Control

**Date**: 2026-03-02
**Status**: Approved

## Summary

Enhance the marble generator with three major features:
1. **N-color distribution** — 4-8 colors, presets, gradient distribution modes
2. **Newtonian fluid dynamics** — full WebGL2 Navier-Stokes solver with viscosity, vorticity confinement, multi-phase interaction
3. **Initial velocity choice** — directional presets, custom vector field editor, magnitude/direction/turbulence controls

## Architecture

Full WebGL2 pipeline for the browser. Enhanced CPU solver for the Node CLI.

```
marble_generator/
  index.html                    ← thin UI shell (controls + canvas)
  src/
    shaders/
      common.vert               ← fullscreen quad vertex shader
      fluid-step.frag           ← advection + vorticity + viscosity
      pressure.frag             ← pressure projection (Jacobi iteration)
      divergence.frag           ← divergence computation
      force.frag                ← external force application
      advect-dye.frag           ← multi-phase dye advection
      color-map.frag            ← N-color palette mapping + gradient modes
      velocity-init.frag        ← preset velocity field generators
      display.frag              ← final compositing + anti-aliasing
    gl/
      renderer.js               ← WebGL2 context, FBO management, ping-pong
      fluid-program.js          ← compile/link shader programs
      texture-pool.js           ← RGBA32F texture allocation + recycling
    engine/
      fluid-sim.js              ← orchestrate GPU fluid steps
      multi-phase.js            ← per-color-phase density/viscosity tracking
      velocity-presets.js       ← swirl, laminar, radial, turbulent generators
    color/
      palette.js                ← N-color system (shared: browser + CLI)
      presets.js                ← marble presets (calacatta, verde, rosso, etc.)
      distribution.js           ← radial/linear/clustered/veined modes (shared)
    ui/
      controls.js               ← DOM bindings, slider/picker management
      vector-editor.js          ← draw velocity arrows on canvas overlay
      studio.js                 ← interactive studio with GPU-accelerated drag
      gallery.js                ← card grid + generation queue
    cli.js                      ← Node CLI (CPU fallback, shares palette/presets)
    generator.js                ← CPU renderer (existing, enhanced for N-color)
```

## WebGL Fluid Engine

### Simulation Approach

Fragment shader ping-pong on RGBA32F textures (WebGL2 `EXT_color_buffer_float`).

### Simulation Grid

- Resolution: `canvas_width / 2` x `canvas_height / 2` (configurable downscale)
- Textures (all RGBA32F):
  - `velocity` — RG channels = (u, v), ping-pong pair
  - `pressure` — R channel, ping-pong pair
  - `divergence` — R channel, single
  - `dye[0..N]` — per-color-phase density fields (R channel each), ping-pong pairs

### Steps per Frame

```
1. addForce.frag      — splat external forces (brush drag, presets)
2. advect.frag        — semi-Lagrangian advection of velocity
3. vorticity.frag     — compute curl, apply vorticity confinement (ε)
4. viscosity.frag     — diffuse velocity (Jacobi, iterations ∝ viscosity)
5. divergence.frag    — compute velocity divergence
6. pressure.frag      — solve pressure Poisson (Jacobi, 30-60 iterations)
7. subtract-grad.frag — subtract pressure gradient → divergence-free
8. advect-dye.frag    — advect each color phase by velocity field
9. color-map.frag     — composite dye phases into final RGBA
```

### Physics Parameters

| Parameter | Range | Default | Effect |
|-----------|-------|---------|--------|
| Viscosity | 0.0001 - 0.1 | 0.001 | Low = water, High = honey |
| Density | 0.5 - 5.0 | 1.0 | Per-phase, heavier fluids sink |
| Vorticity (ε) | 0 - 50 | 15 | Small-scale swirl preservation |
| Diffusion | 0 - 0.01 | 0.0001 | Color bleed rate between phases |
| Timestep (dt) | 0.01 - 1.0 | 0.5 | Simulation speed |
| Pressure iterations | 10 - 80 | 40 | Incompressibility accuracy |

### Multi-Phase Interaction

Each color is a separate density field advected by the shared velocity. Density differences create buoyancy:

```glsl
vec2 buoyancy = vec2(0.0, -gravity * (local_density - ambient_density));
velocity += buoyancy * dt;
```

## Color Distribution

### N-Color System

- Up to 8 colors, each with: hex, ratio %, density, viscosity
- Dynamic UI rows with add/remove
- Ratios auto-normalize to 100%

### Distribution Modes

| Mode | Description |
|------|-------------|
| Veined (default) | FBM noise → threshold bands per color ratio |
| Radial | `distance(uv, center)` → ratio-weighted bands |
| Linear | `uv.x` or `uv.y` → ratio-weighted bands |
| Clustered | Voronoi cells assigned by ratio |
| Swirl | `atan2 + distance` → angular bands |

### Presets

```
Nero Marquina:   [#0a0a0c 60%, #ebe6dc 35%, #c3a54b 5%]     veined
Calacatta Gold:  [#f5f0e8 70%, #d4c9a8 20%, #b89b4f 10%]     veined
Verde Guatemala: [#1a3a2a 50%, #3d7a5a 35%, #e8e0d0 15%]     veined
Rosso Levanto:   [#6b1a1a 45%, #a83232 40%, #f0e8dc 15%]     veined
Blue Sodalite:   [#0d1b3a 40%, #1a3a6b 30%, #c3a54b 10%, #e8e0d0 20%] veined
Arabescato:      [#f2ede5 65%, #b0a898 25%, #555045 10%]     clustered
Portoro:         [#0a0a0a 75%, #c3a54b 18%, #e8d888 7%]      veined
Rainbow Onyx:    [#e8d0b0 30%, #c87850 20%, #6b4030 20%, #3a5040 15%, #d4a840 15%] swirl
```

## Initial Velocity System

### Presets

| Preset | Algorithm |
|--------|-----------|
| Curl Noise (default) | `u = dψ/dy, v = -dψ/dx` where ψ = FBM |
| Laminar H | `u = mag, v = 0` |
| Laminar V | `u = 0, v = mag` |
| Radial Out | `(x-cx, y-cy) / r * mag` |
| Radial In | inverse |
| Vortex | `(-(y-cy), (x-cx)) / r * mag` |
| Double Vortex | Two counter-rotating vortices |
| Turbulent | High-frequency curl noise |

### Controls

- Preset dropdown
- Magnitude slider (0-200)
- Direction angle (0-360)
- Turbulence slider (0-100)

### Custom Vector Field Editor

SVG overlay on canvas for placing/dragging velocity arrows. RBF interpolation fills the grid between arrows. Exported as Float32Array → velocity texture.

## Performance

### Targets

| Resolution | Current CPU | WebGL2 Target |
|------------|------------|---------------|
| 960x540 | ~2s | ~30ms |
| 1920x1080 | ~8s | ~60ms |
| 3840x2160 | ~30s | ~150ms |

### Fallback

If `EXT_color_buffer_float` unavailable, fall back to enhanced CPU solver (existing FluidSim + vorticity + multi-phase).

### CLI

CPU-only. Shares palette/preset configs with browser via ES module imports.
