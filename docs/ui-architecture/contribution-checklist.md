# UI Contribution Checklist

Use this checklist when adding new pages, components, or modifying existing UI.

## Tokens

- [ ] All colors reference `tokens.css` variables (no hardcoded hex values)
- [ ] All spacing uses `--space-N` tokens (no raw `px` or `rem` for margins/padding)
- [ ] All border-radius uses `--radius-*` tokens
- [ ] All shadows use `--shadow-*` tokens
- [ ] All z-index values use `--z-*` tokens

## Responsive

- [ ] Fluid tokens (`clamp()`) handle typography and spacing
- [ ] Explicit breakpoints only for layout shifts (768px, 1280px)
- [ ] Tested at 360px, 768px, and 1920px viewports

## Accessibility

- [ ] All interactive elements have `min-height: var(--touch-min)` (44px)
- [ ] Text/background contrast meets WCAG 2.2 AA (4.5:1 for normal text, 3:1 for large)
- [ ] Charts wrapped in `.chart-frame` with `role="img"` and `aria-label`
- [ ] Form inputs have associated labels
- [ ] Focus visible on all interactive elements (`:focus-visible` ring)
- [ ] `prefers-reduced-motion` respected (use token durations, not raw values)

## States

- [ ] Loading state: use `.skeleton` classes or `ChartFrame.setState('loading')`
- [ ] Empty state: use `.empty-hero` or `.no-data` patterns
- [ ] Error state: use `.error-state` or `.fetch-error` patterns
- [ ] All three states tested (not just the happy path)

## Performance

- [ ] No inline styles in templates (use utility classes or CSS rules)
- [ ] No CSS variable fallbacks (`var(--token)` not `var(--token, #hex)`)
- [ ] Canvas charts read colors from `Theme.colors`, not hardcoded
- [ ] Bundle size tests pass (`pytest telemetry_tool/tests/performance/`)

## Module Lifecycle

- [ ] JS modules register with `ModuleManager.register(name, { init, destroy })`
- [ ] `destroy()` cleans up event listeners, intervals, and DOM modifications
- [ ] No global state leaks between page navigations
