"""Assemble a spec-compliant SVG document from intermediate geometry."""

from . import utils
from .geometry_extractor import (
    ExportComponent, ExportOperation, ExportContour,
    CircleSeg, LineSeg, ArcSeg,
)
from . import path_converter


# Fill/stroke conventions per operation type
_STYLE = {
    'pocket':  {'fill': 'gray', 'stroke': 'none'},
    'profile': {'fill': 'none', 'stroke': 'black'},
    'engrave': {'fill': 'none', 'stroke': 'blue'},
    'drill':   {'fill': 'black', 'stroke': 'none'},
}

# Thin stroke width per output unit (~0.5pt hairline)
_STROKE_WIDTH = {'mm': '0.18', 'in': '0.007'}

# Spacing between bodies when laying out multiple components
_LAYOUT_SPACING_CM = 1.0  # 1 cm gap between bodies
_MARGIN_CM = 1.0  # 1 cm margin around the canvas


def build_svg(components, output_unit):
    """Build a complete SVG document string from ExportComponents.

    Handles multi-body layout by arranging components side-by-side.

    Args:
        components: list of ExportComponent (coordinates in cm)
        output_unit: 'mm' or 'in'

    Returns:
        str: complete SVG document with XML declaration
    """
    # Compute layout offsets for each component
    layout = _compute_layout(components, output_unit)

    # Compute total canvas size
    canvas_w, canvas_h = layout['canvas_size']

    unit_suffix = output_unit

    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    w_str = utils.format_depth(canvas_w, output_unit)
    h_str = utils.format_depth(canvas_h, output_unit)
    lines.append('<svg xmlns="http://www.w3.org/2000/svg" '
                 'width="{}{}" height="{}{}" '
                 'viewBox="0 0 {} {}">'.format(
                     w_str, unit_suffix,
                     h_str, unit_suffix,
                     w_str, h_str))

    for i, comp in enumerate(components):
        offset_x, offset_y = layout['offsets'][i]
        lines.append('')
        lines.append('  <!-- Component: {} -->'.format(_xml_escape(comp.name)))
        lines.append('  <g data-component="{}" id="component-{}" data-source-guid="{}">'.format(
            _xml_escape(comp.name),
            i + 1,
            _xml_escape(comp.guid)
        ))

        # Group operations by type and depth
        for op in comp.operations:
            depth_in_units = utils.cm_to_unit(op.cut_depth, output_unit)
            depth_str = utils.format_depth(depth_in_units, output_unit)
            op_label = op.op_type.upper()

            lines.append('')
            lines.append('    <g id="{}: {}" data-operation="{}" data-cut-depth="{}">'.format(
                op_label, depth_str, op.op_type, depth_str
            ))

            for contour in op.contours:
                element_str = _render_contour(
                    contour, op.op_type, output_unit, offset_x, offset_y
                )
                if element_str:
                    lines.append('      ' + element_str)

            lines.append('    </g>')

        lines.append('  </g>')

    lines.append('')
    lines.append('</svg>')
    lines.append('')

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def _compute_layout(components, output_unit):
    """Compute side-by-side layout positions for multiple components.

    Returns dict with:
        'offsets': list of (offset_x, offset_y) per component in output units
        'canvas_size': (width, height) in output units
    """
    margin = utils.cm_to_unit(_MARGIN_CM, output_unit)
    spacing = utils.cm_to_unit(_LAYOUT_SPACING_CM, output_unit)

    offsets = []
    cursor_x = margin
    max_height = 0.0

    for comp in components:
        if comp.bbox:
            min_x, min_y, max_x, max_y = comp.bbox
            w = utils.cm_to_unit(max_x - min_x, output_unit)
            h = utils.cm_to_unit(max_y - min_y, output_unit)
            # Offset so the component's min corner lands at (cursor_x, margin)
            ox = cursor_x - utils.cm_to_unit(min_x, output_unit)
            oy = margin - utils.cm_to_unit(min_y, output_unit)
            offsets.append((ox, oy))
            cursor_x += w + spacing
            max_height = max(max_height, h)
        else:
            offsets.append((cursor_x, margin))
            cursor_x += spacing

    canvas_w = cursor_x - spacing + margin  # remove last spacing, add right margin
    canvas_h = max_height + 2 * margin

    # Ensure minimum canvas size
    canvas_w = max(canvas_w, 2 * margin)
    canvas_h = max(canvas_h, 2 * margin)

    return {
        'offsets': offsets,
        'canvas_size': (canvas_w, canvas_h),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render_contour(contour, op_type, output_unit, offset_x, offset_y):
    """Render a single contour as an SVG element string.

    Applies layout offset and converts coordinates from cm to output units.
    """
    style = _STYLE.get(op_type, _STYLE['profile'])
    fill = style['fill']
    stroke = style['stroke']

    # Check if this is a single full circle
    if (len(contour.segments) == 1 and
            isinstance(contour.segments[0], CircleSeg) and
            op_type in ('drill', 'pocket')):
        seg = contour.segments[0]
        attrs = path_converter.circle_to_element(seg, output_unit)
        cx = float(attrs['cx']) + offset_x
        cy = float(attrs['cy']) + offset_y
        sw = _STROKE_WIDTH.get(output_unit, '0.18')
        return '<circle cx="{}" cy="{}" r="{}" fill="{}" stroke="{}" stroke-width="{}"/>'.format(
            utils.format_coord(cx, output_unit),
            utils.format_coord(cy, output_unit),
            attrs['r'],
            fill,
            stroke,
            sw
        )

    # Build path with offset applied
    d = _contour_to_path_d_with_offset(contour, output_unit, offset_x, offset_y)
    if not d:
        return None

    sw = _STROKE_WIDTH.get(output_unit, '0.18')
    return '<path d="{}" fill="{}" stroke="{}" stroke-width="{}"/>'.format(d, fill, stroke, sw)


def _contour_to_path_d_with_offset(contour, output_unit, offset_x, offset_y):
    """Convert a contour to a path 'd' string with layout offset applied.

    Coordinates are converted from cm to output units, then offset is added.
    """
    if not contour.segments:
        return ''

    first_seg = contour.segments[0]

    # Handle full circle
    if len(contour.segments) == 1 and isinstance(first_seg, CircleSeg):
        return _circle_path_d_with_offset(first_seg, output_unit, offset_x, offset_y)

    parts = []

    # Move to start
    sx, sy = _convert_and_offset(first_seg.start, output_unit, offset_x, offset_y)
    parts.append('M{},{}'.format(
        utils.format_coord(sx, output_unit),
        utils.format_coord(sy, output_unit)
    ))

    for seg in contour.segments:
        if isinstance(seg, LineSeg):
            ex, ey = _convert_and_offset(seg.end, output_unit, offset_x, offset_y)
            parts.append('L{},{}'.format(
                utils.format_coord(ex, output_unit),
                utils.format_coord(ey, output_unit)
            ))
        elif isinstance(seg, ArcSeg):
            r = utils.cm_to_unit(seg.radius, output_unit)
            ex, ey = _convert_and_offset(seg.end, output_unit, offset_x, offset_y)
            large_flag = 1 if seg.large_arc else 0
            sweep_flag = 1 if seg.clockwise else 0
            parts.append('A{},{} 0 {},{} {},{}'.format(
                utils.format_coord(r, output_unit),
                utils.format_coord(r, output_unit),
                large_flag,
                sweep_flag,
                utils.format_coord(ex, output_unit),
                utils.format_coord(ey, output_unit)
            ))
        elif isinstance(seg, CircleSeg):
            # Inline circle (two arcs)
            cx_u = utils.cm_to_unit(seg.center[0], output_unit) + offset_x
            cy_u = utils.cm_to_unit(seg.center[1], output_unit) + offset_y
            r = utils.cm_to_unit(seg.radius, output_unit)
            lx = cx_u - r
            rx_val = cx_u + r
            parts.append('M{},{}'.format(
                utils.format_coord(lx, output_unit),
                utils.format_coord(cy_u, output_unit)
            ))
            parts.append('A{},{} 0 1,0 {},{}'.format(
                utils.format_coord(r, output_unit),
                utils.format_coord(r, output_unit),
                utils.format_coord(rx_val, output_unit),
                utils.format_coord(cy_u, output_unit)
            ))
            parts.append('A{},{} 0 1,0 {},{}'.format(
                utils.format_coord(r, output_unit),
                utils.format_coord(r, output_unit),
                utils.format_coord(lx, output_unit),
                utils.format_coord(cy_u, output_unit)
            ))
            parts.append('Z')

    if contour.is_closed:
        parts.append('Z')

    return ' '.join(parts)


def _circle_path_d_with_offset(seg, output_unit, offset_x, offset_y):
    """Full circle as two-arc path with offset."""
    cx = utils.cm_to_unit(seg.center[0], output_unit) + offset_x
    cy = utils.cm_to_unit(seg.center[1], output_unit) + offset_y
    r = utils.cm_to_unit(seg.radius, output_unit)

    lx = cx - r
    rx_val = cx + r

    return 'M{},{} A{},{} 0 1,0 {},{} A{},{} 0 1,0 {},{} Z'.format(
        utils.format_coord(lx, output_unit), utils.format_coord(cy, output_unit),
        utils.format_coord(r, output_unit), utils.format_coord(r, output_unit),
        utils.format_coord(rx_val, output_unit), utils.format_coord(cy, output_unit),
        utils.format_coord(r, output_unit), utils.format_coord(r, output_unit),
        utils.format_coord(lx, output_unit), utils.format_coord(cy, output_unit)
    )


def _convert_and_offset(pt_cm, output_unit, offset_x, offset_y):
    """Convert a 2D cm point to output units and apply layout offset."""
    x = utils.cm_to_unit(pt_cm[0], output_unit) + offset_x
    y = utils.cm_to_unit(pt_cm[1], output_unit) + offset_y
    return (x, y)


def _xml_escape(text):
    """Escape special XML characters in attribute values."""
    if not text:
        return ''
    text = text.replace('&', '&amp;')
    text = text.replace('"', '&quot;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text
