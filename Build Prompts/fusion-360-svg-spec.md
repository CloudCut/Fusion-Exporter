# Fusion 360 SVG Export Specification

**For: G-Code API SVG Importer Compatibility**
**Version:** 1.0
**Last Updated:** 2026-02-15

This document specifies the SVG format consumed by the G-Code API's SVG import pipeline. A Fusion 360 add-in that exports SVGs conforming to this spec will produce files the API can parse into CNC toolpath operations with zero manual editing.

The G-Code API parser lives in a separate codebase. This document is fully self-contained — you do not need access to that codebase to implement a conforming exporter.

---

## Table of Contents

1. [SVG Envelope](#1-svg-envelope)
2. [Supported SVG Elements](#2-supported-svg-elements)
3. [Custom Data Attributes](#3-custom-data-attributes)
4. [Group ID Encoding](#4-group-id-encoding)
5. [SVG Path `d` Attribute](#5-svg-path-d-attribute)
6. [Open vs Closed Paths](#6-open-vs-closed-paths)
7. [Internal Geometry Types](#7-internal-geometry-types)
8. [Component Grouping](#8-component-grouping)
9. [Operation Type Inference](#9-operation-type-inference)
10. [Coordinate System](#10-coordinate-system)
11. [Units](#11-units)
12. [Multiple Contours and Islands](#12-multiple-contours-and-islands)
13. [Validation Requirements](#13-validation-requirements)
14. [Fusion 360 Mapping Guidance](#14-fusion-360-mapping-guidance)
15. [Annotated Example SVGs](#15-annotated-example-svgs)

---

## 1. SVG Envelope

The `<svg>` root element must declare `width` and `height` with explicit unit suffixes.

### Required Attributes

| Attribute | Required | Example | Notes |
|-----------|----------|---------|-------|
| `width`   | Yes      | `"200mm"` or `"8in"` | Must include unit suffix |
| `height`  | Yes      | `"150mm"` or `"6in"` | Must include unit suffix |
| `xmlns`   | Yes      | `"http://www.w3.org/2000/svg"` | Standard SVG namespace |
| `viewBox` | No       | `"0 0 200 150"` | Harmless if present, but ignored by the parser |

### Example

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="150mm">
  <!-- geometry here -->
</svg>
```

### Unit Detection

The parser reads `width` and `height` as strings and checks for unit suffixes:

| Suffix | Interpretation | Scale Factor |
|--------|---------------|--------------|
| `mm`   | Millimeters   | 1 / 25.4 (converts to inches internally) |
| `in`   | Inches        | 1.0 (native unit) |
| _(none)_ | Pixels at 90 PPI | 1 / 90 (90 px = 1 inch) |

**Best practice:** Always include `mm` or `in` on both `width` and `height`. Bare numbers default to 90 PPI pixels, which is rarely what you want from a CAD export.

The unit suffix is detected by checking if the width string contains `"mm"` or `"in"`. The parser checks the `width` attribute first; `height` is not independently checked for a different unit.

---

## 2. Supported SVG Elements

### Fully Supported

| Element | Usage | Notes |
|---------|-------|-------|
| `<path>` | Primary geometry carrier | All shapes should be expressed as paths |
| `<circle>` | Circular holes and pockets | Auto-converted to an arc-based path internally |
| `<g>` | Grouping for components and operations | Supports unlimited nesting depth |

### Not Supported

The parser will silently ignore these elements — they will not produce toolpath geometry:

- `<rect>`, `<polygon>`, `<polyline>`, `<ellipse>`, `<line>`
- `<text>`, `<image>`
- `<use>`, `<defs>`, `<symbol>`, `<clipPath>`, `<mask>`
- CSS `<style>` blocks (inline `fill`/`stroke` attributes are fine)
- `transform` attributes on any element (transforms are not applied)

**Important:** The exporter must convert all geometry to `<path>` elements (or `<circle>` for circles). Do not emit `<rect>` for rectangles — emit a `<path>` with the rectangle's corner coordinates instead. Do not use `transform` attributes; bake all transformations into the path coordinates.

### Circle Handling

When the parser encounters a `<circle cx="50" cy="50" r="10">`, it internally converts it to:

```
M40,50 A10,10 0 1,0 60,50 A10,10 0 1,0 40,50 Z
```

Two 180-degree arcs forming a complete circle. The exporter may emit either `<circle>` or the equivalent `<path>` — both work.

---

## 3. Custom Data Attributes

These attributes can appear on `<path>`, `<circle>`, or `<g>` elements. They provide explicit metadata that overrides visual-style inference.

### Supported Attributes

| Attribute | Values | Appears On | Purpose |
|-----------|--------|------------|---------|
| `data-operation` | `"pocket"`, `"profile"`, `"engrave"`, `"drill"` | `<path>`, `<circle>`, `<g>` | Explicit operation type (highest priority) |
| `data-cut-depth` | Decimal number (e.g., `"0.25"`) | `<path>`, `<circle>`, `<g>` | Cut depth in SVG document units |
| `data-component` | String (e.g., `"Base Plate"`) | `<g>` (outer wrapper) | Component/body name for grouping |
| `data-source-guid` | UUID string | `<g>` (outer wrapper) | Unique ID for the source object (Fusion component occurrence ID) |

### Attribute Inheritance

Attributes cascade from parent `<g>` to child elements:

1. **`data-operation`** on a `<path>` overrides `data-operation` on its parent `<g>`
2. **`data-cut-depth`** on a `<path>` overrides `data-cut-depth` on its parent `<g>`
3. If a `<path>` has no `data-cut-depth`, the parser checks its parent `<g>` for `data-cut-depth`
4. If a `<path>` has no `data-operation`, the parser checks its parent `<g>` for `data-operation`

### Legacy Aliases

The parser also accepts these unprefixed variants (for backward compatibility with older exporters):

- `operation` (alias for `data-operation`)
- `cut-depth` (alias for `data-cut-depth`)

**Recommendation:** Use the `data-` prefixed forms. They are HTML5-compliant and preferred.

### Example

```xml
<path d="M10,10 L90,10 L90,90 L10,90 Z"
      data-operation="pocket"
      data-cut-depth="3.0"
      fill="gray" stroke="none"/>
```

---

## 4. Group ID Encoding

As an alternative (or supplement) to data attributes, operation type and cut depth can be encoded in the `id` attribute of a `<g>` element.

### Format

```
id="OPERATION_TYPE: DEPTH_VALUE"
```

### Regex Pattern

The parser matches group IDs against this exact regex:

```regex
/^(PROFILE|POCKET|ENGRAVE|DRILL):\s*([0-9.]+)$/i
```

### Examples

| Group ID | Parsed Operation | Parsed Depth |
|----------|-----------------|--------------|
| `PROFILE: 0.5` | profile | 0.5 |
| `POCKET: 0.25` | pocket | 0.25 |
| `ENGRAVE: 0.1` | engrave | 0.1 |
| `DRILL: 6.0` | drill | 6.0 |
| `pocket: 3.175` | pocket | 3.175 |

### Rules

- Case-insensitive (`POCKET`, `pocket`, `Pocket` all work)
- The colon is required: `POCKET 0.25` (no colon) will **not** match. Space after the colon is optional (`POCKET:0.25` and `POCKET: 0.25` both work)
- The depth value must be a positive decimal number
- This encoding only works on `<g>` elements, not on `<path>` directly
- When both a group ID pattern and `data-operation`/`data-cut-depth` attributes are present, the explicit data attributes take priority on the child paths

### Example

```xml
<g id="POCKET: 0.25">
  <path d="M10,10 L90,10 L90,90 L10,90 Z" fill="gray"/>
  <path d="M30,30 L70,30 L70,70 L30,70 Z" fill="gray"/>
</g>
```

Both paths inherit `operation=pocket` and `cutDepth=0.25` from the group ID.

---

## 5. SVG Path `d` Attribute

### Supported Commands

All standard SVG path commands are supported, in both absolute (uppercase) and relative (lowercase) forms:

| Command | Name | Parameters | Notes |
|---------|------|-----------|-------|
| `M` / `m` | Move To | `x,y` | Sets current point; starts a new subpath |
| `L` / `l` | Line To | `x,y` | Straight line segment |
| `H` / `h` | Horizontal Line | `x` | Horizontal line (Y unchanged) |
| `V` / `v` | Vertical Line | `y` | Vertical line (X unchanged) |
| `C` / `c` | Cubic Bezier | `x1,y1 x2,y2 x,y` | Flattened to line segments |
| `S` / `s` | Smooth Cubic | `x2,y2 x,y` | Reflects previous control point; flattened |
| `Q` / `q` | Quadratic Bezier | `x1,y1 x,y` | Flattened to line segments |
| `T` / `t` | Smooth Quadratic | `x,y` | Reflects previous control point; flattened |
| `A` / `a` | Elliptical Arc | `rx,ry rotation large-arc sweep x,y` | See arc handling below |
| `Z` / `z` | Close Path | _(none)_ | Draws line back to subpath start |

### Coordinate Format

- Decimal numbers: `10`, `10.5`, `-3.14`, `.5`
- Separators: comma or whitespace (both work)
- Implicit line-to after `M`: `M10,10 20,20 30,10` is `M10,10 L20,20 L30,10`

### Bezier Curve Handling

All Bezier curves (C, S, Q, T) are **flattened to line segments** using adaptive De Casteljau subdivision:

- **Tolerance:** 0.001 inches (squared tolerance = 0.000001)
- **Max recursion depth:** 10 levels
- The flattened result is a series of short `line` segments that approximate the curve
- This means the downstream toolpath sees only lines and arcs — no splines

**Exporter guidance:** Feel free to emit Bezier curves for rounded or freeform geometry. They will be faithfully flattened. However, for simple straight edges and circular arcs, prefer `L` and `A` commands respectively — they produce cleaner geometry.

### Arc Handling

The SVG `A` command parameters: `rx ry x-rotation large-arc-flag sweep-flag x y`

- **Circular arcs** (`rx === ry`): Preserved as native arc geometry elements with center, radius, and direction. These produce the best CNC output (G02/G03 commands).
- **Elliptical arcs** (`rx !== ry`): Flattened to line segments (CNC machines cannot cut true ellipses). A console warning is emitted.

**Exporter guidance:** Use circular arcs (`A r,r ...`) wherever possible. For Fusion 360 sketch geometry that contains true circles and arcs, emit them as SVG `A` commands with equal `rx` and `ry`.

### Multiple Subpaths

A single `<path>` element may contain multiple subpaths (multiple `M` commands). The parser splits these into separate geometry objects. Subpaths with a bounding box area less than **0.01 square inches** are filtered out as noise.

**Exporter guidance:** Prefer one `<path>` element per contour. If you do combine subpaths, know that they will be split and processed independently.

---

## 6. Open vs Closed Paths

Path closure determines the default operation type when no explicit `data-operation` is specified.

### How Closure Is Detected

A path is considered **closed** if either:

1. The `d` string ends with a `Z` or `z` command, OR
2. The final endpoint is within **0.001 inches** of the start point (implicit closure)

### Closure and Operation Defaults

| Path Type | Detection | Default Operation |
|-----------|-----------|-------------------|
| Closed + filled | Ends with `Z`, has `fill` | **Pocket** |
| Closed + stroke only | Ends with `Z`, `fill="none"` | **Profile** |
| Closed + no style | Ends with `Z` | **Profile** |
| Open | No `Z`, endpoint far from start | **Engrave** |

### Exporter Guidance

- **Always use `Z`** to close paths that represent closed shapes (profiles, pockets, holes)
- Do not rely on implicit closure (endpoint matching start) — use an explicit `Z`
- Open paths (engravings, V-carve text strokes) should **not** have a `Z`

---

## 7. Internal Geometry Types

This section describes what the parser produces internally. Understanding these types helps you structure your SVG output for optimal results.

### `complex_path`

The primary geometry type. An array of connected elements forming a path.

```
{
  type: "complex_path",
  elements: [
    { type: "line", start: {x, y}, end: {x, y} },
    { type: "arc",  start: {x, y}, end: {x, y}, center: {x, y},
                    radius: Number, clockwise: Boolean, largeArc: Boolean }
  ],
  closed: Boolean,
  depth: Number
}
```

- `elements` are ordered and connected: `elements[n].end` matches `elements[n+1].start`
- `closed: true` means the last element's end matches the first element's start
- `depth` is the cut depth in inches (after unit conversion)

### `circle`

Auto-detected when a path is a `<circle>` element or is recognized as a circle from arc geometry.

```
{
  type: "circle",
  center: { x, y },
  radius: Number,
  depth: Number
}
```

### `rectangle`

Auto-detected from a `complex_path` that meets all of these criteria:
- Exactly **4 line elements** (no arcs)
- Path is **closed**
- All 4 corners align to exactly **2 unique X values** and **2 unique Y values** (orthogonal edges)
- Corner positions match within **0.001 inch** tolerance

```
{
  type: "rectangle",
  center: { x, y },
  width: Number,
  height: Number,
  depth: Number
}
```

Rectangle detection is automatic — the exporter does not need to flag rectangles specially. Just emit a closed 4-segment path with orthogonal edges.

---

## 8. Component Grouping

The SVG should use a two-level `<g>` nesting structure to organize geometry by component and operation.

### Structure

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="150mm">

  <!-- Component 1 -->
  <g data-component="Base Plate" id="component-1" data-source-guid="abc-123-def">

    <!-- Operation group: profile cut at 6mm depth -->
    <g id="PROFILE: 6.0" data-operation="profile" data-cut-depth="6.0">
      <path d="M0,0 L200,0 L200,150 L0,150 Z" stroke="black" fill="none"/>
    </g>

    <!-- Operation group: pocket at 3mm depth -->
    <g id="POCKET: 3.0" data-operation="pocket" data-cut-depth="3.0">
      <path d="M20,20 L80,20 L80,60 L20,60 Z" fill="gray" stroke="none"/>
    </g>

    <!-- Operation group: drill holes -->
    <g id="DRILL: 6.0" data-operation="drill" data-cut-depth="6.0">
      <circle cx="10" cy="10" r="2.5" fill="black"/>
      <circle cx="190" cy="10" r="2.5" fill="black"/>
    </g>

  </g>

  <!-- Component 2 -->
  <g data-component="Side Panel" id="component-2" data-source-guid="ghi-456-jkl">
    <g id="PROFILE: 6.0" data-operation="profile" data-cut-depth="6.0">
      <path d="M0,0 L100,0 L100,80 L0,80 Z" stroke="black" fill="none"/>
    </g>
  </g>

</svg>
```

### Layer Descriptions

| Level | Element | Attributes | Purpose |
|-------|---------|------------|---------|
| Outer `<g>` | Component wrapper | `data-component`, `id`, `data-source-guid` | One per Fusion body or component |
| Inner `<g>` | Operation wrapper | `id` (encoded), `data-operation`, `data-cut-depth` | Groups paths by operation type + depth |
| Leaf | `<path>` or `<circle>` | `d`, `fill`, `stroke` | Actual geometry |

### Flat Format (Also Supported)

If component grouping is not needed, a simpler flat structure also works:

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="150mm">
  <g id="PROFILE: 6.0">
    <path d="M0,0 L200,0 L200,150 L0,150 Z" stroke="black" fill="none"/>
  </g>
  <g id="POCKET: 3.0">
    <path d="M20,20 L80,20 L80,60 L20,60 Z" fill="gray" stroke="none"/>
  </g>
</svg>
```

---

## 9. Operation Type Inference

The parser determines operation type using a priority chain. Higher-priority signals override lower ones.

### Priority Order (Highest to Lowest)

| Priority | Source | Confidence | Example |
|----------|--------|------------|---------|
| 1 | `data-operation` attribute on `<path>` | ~100% | `data-operation="pocket"` |
| 2 | `data-operation` attribute on parent `<g>` | ~100% | `<g data-operation="pocket">` |
| 3 | Group `id` regex match | ~100% | `<g id="POCKET: 0.25">` |
| 4 | `fill` present and not `"none"` / `"transparent"` | ~70% | `fill="gray"` → pocket |
| 5 | `stroke` present, `fill` is `"none"` or absent | ~70% | `stroke="black" fill="none"` → profile |
| 6 | Closed path (has `Z`) | ~50% | Defaults to **profile** |
| 7 | Open path (no `Z`) | ~50% | Defaults to **engrave** |

### Confidence Scoring

The parser also calculates a confidence score (0.0–1.0) for each operation:

| Condition | Confidence Boost |
|-----------|-----------------|
| Has explicit `data-operation` | +0.3 |
| Has explicit `data-cut-depth` | +0.2 |
| Has meaningful `fill` | +0.1 |
| Has meaningful `stroke` | +0.1 |
| Base | 0.5 |

Operations with confidence below 0.5 may prompt the user for manual confirmation in the UI.

### Exporter Guidance

**Always set `data-operation` and `data-cut-depth` explicitly.** This gives 100% confidence and removes all ambiguity. Use `fill`/`stroke` as visual hints for human readability, but do not rely on them as the sole operation signal.

Recommended fill/stroke conventions (for visual consistency):

| Operation | Fill | Stroke |
|-----------|------|--------|
| Pocket | `"gray"` or any color | `"none"` |
| Profile | `"none"` | `"black"` |
| Engrave | `"none"` | `"blue"` |
| Drill | `"black"` | `"none"` |

---

## 10. Coordinate System

### SVG vs CNC Coordinate Systems

| System | X Direction | Y Direction | Origin |
|--------|-------------|-------------|--------|
| SVG (standard) | Right (+X) | **Down** (+Y) | Top-left |
| CNC / G-code | Right (+X) | **Up** (+Y) | Bottom-left |

### Y-Axis Flip

The G-Code API performs a Y-axis flip internally when converting SVG coordinates to CNC coordinates:

```
y_cnc = (svgHeight * scaleFactor) - y_svg
```

where `svgHeight` is the `height` attribute value and `scaleFactor` converts SVG units to inches.

### What This Means for the Exporter

**Output standard SVG coordinates (Y-down).** Do NOT pre-flip Y values. The parser expects:

- Y = 0 at the **top** of the workpiece
- Y increases **downward**
- The parser handles the flip to CNC coordinates (Y-up) automatically

If you pre-flip Y values, the resulting toolpath will be mirrored vertically.

### Arc Direction During Y-Flip

When the Y-axis is flipped, arc sweep directions are inverted internally:

```
clockwise_cnc = !clockwise_svg
```

The exporter should use standard SVG arc conventions:
- `sweep-flag = 0` → counterclockwise in SVG (Y-down) space
- `sweep-flag = 1` → clockwise in SVG (Y-down) space

The parser will invert these when converting to CNC coordinates.

---

## 11. Units

### Unit System

The G-Code API works internally in **inches**. All SVG coordinates are scaled to inches during import.

### How Units Are Determined

The parser reads the `width` attribute string and checks for unit suffixes:

```
"200mm"  →  unit = mm,  scaleFactor = 1/25.4 = 0.03937
"8in"    →  unit = in,  scaleFactor = 1.0
"720"    →  unit = px,  scaleFactor = 1/90 = 0.01111
```

### Coordinate Interpretation

All numeric values in the SVG (path coordinates, circle cx/cy/r, data-cut-depth) are interpreted in the detected unit:

```xml
<!-- If width="200mm", then all coordinates are in mm -->
<svg width="200mm" height="150mm">
  <!-- This path is 100mm x 80mm -->
  <path d="M10,10 L110,10 L110,90 L10,90 Z" data-cut-depth="3.0"/>
  <!-- cut-depth is 3.0mm -->
</svg>
```

```xml
<!-- If width="8in", then all coordinates are in inches -->
<svg width="8in" height="6in">
  <!-- This path is 4" x 3" -->
  <path d="M1,1 L5,1 L5,4 L1,4 Z" data-cut-depth="0.125"/>
  <!-- cut-depth is 0.125" -->
</svg>
```

### Best Practice

- Always include explicit units: `width="200mm" height="150mm"`
- Use the same unit on both `width` and `height`
- Use `mm` for metric Fusion 360 documents, `in` for imperial
- `data-cut-depth` values should be in the same unit as the SVG dimensions

---

## 12. Multiple Contours and Islands

### Pockets with Interior Holes

When a pocket has interior cutouts (islands), export the outer boundary and inner holes as **separate `<path>` elements** within the same operation `<g>` group.

```xml
<g id="POCKET: 3.0" data-operation="pocket" data-cut-depth="3.0">
  <!-- Outer boundary (larger area, will be detected as container) -->
  <path d="M10,10 L190,10 L190,140 L10,140 Z" fill="gray"/>

  <!-- Inner hole (smaller area, will be detected as island) -->
  <path d="M50,40 L80,40 L80,70 L50,70 Z" fill="gray"/>

  <!-- Another inner hole -->
  <path d="M120,60 L160,60 L160,100 L120,100 Z" fill="gray"/>
</g>
```

### How the Parser Detects Nesting

The parser uses **spatial containment analysis** after parsing:

1. Sorts closed operations by bounding box area (largest first)
2. For each operation, checks if its vertices are contained within larger operations
3. Uses a **ray-casting point-in-polygon** test
4. If >=50% of a path's vertices are inside another path, it is considered contained
5. Nesting depth determines `profileSide`:
   - Depth 0 (outermost) → `profileSide: "outside"` → tool offsets **left**
   - Depth 1 (first island) → `profileSide: "inside"` → tool offsets **right**
   - Depth 2 → `profileSide: "outside"` (even-odd rule)
6. Inner paths are machined before outer paths automatically

### Exporter Guidance

- Export each contour as a separate `<path>` element — do NOT combine outer and inner contours into a single `<path>` with multiple subpaths (multiple `M` commands)
- Group related contours (outer + inner) in the same operation `<g>`
- Winding direction does not matter — the parser uses spatial containment, not winding rules

---

## 13. Validation Requirements

### Path Connectivity

Path elements must be connected end-to-start:

```
element[0].end ≈ element[1].start   (within 0.001")
element[1].end ≈ element[2].start   (within 0.001")
...
```

For closed paths, the final element's end must match the first element's start (within 0.001").

When the parser encounters a `Z` command and the current position is not at the start position, it automatically inserts a closing line segment.

### Degenerate Segment Filtering

Line segments shorter than **0.0001 inches** (~0.003mm) are automatically filtered out. However, the exporter should avoid generating them — they indicate precision issues.

### Minimum Path Area

When a `<path>` contains multiple subpaths (multiple `M` commands), subpaths with a bounding box area less than **0.01 square inches** (~6.5 sq mm) are filtered out as noise. This prevents tiny decorative fragments from creating unwanted operations.

Single-path `<path>` elements are not subject to this filter.

### Numeric Precision

- Use at least **4 decimal places** for coordinates in millimeters (0.001mm precision)
- Use at least **6 decimal places** for coordinates in inches (0.000001" precision)
- Avoid scientific notation (`1e-3`) — use decimal form (`0.001`)

### Attribute Value Format

- `data-cut-depth`: Positive decimal number as a string, no units suffix (e.g., `"3.0"`, not `"3.0mm"`)
- `data-operation`: Lowercase string, one of `"pocket"`, `"profile"`, `"engrave"`, `"drill"`
- `data-component`: Any non-empty string
- `data-source-guid`: Any non-empty string (recommend UUID format)

---

## 14. Fusion 360 Mapping Guidance

This section maps Fusion 360 API objects to SVG output structures.

### Fusion Object → SVG Element Mapping

| Fusion 360 Object | SVG Output | Notes |
|-------------------|------------|-------|
| **Component** | `<g data-component="name">` | Outer grouping wrapper |
| **Component Occurrence** | `data-source-guid` on component `<g>` | Use `occurrence.entityToken` |
| **Body** | `<g data-component="body-name">` | One component group per body |
| **Sketch Profile** | `<path d="...">` | Export sketch curves directly as SVG path |
| **Sketch Circle** | `<circle>` or `<path>` with arcs | Either form works |
| **BRep Face (planar)** | `<path d="...">` | Project face edge loops to XY plane |
| **BRep Edge (circular)** | `A rx,ry ...` arc command | Preserve as circular arc |
| **BRep Edge (linear)** | `L x,y` line command | Straight line segment |
| **BRep Edge (spline)** | `C x1,y1 x2,y2 x,y` | Cubic Bezier; will be flattened by parser |
| **Manufacturing Setup** | — | Not represented in SVG (handled by API) |

### Extracting 2D Geometry from Fusion

#### Option A: From Sketches

If the Fusion design uses sketches (2D profiles):

1. Iterate over `sketch.profiles`
2. For each profile, iterate over `profile.profileLoops`
3. For each loop, iterate over `loop.profileCurves`
4. Convert each curve (line, arc, spline) to SVG path commands
5. Close the path with `Z`

#### Option B: From 3D Bodies (Face Projection)

If exporting from 3D bodies:

1. Select the relevant face (typically the top or bottom face of a flat part)
2. Get the face's edge loops: `face.loops`
3. For each loop, iterate over `loop.edges`
4. For each edge, get the 3D curve: `edge.geometry`
5. Project the curve to the XY plane (drop the Z coordinate)
6. Convert to SVG path commands
7. Close the path with `Z`

The outer loop is the face boundary; inner loops are holes/cutouts.

#### Operation Assignment

For each exported path group, determine the operation:

| Fusion Scenario | SVG Operation | How to Determine |
|-----------------|--------------|------------------|
| Through-cut outer profile | `profile` | Cut depth = material thickness |
| Pocket (partial depth) | `pocket` | Cut depth < material thickness |
| Through hole (circular) | `drill` | Circular, cut depth = material thickness |
| Blind hole | `pocket` | Circular, cut depth < material thickness |
| Engraving / V-carve | `engrave` | Open path or very shallow depth |
| Slot (elongated pocket) | `pocket` | Closed path, partial depth |

### Handling Multiple Bodies

If a Fusion design has multiple bodies that represent separate flat parts (e.g., a box with panels):

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="500mm" height="400mm">
  <g data-component="Top Panel" data-source-guid="...">
    <!-- Top panel geometry -->
  </g>
  <g data-component="Side Panel Left" data-source-guid="...">
    <!-- Side panel geometry, positioned to the right of top panel -->
  </g>
  <g data-component="Side Panel Right" data-source-guid="...">
    <!-- ... -->
  </g>
</svg>
```

Each body should be laid out in 2D (flat, no overlap) within the SVG canvas. The `width` and `height` of the SVG should encompass all bodies.

---

## 15. Annotated Example SVGs

### Example 1: Minimal — Single Profile Path

A simple rectangular cutout, 100mm x 60mm, cut through 6mm material.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="120mm" height="80mm">
  <g data-component="Simple Part" id="component-1" data-source-guid="fusion-token-001">
    <g id="PROFILE: 6.0" data-operation="profile" data-cut-depth="6.0">
      <path d="M10,10 L110,10 L110,70 L10,70 Z"
            stroke="black" fill="none"/>
    </g>
  </g>
</svg>
```

**What the parser produces:**
- 1 component: "Simple Part"
- 1 operation: profile, depth 6.0mm (converted to ~0.236")
- Geometry: rectangle (auto-detected from 4 orthogonal lines), closed
- Confidence: 1.0 (explicit data-operation + data-cut-depth)

---

### Example 2: Moderate — Profile + Pocket + Drill Holes

A plate with an outer profile, a rectangular pocket, and two mounting holes.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="160mm" height="100mm">
  <g data-component="Mounting Plate" id="component-1"
     data-source-guid="fusion-token-002">

    <!-- Outer profile: cut through 6mm material -->
    <g id="PROFILE: 6.0" data-operation="profile" data-cut-depth="6.0">
      <path d="M10,10 L150,10 L150,90 L10,90 Z"
            stroke="black" fill="none"/>
    </g>

    <!-- Rectangular pocket: 3mm deep -->
    <g id="POCKET: 3.0" data-operation="pocket" data-cut-depth="3.0">
      <path d="M40,30 L120,30 L120,70 L40,70 Z"
            fill="gray" stroke="none"/>
    </g>

    <!-- Drill holes: through at 6mm -->
    <g id="DRILL: 6.0" data-operation="drill" data-cut-depth="6.0">
      <circle cx="25" cy="50" r="3.0" fill="black" stroke="none"/>
      <circle cx="135" cy="50" r="3.0" fill="black" stroke="none"/>
    </g>

  </g>
</svg>
```

**What the parser produces:**
- 1 component: "Mounting Plate"
- 4 operations:
  - Profile of outer rectangle, depth 6.0mm
  - Pocket of inner rectangle, depth 3.0mm
  - Drill at (25, 50), radius 3.0mm, depth 6.0mm
  - Drill at (135, 50), radius 3.0mm, depth 6.0mm

---

### Example 3: Full — Multi-Component with Islands and Arcs

A two-part design with varying depths, rounded corners, and interior holes.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="300mm" height="200mm">

  <!-- Component 1: Base plate with pocket and mounting holes -->
  <g data-component="Base Plate" id="component-1"
     data-source-guid="fusion-token-010">

    <!-- Outer profile with rounded corners (6mm radius) -->
    <g id="PROFILE: 10.0" data-operation="profile" data-cut-depth="10.0">
      <path d="M16,10 L184,10
               A6,6 0 0,1 190,16
               L190,134
               A6,6 0 0,1 184,140
               L16,140
               A6,6 0 0,1 10,134
               L10,16
               A6,6 0 0,1 16,10 Z"
            stroke="black" fill="none"/>
    </g>

    <!-- Pocket with island (interior hole stays raised) -->
    <g id="POCKET: 5.0" data-operation="pocket" data-cut-depth="5.0">
      <!-- Outer pocket boundary -->
      <path d="M30,25 L170,25 L170,125 L30,125 Z"
            fill="gray" stroke="none"/>
      <!-- Island (hole in pocket — material left standing) -->
      <path d="M80,55 L120,55 L120,95 L80,95 Z"
            fill="gray" stroke="none"/>
    </g>

    <!-- Mounting holes: 4 corners -->
    <g id="DRILL: 10.0" data-operation="drill" data-cut-depth="10.0">
      <circle cx="25" cy="25" r="2.5" fill="black"/>
      <circle cx="175" cy="25" r="2.5" fill="black"/>
      <circle cx="25" cy="125" r="2.5" fill="black"/>
      <circle cx="175" cy="125" r="2.5" fill="black"/>
    </g>

  </g>

  <!-- Component 2: Cover plate (simpler, offset to the right) -->
  <g data-component="Cover Plate" id="component-2"
     data-source-guid="fusion-token-011">

    <!-- Outer profile -->
    <g id="PROFILE: 3.0" data-operation="profile" data-cut-depth="3.0">
      <path d="M210,30 L290,30 L290,120 L210,120 Z"
            stroke="black" fill="none"/>
    </g>

    <!-- Engraved label (open path — no Z) -->
    <g id="ENGRAVE: 0.5" data-operation="engrave" data-cut-depth="0.5">
      <path d="M220,75 L240,75 L240,60 L260,90 L280,60"
            stroke="blue" fill="none"/>
    </g>

  </g>

</svg>
```

**What the parser produces:**
- 2 components: "Base Plate" and "Cover Plate"
- Operations for Base Plate:
  - Profile: rounded rectangle with 4 arcs (6mm radius corners), depth 10mm
  - Pocket: outer rectangle with 1 island (inner rectangle detected via containment analysis, gets `profileSide: "inside"`)
  - 4 drill operations at the corner positions
- Operations for Cover Plate:
  - Profile: simple rectangle, depth 3mm
  - Engrave: open zigzag path (no `Z`), depth 0.5mm

---

## Appendix A: Quick Reference Checklist

Use this checklist when building or testing the Fusion 360 SVG exporter:

- [ ] `<svg>` has `width` and `height` with `mm` or `in` suffix
- [ ] `xmlns="http://www.w3.org/2000/svg"` is present
- [ ] All geometry is `<path>` or `<circle>` elements (no `<rect>`, `<polygon>`, etc.)
- [ ] No `transform` attributes anywhere (coordinates are pre-transformed)
- [ ] Closed shapes end with `Z`
- [ ] Each component is wrapped in `<g data-component="..." data-source-guid="...">`
- [ ] Each operation group has `data-operation` and `data-cut-depth`
- [ ] Group IDs follow `"TYPE: DEPTH"` format (e.g., `"POCKET: 3.0"`)
- [ ] Circular arcs use `A` with `rx === ry`
- [ ] Coordinates are in standard SVG Y-down orientation (not pre-flipped)
- [ ] `data-cut-depth` values are in the SVG document's unit (no unit suffix on the value)
- [ ] Paths connect properly: each segment's end matches the next segment's start
- [ ] Islands/holes are separate `<path>` elements in the same operation `<g>`
- [ ] No CSS stylesheets — use inline `fill`/`stroke` attributes

## Appendix B: Attribute Reference (Alphabetical)

| Attribute | Element | Value | Purpose |
|-----------|---------|-------|---------|
| `cx` | `<circle>` | Number | Circle center X coordinate |
| `cy` | `<circle>` | Number | Circle center Y coordinate |
| `d` | `<path>` | Path string | SVG path data (M, L, A, Z, etc.) |
| `data-component` | `<g>` | String | Component/body name |
| `data-cut-depth` | `<g>`, `<path>`, `<circle>` | Decimal string | Cut depth in document units |
| `data-operation` | `<g>`, `<path>`, `<circle>` | `pocket\|profile\|engrave\|drill` | Operation type |
| `data-source-guid` | `<g>` | UUID string | Fusion component occurrence token |
| `fill` | `<path>`, `<circle>` | Color or `"none"` | Visual hint for operation type |
| `height` | `<svg>` | Number + unit | SVG canvas height |
| `id` | `<g>` | `"TYPE: DEPTH"` | Encoded operation type + depth |
| `r` | `<circle>` | Number | Circle radius |
| `stroke` | `<path>`, `<circle>` | Color or `"none"` | Visual hint for operation type |
| `width` | `<svg>` | Number + unit | SVG canvas width |
| `xmlns` | `<svg>` | `http://www.w3.org/2000/svg` | SVG namespace (required) |
