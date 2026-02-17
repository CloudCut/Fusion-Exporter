"""Convert intermediate geometry (PathSegments) to SVG path command strings."""

from . import utils
from .geometry_extractor import LineSeg, ArcSeg, CircleSeg, ExportContour


def contour_to_path_d(contour, output_unit):
    """Convert an ExportContour to an SVG path 'd' attribute string.

    All coordinates are converted from Fusion cm to the output unit.

    Args:
        contour: ExportContour with segments in cm
        output_unit: 'mm' or 'in'

    Returns:
        str: the SVG 'd' attribute value, e.g. "M10,20 L30,40 Z"
    """
    if not contour.segments:
        return ''

    first_seg = contour.segments[0]

    # Handle full circle as special case
    if len(contour.segments) == 1 and isinstance(first_seg, CircleSeg):
        return _circle_to_path_d(first_seg, output_unit)

    parts = []

    # Move to the start of the first segment
    start = _convert_point(first_seg.start, output_unit)
    parts.append('M{},{}'.format(
        _fmt(start[0], output_unit),
        _fmt(start[1], output_unit)
    ))

    for seg in contour.segments:
        if isinstance(seg, LineSeg):
            end = _convert_point(seg.end, output_unit)
            parts.append('L{},{}'.format(
                _fmt(end[0], output_unit),
                _fmt(end[1], output_unit)
            ))
        elif isinstance(seg, ArcSeg):
            parts.append(_arc_to_svg(seg, output_unit))
        elif isinstance(seg, CircleSeg):
            # A circle segment mid-contour (unusual) — emit as two arcs
            parts.append(_circle_seg_inline(seg, output_unit))

    if contour.is_closed:
        parts.append('Z')

    return ' '.join(parts)


def circle_to_element(seg, output_unit):
    """Convert a CircleSeg to SVG <circle> attribute dict.

    Args:
        seg: CircleSeg with center/radius in cm
        output_unit: 'mm' or 'in'

    Returns:
        dict with keys: cx, cy, r (all formatted strings)
    """
    cx = utils.cm_to_unit(seg.center[0], output_unit)
    cy = utils.cm_to_unit(seg.center[1], output_unit)
    r = utils.cm_to_unit(seg.radius, output_unit)

    return {
        'cx': _fmt(cx, output_unit),
        'cy': _fmt(cy, output_unit),
        'r': _fmt(r, output_unit),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _convert_point(pt_cm, output_unit):
    """Convert a 2D point from cm to output units."""
    return (
        utils.cm_to_unit(pt_cm[0], output_unit),
        utils.cm_to_unit(pt_cm[1], output_unit)
    )


def _fmt(val, output_unit):
    """Format a coordinate value for SVG output."""
    return utils.format_coord(val, output_unit)


def _arc_to_svg(seg, output_unit):
    """Convert an ArcSeg to an SVG 'A' command string."""
    r = utils.cm_to_unit(seg.radius, output_unit)
    end = _convert_point(seg.end, output_unit)

    large_arc_flag = 1 if seg.large_arc else 0
    sweep_flag = 1 if seg.clockwise else 0

    return 'A{},{} 0 {},{} {},{}'.format(
        _fmt(r, output_unit),
        _fmt(r, output_unit),
        large_arc_flag,
        sweep_flag,
        _fmt(end[0], output_unit),
        _fmt(end[1], output_unit)
    )


def _circle_to_path_d(seg, output_unit):
    """Convert a full CircleSeg to a path 'd' string using two semicircular arcs.

    This matches the parser's internal circle representation:
    M(cx-r, cy) A(r,r 0 1,0 cx+r,cy) A(r,r 0 1,0 cx-r,cy) Z
    """
    cx = utils.cm_to_unit(seg.center[0], output_unit)
    cy = utils.cm_to_unit(seg.center[1], output_unit)
    r = utils.cm_to_unit(seg.radius, output_unit)

    left_x = cx - r
    right_x = cx + r

    return 'M{},{} A{},{} 0 1,0 {},{} A{},{} 0 1,0 {},{} Z'.format(
        _fmt(left_x, output_unit), _fmt(cy, output_unit),
        _fmt(r, output_unit), _fmt(r, output_unit),
        _fmt(right_x, output_unit), _fmt(cy, output_unit),
        _fmt(r, output_unit), _fmt(r, output_unit),
        _fmt(left_x, output_unit), _fmt(cy, output_unit)
    )


def _circle_seg_inline(seg, output_unit):
    """Emit a circle as two arcs inline within a path (unusual case)."""
    cx = utils.cm_to_unit(seg.center[0], output_unit)
    cy = utils.cm_to_unit(seg.center[1], output_unit)
    r = utils.cm_to_unit(seg.radius, output_unit)

    left_x = cx - r
    right_x = cx + r

    return 'M{},{} A{},{} 0 1,0 {},{} A{},{} 0 1,0 {},{} Z'.format(
        _fmt(left_x, output_unit), _fmt(cy, output_unit),
        _fmt(r, output_unit), _fmt(r, output_unit),
        _fmt(right_x, output_unit), _fmt(cy, output_unit),
        _fmt(r, output_unit), _fmt(r, output_unit),
        _fmt(left_x, output_unit), _fmt(cy, output_unit)
    )
