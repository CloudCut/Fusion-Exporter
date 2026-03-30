"""Assemble a JSON document from intermediate geometry.

Mirrors svg_builder.py — same layout logic, same coordinate system,
but outputs a machine-readable JSON structure instead of SVG markup.
"""

import json

from . import utils
from .geometry_extractor import (
    ExportComponent, ExportOperation, ExportContour,
    CircleSeg, LineSeg, ArcSeg,
)
from . import path_converter


# Spacing between bodies when laying out multiple components
_LAYOUT_SPACING_CM = 1.0  # 1 cm gap between bodies
_MARGIN_CM = 1.0  # 1 cm margin around the canvas


def build_json(components, output_unit, stock_thickness_cm=0):
    """Build a JSON string from ExportComponents.

    Handles multi-body layout by arranging components side-by-side
    (same algorithm as svg_builder).

    Args:
        components: list of ExportComponent (coordinates in cm)
        output_unit: 'mm' or 'in'
        stock_thickness_cm: stock thickness in cm for all components in this file

    Returns:
        str: JSON document string
    """
    layout = _compute_layout(components, output_unit)
    canvas_w, canvas_h = layout['canvas_size']

    thickness_in_units = utils.cm_to_unit(stock_thickness_cm, output_unit)

    doc = {
        'units': output_unit,
        'stockThickness': _num(thickness_in_units, output_unit),
        'width': _num(canvas_w, output_unit),
        'height': _num(canvas_h, output_unit),
        'components': [],
    }

    for i, comp in enumerate(components):
        offset_x, offset_y = layout['offsets'][i]

        comp_obj = {
            'name': comp.name,
            'sourceGuid': comp.guid,
            'operations': [],
        }

        for op in comp.operations:
            depth_in_units = utils.cm_to_unit(op.cut_depth, output_unit)

            op_obj = {
                'type': op.op_type,
                'cutDepth': _num(depth_in_units, output_unit),
                'paths': [],
                'circles': [],
            }

            for contour in op.contours:
                _add_contour(op_obj, contour, op.op_type,
                             output_unit, offset_x, offset_y)

            comp_obj['operations'].append(op_obj)

        doc['components'].append(comp_obj)

    return json.dumps(doc, indent=2)


# ---------------------------------------------------------------------------
# Layout  (identical to svg_builder._compute_layout)
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
            ox = cursor_x - utils.cm_to_unit(min_x, output_unit)
            oy = margin - utils.cm_to_unit(min_y, output_unit)
            offsets.append((ox, oy))
            cursor_x += w + spacing
            max_height = max(max_height, h)
        else:
            offsets.append((cursor_x, margin))
            cursor_x += spacing

    canvas_w = cursor_x - spacing + margin
    canvas_h = max_height + 2 * margin

    canvas_w = max(canvas_w, 2 * margin)
    canvas_h = max(canvas_h, 2 * margin)

    return {
        'offsets': offsets,
        'canvas_size': (canvas_w, canvas_h),
    }


# ---------------------------------------------------------------------------
# Contour → JSON helpers
# ---------------------------------------------------------------------------

def _add_contour(op_obj, contour, op_type, output_unit, offset_x, offset_y):
    """Convert a contour to either a circle object or a path d-string
    and append it to the appropriate list in op_obj."""

    # Single full circle → emit as circle object
    if (len(contour.segments) == 1 and
            isinstance(contour.segments[0], CircleSeg) and
            op_type in ('drill', 'pocket')):
        seg = contour.segments[0]
        attrs = path_converter.circle_to_element(seg, output_unit)
        cx = float(attrs['cx']) + offset_x
        cy = float(attrs['cy']) + offset_y
        r = float(attrs['r'])
        op_obj['circles'].append({
            'cx': _num(cx, output_unit),
            'cy': _num(cy, output_unit),
            'r': _num(r, output_unit),
        })
        return

    # Everything else → path d-string
    d = _contour_to_path_d_with_offset(contour, output_unit, offset_x, offset_y)
    if d:
        op_obj['paths'].append(d)


def _contour_to_path_d_with_offset(contour, output_unit, offset_x, offset_y):
    """Convert a contour to a path 'd' string with layout offset applied.

    Same logic as svg_builder._contour_to_path_d_with_offset.
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


def _num(val, output_unit):
    """Round a numeric value to appropriate precision for JSON output."""
    if output_unit == 'mm':
        return round(val, 4)
    else:
        return round(val, 6)
