# Fusion 360 SVG Exporter — Build Plan

**Status:** Implementation complete (Phases 1–6)

## Context

Fusion 360 Python add-in that exports design geometry as SVG files conforming to the G-Code API's SVG import specification (documented in `fusion-360-svg-spec.md`). Exported SVGs are consumed by a separate CNC toolpath generation API with zero manual editing required.

---

## Project Structure

```
/Users/eric/Documents/GitHub Repos/Fusion Exporter/
├── FusionExporter.py              # Entry point (run/stop)
├── FusionExporter.manifest        # Add-in metadata JSON
├── config.py                      # Global constants (command IDs, etc.)
├── commands/
│   ├── __init__.py                # Command registry (start/stop all)
│   └── exportSVG/
│       ├── __init__.py
│       ├── entry.py               # Command definition, dialog, event handlers
│       └── resources/
│           ├── 16x16.png          # Toolbar icons
│           ├── 32x32.png
│           └── 64x64.png
├── lib/
│   ├── __init__.py
│   ├── geometry_extractor.py      # Extract geometry from Fusion API objects
│   ├── svg_builder.py             # Assemble SVG document from geometry
│   ├── path_converter.py          # Convert Fusion curves → SVG path commands
│   └── utils.py                   # Unit conversion, logging, helpers
├── setup-dev.sh                   # One-time symlink setup for development
├── Build Prompts/
│   ├── fusion-360-svg-spec.md     # SVG format spec (the contract)
│   ├── build-plan.md              # This file
│   └── Description of how exporter should work
└── .gitignore
```

---

## Implementation Checklist

### Phase 1: Project Scaffolding & Deployment
- [x] `FusionExporter.manifest` — add-in metadata
- [x] `FusionExporter.py` — entry point with `run()`/`stop()`, `importlib.reload()` chain
- [x] `config.py` — command IDs, add-in name constants
- [x] `commands/__init__.py` — start/stop registry with sub-module reloading
- [x] `commands/exportSVG/__init__.py` and `entry.py` — "Export SVG" button in UTILITIES toolbar
- [x] Toolbar icons (16x16, 32x32, 64x64 PNGs)
- [x] `setup-dev.sh` — symlink creation script with safety checks
- [x] `.gitignore`
- [ ] **Verify:** Run setup script, load add-in in Fusion, confirm button appears

### Phase 2: Export Dialog & File Save
- [x] Body Selection input (pre-populated with current selection)
- [x] Material Thickness value input (auto-detected units)
- [x] Units dropdown: Millimeters / Inches (auto-detected from document)
- [x] `commandCreated`, `validateInputs`, `execute`, `destroy` event handlers
- [x] Input validation: positive thickness, at least one body
- [x] File save dialog (filter: SVG files)
- [ ] **Verify:** Click button, dialog opens, validates, save dialog works

### Phase 3: Geometry Extraction — BRep Faces
- [x] Intermediate geometry classes: `ExportComponent`, `ExportOperation`, `ExportContour`, `PathSegment` (LineSeg, ArcSeg, CircleSeg)
- [x] `extract_from_bodies()` — iterate bodies, find top face, extract edge loops
- [x] Top face identification: largest-area upward-facing planar face
- [x] Edge loop extraction: `face.loops` → `loop.coEdges` → edge geometry
- [x] Edge geometry conversion: Line3D → LineSeg, Arc3D → ArcSeg, Circle3D → CircleSeg, NurbsCurve3D → tessellated LineSegs
- [x] CoEdge direction handling (`isOpposedToEdge`)
- [x] Automatic operation classification: outer loop → profile, inner circular → drill, inner non-circular → profile
- [x] 3D → 2D projection: XY faces → drop Z; arbitrary faces → UV coordinate frame
- [x] Bounding box computation for layout
- [ ] **Verify:** Export a 3D body, inspect intermediate geometry

### Phase 4: SVG Generation
- [x] `path_converter.py`: line_to_svg, arc_to_svg, circle_to_element, contour_to_path_d
- [x] `svg_builder.py`: SVG document assembly with XML declaration
- [x] `<svg>` root with width/height unit suffixes
- [x] Component groups: `<g data-component="..." data-source-guid="...">`
- [x] Operation groups: `<g id="TYPE: DEPTH" data-operation="..." data-cut-depth="...">`
- [x] Fill/stroke conventions: pocket=gray, profile=black stroke, engrave=blue, drill=black fill
- [x] `utils.py`: cm_to_mm, cm_to_in, format_coord (4dp mm / 6dp in), logging
- [x] UTF-8 file output with `<?xml?>` declaration
- [ ] **Verify:** Open SVG in browser, validate against Appendix A checklist

### Phase 5: Pocket Detection & Depth Analysis
- [x] Scan planar faces parallel to and below the top face
- [x] Pocket depth = top face Z − pocket face Z
- [x] Skip faces at material thickness depth (already through-cuts)
- [x] Extract pocket face edge loops using same projection frame as top face
- [x] All pocket contours classified as `pocket` operation
- [ ] **Verify:** Part with rectangular pocket, verify depth in SVG

### Phase 6: Multi-Body Layout & Polish
- [x] Side-by-side layout with spacing between components
- [x] Canvas size computed from bounding boxes + margin
- [x] Error handling: no design, no planar faces, file write failure
- [x] Unsupported geometry: tessellated via `getStrokes()` as fallback
- [x] Progress logging to Text Commands palette
- [x] Success notification with file path + geometry summary
- [ ] **Verify:** Multi-body design export

### Phase 7 (Future): Sketch-Based Export
- [ ] `extract_from_sketch()` — iterate sketch.profiles, profileLoops, profileCurves
- [ ] Add "Active Sketch" option to export dialog

---

## Key Technical Decisions

| Decision | Approach |
|----------|----------|
| Units | Fusion cm internally → `×10` for mm, `÷2.54` for in |
| Coordinates | Standard SVG Y-down (parser handles Y-flip to CNC) |
| Arc conversion | Fusion Arc3D → SVG `A` with computed large-arc/sweep flags |
| Splines | Tessellate via `evaluator.getStrokes()` → line segments |
| Module reloading | `importlib.reload()` chain for hot-reload |
| No transforms | All coordinates baked into path data |
| One path per contour | Each edge loop = one `<path>` element |
| Toolbar placement | UTILITIES tab, Scripts/Add-ins panel |

---

## Spec Compliance Checklist (from Appendix A)

- [x] `<svg>` has width/height with unit suffix
- [x] `xmlns` present
- [x] All geometry is `<path>` or `<circle>` (no `<rect>`, `<polygon>`)
- [x] No `transform` attributes
- [x] Closed shapes end with `Z`
- [x] Component groups have `data-component` and `data-source-guid`
- [x] Operation groups have `data-operation`, `data-cut-depth`, and `id="TYPE: DEPTH"`
- [x] Circular arcs use `A` with `rx === ry`
- [x] Standard SVG Y-down coordinates
- [x] Paths connect properly (end matches next start via coEdge traversal)
- [x] Islands are separate `<path>` elements in same operation `<g>`
- [x] No CSS stylesheets — inline `fill`/`stroke` only
