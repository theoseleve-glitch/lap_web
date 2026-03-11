# Corner Editor Design Spec

**Date**: 2026-03-11
**Status**: Approved
**Replaces**: CornerPicker toggle-based selection

## Problem

The current CornerPicker only lets users toggle pre-detected corners on/off. Users want to define corner zones themselves by clicking on the track map to place entry/apex/exit points.

## Core Concept

Replace the toggle-based corner picker with a click-to-place corner editor. Auto-detected corners load silently as the default. A 15-second timer auto-proceeds if the user doesn't interact. Any map click cancels the timer and enters full manual mode.

## Interaction Flow

### Timer Phase (0-15s)

1. Page enters `awaiting_corners` state.
2. Track map renders with auto-detected corners pre-placed (entry handle, apex marker, exit handle per corner).
3. A 15s countdown bar appears at the bottom of the canvas.
4. If user doesn't touch the map within 15s, auto-proceed with detected corners.

### Edit Mode (after first click)

1. Any click on the map cancels the timer permanently.
2. "Continue Analysis" button appears.
3. User interactions:
   - **Single-click on empty track**: Places a new corner. Apex at click point, entry/exit auto-expand +/-30m along the track (snapped to track points, clamped to bounds).
   - **Drag entry/exit handles**: Adjusts zone boundaries along the track. Minimum zone ~10m.
   - **Click existing apex marker**: Deletes that corner.
   - **Click "Continue Analysis"**: Submits current corners.

### Visual Elements

- **Corner zone**: Highlighted thicker track segment, colored per corner index.
- **Apex marker**: Filled circle (8px), labeled C1, C2, etc.
- **Entry/exit handles**: Smaller circles (5px), `cursor: grab` on hover.
- **Timer bar**: Thin bar at canvas bottom, drains left-to-right over 15s.
- **Ghost preview**: Faint preview circle on hover over empty track.
- **Corner chips**: Below map, show placed corners. Click chip to delete.
- **Reset button**: "Reset to Auto-detected" restores pipeline corners.

### Direction

Determined by the pipeline during analysis from track curvature, not by the editor.

## Data Flow Changes

### Frontend to Backend (new format)

```json
{
  "corners": [
    { "s_start": 120.5, "s_apex": 145.0, "s_end": 170.2 },
    { "s_start": 310.0, "s_apex": 340.0, "s_end": 365.0 }
  ]
}
```

### Backend resume endpoint

Accept both formats for backwards compat:
- `selected_corner_ids: int[]` — legacy, filter auto-detected corners.
- `corners: [{s_start, s_apex, s_end}]` — new, use directly, skip auto-detected.

### Pipeline finalize

When `corners` array is provided, use it as-is. Enrich with lat/lon/direction from track geometry. When `selected_corner_ids` is provided, filter as before.

## Component Structure

### CornerEditor.tsx (new, replaces CornerPicker.tsx)

Same canvas projection/rendering as CornerPicker. New state and interactions:

```typescript
interface EditorCorner {
  id: string;           // Unique ID (crypto.randomUUID or sequential)
  s_start: number;      // Distance along track (meters) — entry
  s_apex: number;       // Distance along track (meters) — apex
  s_end: number;        // Distance along track (meters) — exit
  idxStart: number;     // Index into downsampled track arrays
  idxApex: number;
  idxEnd: number;
}

type EditorMode = 'timer' | 'editing';
```

State machine:
- `timer` → Auto-detected corners shown, 15s countdown active.
- `editing` → Timer cancelled, user has full control.

Interactions:
- `mousedown` on handle → start drag (track `dragTarget: {cornerId, handle: 'start'|'end'}`)
- `mousemove` while dragging → update handle position (snap to nearest track point)
- `mouseup` → commit drag
- `click` on empty track → place new corner
- `click` on apex → delete corner

### Upload page changes

- Swap `<CornerPicker>` for `<CornerEditor>`.
- `onSubmit` receives `EditorCorner[]` instead of `number[]`.
- `handleCornerSubmit` sends `{ corners: [...] }` instead of `{ selected_corner_ids: [...] }`.

### Backend changes

- `web/schemas/jobs.py`: Add `corners` field to `ResumeJobSchema` (list of `{s_start, s_apex, s_end}`).
- `web/routes/jobs.py`: Pass `corners` to pipeline context when provided.
- `pipeline_context.py`: Add `set_custom_corners()` / `custom_corners` property.
- `tasks/pipeline_tasks.py`: In `_run_finalize_stages()`, use custom corners if set, otherwise filter by selected_corner_ids, otherwise use all detected.

## What stays the same

- Track map rendering (projection, speed coloring, grid, S/F marker).
- Canvas-based approach (no Leaflet/tiles).
- The `extract_track_layout_for_picker()` backend helper.
- The track-layout API endpoint.
- The SSE job tracking flow.

## Out of scope

- Corner type classification in the editor (hairpin, chicane, etc.)
- Undo/redo stack
- Saving corner templates per track
- Multi-lap corner comparison in the editor
