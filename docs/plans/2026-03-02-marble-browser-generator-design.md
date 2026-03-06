# Marble Browser Generator — Design

**Date**: 2026-03-02
**Status**: Approved

## Goal

Port the CLI marble background generator to a single self-contained HTML file with live Canvas preview and batch gallery generation.

## Architecture

Single file: `marble_generator/index.html`

- Inline all JS (simplex noise, FBM, domain warp, palette, coverage, auto-tune)
- Web Worker (inline blob) for non-blocking generation
- Canvas API for rendering (replaces `sharp`)
- Dark theme UI with grid gallery

## Bug Fixes

1. **Auto-tune overshoot** — damped corrections with decreasing step size
2. **Gold vein range** — tighten goldThreshold clamp range
3. **Transition banding** — widen smoothstep zone
4. **Seed validation** — clamp to valid positive integers

## UX

- Count input (1-50), Generate button, progress bar
- 3-4 column grid of canvas thumbnails (480x270)
- Each card: canvas + seed/coverage overlay
- Click → fullscreen lightbox, re-render at 1920x1080, download PNG
- Auto-scroll to latest

## Generation Flow

1. User sets count, clicks Generate
2. Web Worker generates at thumbnail resolution
3. Posts ImageData + metadata back to main thread
4. Main thread draws to canvas gallery
5. Click → full-res re-render in worker → download via canvas.toBlob()

## No Server Required

Pure client-side — double-click to open.
