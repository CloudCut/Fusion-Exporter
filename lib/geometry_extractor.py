"""Extract geometry from Fusion 360 API objects.

Produces an intermediate representation of components, operations,
contours, and path segments that can be converted to SVG.
"""

import adsk.core
import adsk.fusion
import math

from . import utils


# ---------------------------------------------------------------------------
# Intermediate geometry data classes
# ---------------------------------------------------------------------------

class PathSegment:
    """Base class for a path segment."""
    pass


class LineSeg(PathSegment):
    """Straight line from start to end. Coordinates are 2D (x, y) tuples in cm."""
    def __init__(self, start, end):
        self.start = start
        self.end = end

    def __repr__(self):
        return 'LineSeg({} -> {})'.format(self.start, self.end)


class ArcSeg(PathSegment):
    """Circular arc. Coordinates are 2D (x, y) tuples in cm."""
    def __init__(self, start, end, center, radius, clockwise, large_arc):
        self.start = start
        self.end = end
        self.center = center
        self.radius = radius
        self.clockwise = clockwise
        self.large_arc = large_arc

    def __repr__(self):
        return 'ArcSeg(r={:.4f}, cw={}, lg={})'.format(
            self.radius, self.clockwise, self.large_arc
        )


class CircleSeg(PathSegment):
    """Full circle. Coordinates are 2D in cm."""
    def __init__(self, center, radius):
        self.center = center
        self.radius = radius

    def __repr__(self):
        return 'CircleSeg(c={}, r={:.4f})'.format(self.center, self.radius)


class ExportContour:
    """A single closed or open contour (edge loop)."""
    def __init__(self, segments, is_closed=True, is_outer=True):
        self.segments = segments  # list[PathSegment]
        self.is_closed = is_closed
        self.is_outer = is_outer

    def __repr__(self):
        return 'ExportContour(segs={}, closed={}, outer={})'.format(
            len(self.segments), self.is_closed, self.is_outer
        )


class ExportOperation:
    """A group of contours sharing the same operation type and cut depth."""
    def __init__(self, op_type, cut_depth, contours=None):
        self.op_type = op_type        # 'profile', 'pocket', 'drill', 'engrave'
        self.cut_depth = cut_depth    # in cm (Fusion internal units)
        self.contours = contours or []  # list[ExportContour]

    def __repr__(self):
        return 'ExportOperation({} @ {}, contours={})'.format(
            self.op_type, self.cut_depth, len(self.contours)
        )


class ExportComponent:
    """A named component containing operations."""
    def __init__(self, name, guid, operations=None, bbox=None):
        self.name = name
        self.guid = guid
        self.operations = operations or []  # list[ExportOperation]
        self.bbox = bbox  # (min_x, min_y, max_x, max_y) in cm or None

    def __repr__(self):
        return 'ExportComponent({}, ops={})'.format(
            self.name, len(self.operations)
        )


# Tolerance for grouping faces at the same level (cm)
_LEVEL_TOL = 1e-4

# Tolerance for comparing normal directions (dot product)
_NORMAL_TOL = 0.9999


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_from_bodies(bodies):
    """Extract geometry from a list of BRepBody objects.

    Material thickness is auto-detected per body from the distance
    between the top and bottom faces along the sheet normal.

    Args:
        bodies: list of adsk.fusion.BRepBody

    Returns:
        list of ExportComponent
    """
    components = []

    for body in bodies:
        comp = _extract_body(body)
        if comp and comp.operations:
            components.append(comp)

    return components


# ---------------------------------------------------------------------------
# Body-level extraction
# ---------------------------------------------------------------------------

def _extract_body(body):
    """Extract geometry from a single BRepBody."""
    parent_comp = body.parentComponent
    name = body.name if body.name else parent_comp.name

    guid = ''
    try:
        guid = body.entityToken
    except Exception:
        guid = parent_comp.id

    utils.log('Processing body: {}'.format(name))

    # Classify all planar faces along the sheet normal
    result = _classify_faces(body)
    if result is None:
        utils.log('  No suitable planar faces found, skipping.')
        return None

    profile_face = result['profile_face']
    through_hole_faces = result['through_hole_faces']
    thickness_cm = result['thickness_cm']
    pocket_faces = result['pocket_faces']
    sheet_normal = result['sheet_normal']

    utils.log('  Sheet normal: ({:.4f}, {:.4f}, {:.4f})'.format(
        sheet_normal[0], sheet_normal[1], sheet_normal[2]))
    utils.log('  Thickness: {:.4f} cm'.format(thickness_cm))
    utils.log('  Through-hole faces: {}'.format(len(through_hole_faces)))
    utils.log('  Pocket face groups: {}'.format(len(pocket_faces)))

    # Build a consistent projection frame from the profile face
    prof_plane = profile_face.geometry
    u_axis, v_axis = _build_face_axes(prof_plane)
    proj_origin = prof_plane.origin

    # Collect operations
    operations_map = {}  # key: (op_type, depth_cm) -> list of contours

    # OUTER PROFILE: from the profile face's outer loop.
    # This is the single intact face whose outer loop is the true part
    # boundary. (The opposite side can be split into multiple faces when
    # pockets at different depths intersect.)
    _extract_outer_profile(profile_face, thickness_cm, operations_map,
                           proj_origin, u_axis, v_axis)

    # THROUGH-HOLES: from all through-hole faces' inner loops.
    # Inner loops on the opposite side are through-holes (circles = drill,
    # non-circular = profile cut-through).
    for bf in through_hole_faces:
        _extract_through_holes(bf['face'], thickness_cm, operations_map,
                               proj_origin, u_axis, v_axis)

    # POCKETS: from intermediate-level faces
    for pocket_depth_cm, faces in pocket_faces:
        _extract_pocket_contours(faces, pocket_depth_cm, operations_map,
                                 proj_origin, u_axis, v_axis)

    # Build ExportComponent
    operations = []
    for (op_type, depth_cm), contours in operations_map.items():
        operations.append(ExportOperation(op_type, depth_cm, contours))

    bbox = _compute_component_bbox(operations)

    return ExportComponent(name, guid, operations, bbox)


def _classify_faces(body):
    """Classify all planar faces of a body by position along the sheet normal.

    Works with arbitrarily oriented sheet bodies (not just Z-up).

    1. Collects all planar faces and groups them by normal direction
       (treating n and -n as the same orientation).
    2. The normal-group with the most total area = the sheet plane.
    3. Projects face positions along that normal to determine height.
    4. Highest projection = top, lowest = bottom, intermediate = pockets.

    Returns:
        dict with keys:
            'profile_face': BRepFace for outer profile (single intact face)
            'through_hole_faces': list of face_dicts for through-hole detection
            'thickness_cm': material thickness in cm
            'pocket_faces': list of (depth_cm, [face_dicts]) tuples
            'sheet_normal': (x, y, z) tuple of the sheet's normal direction
        Returns None if no suitable planar faces found.
    """
    # Collect all planar faces
    planar_faces = []
    for face in body.faces:
        geom = face.geometry
        if isinstance(geom, adsk.core.Plane):
            n = geom.normal
            o = geom.origin
            planar_faces.append({
                'face': face,
                'normal': (n.x, n.y, n.z),
                'origin': (o.x, o.y, o.z),
                'area': face.area,
            })

    if not planar_faces:
        return None

    # Group faces by normal direction (n and -n are the same sheet orientation)
    normal_groups = _group_faces_by_normal(planar_faces)

    if not normal_groups:
        return None

    # Find the group with the most total area — that's our sheet plane
    best_group = max(normal_groups, key=lambda g: g['total_area'])
    sheet_normal = best_group['normal']  # canonical normal direction
    sheet_faces = best_group['faces']

    utils.log('  Found {} normal groups, sheet normal = ({:.4f}, {:.4f}, {:.4f}) '
              'with {} faces, total area = {:.4f} cm²'.format(
                  len(normal_groups),
                  sheet_normal[0], sheet_normal[1], sheet_normal[2],
                  len(sheet_faces), best_group['total_area']))

    # Project each face's origin along the sheet normal to get its "height"
    for f in sheet_faces:
        ox, oy, oz = f['origin']
        f['height'] = ox * sheet_normal[0] + oy * sheet_normal[1] + oz * sheet_normal[2]

    # Group by height level
    height_groups = _group_faces_by_level(sheet_faces, key='height')

    if not height_groups:
        return None

    # Highest = top, lowest = bottom
    heights = [h for h, _ in height_groups]
    highest = max(heights)
    lowest = min(heights)

    thickness_cm = highest - lowest

    if thickness_cm < _LEVEL_TOL:
        # All faces at same level — flat body, no thickness
        largest = max(sheet_faces, key=lambda f: f['area'])
        return {
            'profile_face': largest['face'],
            'through_hole_faces': [],
            'thickness_cm': 0,
            'pocket_faces': [],
            'sheet_normal': sheet_normal,
        }

    high_candidates = []
    low_candidates = []
    pocket_face_list = []

    for level, faces in height_groups:
        if abs(level - highest) < _LEVEL_TOL:
            high_candidates.extend(faces)
        elif abs(level - lowest) < _LEVEL_TOL:
            low_candidates.extend(faces)
        else:
            pocket_face_list.extend([(level, f) for f in faces])

    # Determine which side the pockets open from using pocket face outward normals.
    # The outward normal of a pocket bottom face points into the pocket cavity
    # (toward the pocket opening = the machining top of the sheet).
    # If the dot product of the pocket face outward normal with the sheet normal
    # is negative, pockets open toward the low-projection side (low = machining top).
    # If positive, pockets open toward the high-projection side (high = machining top).
    pockets_open_toward_high = True  # default
    if pocket_face_list:
        dot_sum = 0.0
        for _, pf in pocket_face_list:
            face_obj = pf['face']
            fn = pf['normal']
            # Determine the outward normal (face normal, accounting for isParamReversed)
            if face_obj.isParamReversed:
                outward = (-fn[0], -fn[1], -fn[2])
            else:
                outward = fn
            dot_sum += (outward[0] * sheet_normal[0] +
                        outward[1] * sheet_normal[1] +
                        outward[2] * sheet_normal[2])
        pockets_open_toward_high = dot_sum > 0
        utils.log('  Pocket normal dot sum: {:.4f} → pockets open toward {} level'.format(
            dot_sum, 'high' if pockets_open_toward_high else 'low'))

    # The machining top is the side the pockets open toward.
    # Pocket depth is measured from the machining top level.
    if pockets_open_toward_high:
        machining_top_level = highest
    else:
        machining_top_level = lowest

    utils.log('  Machining top level: {:.4f}'.format(machining_top_level))

    # PROFILE FACE selection strategy:
    # The machining-top face is the best profile candidate because its inner
    # loops are pocket/counterbore openings (which we intentionally skip),
    # while the bottom face's inner loops are true through-holes.
    # However, if the machining-top side has MORE faces (split by intersecting
    # pocket geometry), we must use the side with fewer faces for profile
    # to get a clean outer loop.
    if pockets_open_toward_high:
        machining_top_candidates = high_candidates
        bottom_candidates = low_candidates
    else:
        machining_top_candidates = low_candidates
        bottom_candidates = high_candidates

    if len(machining_top_candidates) <= len(bottom_candidates):
        # Machining top has fewer or equal faces — use it for profile.
        # Through-holes come from the bottom (only true through-features).
        profile_candidates = machining_top_candidates
        through_hole_faces = bottom_candidates
    else:
        # Machining top is split — use bottom for profile (cleaner outer loop).
        # Through-holes come from machining top (may include pocket openings).
        profile_candidates = bottom_candidates
        through_hole_faces = machining_top_candidates

    profile_face = max(profile_candidates, key=lambda f: f['area'])['face']

    profile_side = 'machining-top' if profile_candidates is machining_top_candidates else 'bottom'
    utils.log('  Profile face from {} ({} faces), through-holes from {} ({} faces)'.format(
        profile_side, len(profile_candidates),
        'bottom' if profile_side == 'machining-top' else 'machining-top',
        len(through_hole_faces)
    ))

    # Group pocket faces by level
    pocket_groups = {}
    for level, f in pocket_face_list:
        # Find matching bucket
        matched = False
        for existing_level in list(pocket_groups.keys()):
            if abs(level - existing_level) < _LEVEL_TOL:
                pocket_groups[existing_level].append(f)
                matched = True
                break
        if not matched:
            pocket_groups[level] = [f]

    # Convert to (depth_from_machining_top, faces) tuples.
    pocket_faces = []
    for level, faces in pocket_groups.items():
        depth_cm = abs(machining_top_level - level)
        pocket_faces.append((depth_cm, faces))
        utils.log('  Pocket group at level={:.4f} (depth={:.4f} cm): {} face(s)'.format(
            level, depth_cm, len(faces)
        ))

    # Sort by depth ascending (shallowest first)
    pocket_faces.sort(key=lambda x: x[0])

    return {
        'profile_face': profile_face,
        'through_hole_faces': through_hole_faces,
        'thickness_cm': thickness_cm,
        'pocket_faces': pocket_faces,
        'sheet_normal': sheet_normal,
    }


def _group_faces_by_normal(planar_faces):
    """Group planar faces by normal direction, treating n and -n as equivalent.

    Returns list of dicts: {'normal': (x,y,z), 'faces': [...], 'total_area': float}
    The canonical normal is chosen so that the largest-area face's normal is used
    (this tends to point "outward" from the top of the sheet).
    """
    groups = []

    for f in planar_faces:
        nx, ny, nz = f['normal']
        matched = False

        for g in groups:
            gnx, gny, gnz = g['normal']
            # Check if normals are parallel (same or opposite direction)
            dot = abs(nx * gnx + ny * gny + nz * gnz)
            if dot > _NORMAL_TOL:
                g['faces'].append(f)
                g['total_area'] += f['area']
                matched = True
                break

        if not matched:
            groups.append({
                'normal': (nx, ny, nz),
                'faces': [f],
                'total_area': f['area'],
            })

    # Normalize each group's canonical normal: use the normal direction
    # that points "up" (positive dot with Z, or if flat, positive dot with Y)
    for g in groups:
        nx, ny, nz = g['normal']
        # Prefer normal pointing in positive Z, then positive Y, then positive X
        if nz < -0.01 or (abs(nz) < 0.01 and ny < -0.01) or (abs(nz) < 0.01 and abs(ny) < 0.01 and nx < -0.01):
            g['normal'] = (-nx, -ny, -nz)

    return groups


def _group_faces_by_level(faces, key='height'):
    """Group faces by a numeric level value with tolerance.

    Returns list of (level, [face_dicts]) sorted by level descending.
    """
    if not faces:
        return []

    sorted_faces = sorted(faces, key=lambda f: f[key], reverse=True)

    groups = []
    current_level = sorted_faces[0][key]
    current_group = [sorted_faces[0]]

    for f in sorted_faces[1:]:
        if abs(f[key] - current_level) < _LEVEL_TOL:
            current_group.append(f)
        else:
            groups.append((current_level, current_group))
            current_level = f[key]
            current_group = [f]

    groups.append((current_level, current_group))
    return groups


# ---------------------------------------------------------------------------
# Face contour extraction
# ---------------------------------------------------------------------------

def _extract_outer_profile(face, thickness_cm, operations_map,
                           proj_origin, u_axis, v_axis):
    """Extract the outer profile from the top face's outer loop only.

    The top face is typically a single intact face whose outer loop is the
    true part boundary. We ignore its inner loops here — those are pocket
    openings, not through-cuts.
    """
    for loop in face.loops:
        if not loop.isOuter:
            continue  # Skip inner loops (pocket openings on top face)

        contour = _extract_loop(loop, proj_origin, u_axis, v_axis)
        if contour is None:
            continue

        contour.is_outer = True
        key = ('profile', thickness_cm)
        if key not in operations_map:
            operations_map[key] = []
        operations_map[key].append(contour)


def _extract_through_holes(face, thickness_cm, operations_map,
                            proj_origin, u_axis, v_axis):
    """Extract through-holes from a bottom face's inner loops.

    Inner loops on bottom faces are through-features: circles become drill
    operations, non-circular loops become profile cut-throughs. Outer loops
    on bottom faces are ignored (they're internal boundaries from face splitting,
    not the true part outline).
    """
    for loop in face.loops:
        if loop.isOuter:
            continue  # Skip outer loop of bottom faces

        contour = _extract_loop(loop, proj_origin, u_axis, v_axis)
        if contour is None:
            continue

        contour.is_outer = False

        if _is_full_circle_contour(contour):
            op_type = 'drill'
        else:
            op_type = 'profile'

        key = (op_type, thickness_cm)
        if key not in operations_map:
            operations_map[key] = []
        operations_map[key].append(contour)


def _extract_pocket_contours(face_dicts, pocket_depth_cm, operations_map,
                              proj_origin, u_axis, v_axis):
    """Extract pocket contours from faces at a given Z level.

    Extracts BOTH outer and inner loops from each pocket face:
    - Outer loops define the pocket boundary.
    - Inner loops define islands (raised areas), deeper pocket openings, or
      through-hole boundaries within the pocket.

    All are emitted as separate paths in the same pocket operation group.
    The CAM parser uses containment analysis to determine which paths are
    outer boundaries and which are islands.
    """
    for fd in face_dicts:
        face = fd['face']
        for loop in face.loops:
            contour = _extract_loop(loop, proj_origin, u_axis, v_axis)
            if contour is None:
                continue

            contour.is_outer = loop.isOuter

            # All partial-depth features are pockets (including blind holes).
            # Only through-holes at material thickness are drill operations.
            op_type = 'pocket'

            key = (op_type, pocket_depth_cm)
            if key not in operations_map:
                operations_map[key] = []
            operations_map[key].append(contour)


# ---------------------------------------------------------------------------
# Loop and edge conversion
# ---------------------------------------------------------------------------

def _extract_loop(loop, origin, u_axis, v_axis):
    """Extract a contour from a BRepLoop.

    Projects 3D edge geometry onto the 2D coordinate system.
    Returns an ExportContour or None if the loop has no valid geometry.
    """
    segments = []

    co_edges = list(loop.coEdges)
    if not co_edges:
        return None

    for co_edge in co_edges:
        edge = co_edge.edge
        is_opposed = co_edge.isOpposedToEdge
        edge_geom = edge.geometry

        new_segs = _convert_edge_geometry(
            edge, edge_geom, is_opposed, origin, u_axis, v_axis
        )
        segments.extend(new_segs)

    if not segments:
        return None

    return ExportContour(segments, is_closed=True, is_outer=True)


def _convert_edge_geometry(edge, geom, is_opposed, origin, u_axis, v_axis):
    """Convert a 3D edge geometry to 2D path segments."""
    if isinstance(geom, adsk.core.Circle3D):
        center_2d = _project_point(geom.center, origin, u_axis, v_axis)
        radius = geom.radius
        return [CircleSeg(center_2d, radius)]

    if isinstance(geom, adsk.core.Arc3D):
        return _convert_arc(edge, geom, is_opposed, origin, u_axis, v_axis)

    if isinstance(geom, adsk.core.Line3D):
        return _convert_line(edge, is_opposed, origin, u_axis, v_axis)

    # NurbsCurve3D or other complex curves: tessellate
    return _tessellate_edge(edge, is_opposed, origin, u_axis, v_axis)


def _convert_line(edge, is_opposed, origin, u_axis, v_axis):
    """Convert a linear edge to a LineSeg."""
    sp = edge.startVertex.geometry
    ep = edge.endVertex.geometry

    start_2d = _project_point(sp, origin, u_axis, v_axis)
    end_2d = _project_point(ep, origin, u_axis, v_axis)

    if is_opposed:
        start_2d, end_2d = end_2d, start_2d

    return [LineSeg(start_2d, end_2d)]


def _convert_arc(edge, geom, is_opposed, origin, u_axis, v_axis):
    """Convert an Arc3D edge to an ArcSeg.

    Computes the SVG large-arc-flag and sweep-flag from Fusion's arc
    representation.
    """
    sp = edge.startVertex.geometry
    ep = edge.endVertex.geometry

    start_2d = _project_point(sp, origin, u_axis, v_axis)
    end_2d = _project_point(ep, origin, u_axis, v_axis)
    center_2d = _project_point(geom.center, origin, u_axis, v_axis)
    radius = geom.radius

    if is_opposed:
        start_2d, end_2d = end_2d, start_2d

    # Determine the arc's native direction in the projected 2D space.
    # The arc normal (geom.normal) indicates the axis — if it aligns with
    # the projection's "up" direction (u x v), the arc is CCW in 2D.
    arc_normal = geom.normal
    view_z_x = u_axis.y * v_axis.z - u_axis.z * v_axis.y
    view_z_y = u_axis.z * v_axis.x - u_axis.x * v_axis.z
    view_z_z = u_axis.x * v_axis.y - u_axis.y * v_axis.x

    dot_normal = (arc_normal.x * view_z_x +
                  arc_normal.y * view_z_y +
                  arc_normal.z * view_z_z)

    arc_is_ccw = dot_normal > 0

    if is_opposed:
        arc_is_ccw = not arc_is_ccw

    # In SVG Y-down coordinates, CCW in math-Y-up = CW visually.
    # SVG sweep_flag=1 means clockwise in SVG space.
    clockwise = arc_is_ccw

    # Compute sweep angle magnitude for large-arc determination
    cs = (start_2d[0] - center_2d[0], start_2d[1] - center_2d[1])
    ce = (end_2d[0] - center_2d[0], end_2d[1] - center_2d[1])
    angle_start = math.atan2(cs[1], cs[0])
    angle_end = math.atan2(ce[1], ce[0])

    sweep = angle_end - angle_start
    if arc_is_ccw:
        if sweep <= 0:
            sweep += 2 * math.pi
    else:
        if sweep >= 0:
            sweep -= 2 * math.pi

    large_arc = abs(sweep) > math.pi

    return [ArcSeg(start_2d, end_2d, center_2d, radius, clockwise, large_arc)]


def _tessellate_edge(edge, is_opposed, origin, u_axis, v_axis):
    """Tessellate a complex edge (NurbsCurve, etc.) into line segments."""
    evaluator = edge.evaluator
    result, start_param, end_param = evaluator.getParameterExtents()
    if not result:
        return []

    tolerance = 0.001  # cm (roughly 0.01mm)
    result, points = evaluator.getStrokes(start_param, end_param, tolerance)
    if not result or not points or len(points) < 2:
        return []

    pts_2d = [_project_point(p, origin, u_axis, v_axis) for p in points]

    if is_opposed:
        pts_2d.reverse()

    segments = []
    for i in range(len(pts_2d) - 1):
        segments.append(LineSeg(pts_2d[i], pts_2d[i + 1]))

    return segments


# ---------------------------------------------------------------------------
# Projection and coordinate helpers
# ---------------------------------------------------------------------------

def _build_face_axes(plane):
    """Build an orthonormal U/V coordinate frame from a Plane.

    V is negated so that the projection outputs SVG-compatible Y-down
    coordinates directly.  Fusion's Y-up (or the face's "physical up")
    maps to negative V, which means small SVG-Y = top of the workpiece.

    For horizontal faces (normal along Z): U = +X, V = -Y.
    For non-horizontal faces: general orthonormal frame with V negated.
    """
    normal = plane.normal

    if abs(normal.z) > 0.9:
        u = adsk.core.Vector3D.create(1, 0, 0)
        v = adsk.core.Vector3D.create(0, -1, 0)
        return u, v

    ref = adsk.core.Vector3D.create(0, 0, 1)

    u = adsk.core.Vector3D.create(
        ref.y * normal.z - ref.z * normal.y,
        ref.z * normal.x - ref.x * normal.z,
        ref.x * normal.y - ref.y * normal.x
    )
    u.normalize()

    # Compute normal × u, then negate for SVG Y-down convention
    v = adsk.core.Vector3D.create(
        -(normal.y * u.z - normal.z * u.y),
        -(normal.z * u.x - normal.x * u.z),
        -(normal.x * u.y - normal.y * u.x)
    )
    v.normalize()

    return u, v


def _project_point(point3d, origin, u_axis, v_axis):
    """Project a 3D point onto a 2D coordinate system defined by origin, u, v.

    Returns (u, v) tuple in cm (Fusion internal units).
    """
    dx = point3d.x - origin.x
    dy = point3d.y - origin.y
    dz = point3d.z - origin.z

    u = dx * u_axis.x + dy * u_axis.y + dz * u_axis.z
    v = dx * v_axis.x + dy * v_axis.y + dz * v_axis.z

    return (u, v)


# ---------------------------------------------------------------------------
# Contour analysis helpers
# ---------------------------------------------------------------------------

def _is_full_circle_contour(contour):
    """Check if a contour represents a full circle."""
    if len(contour.segments) == 1 and isinstance(contour.segments[0], CircleSeg):
        return True

    if len(contour.segments) == 2:
        s0 = contour.segments[0]
        s1 = contour.segments[1]
        if isinstance(s0, ArcSeg) and isinstance(s1, ArcSeg):
            if abs(s0.radius - s1.radius) < 1e-6:
                if utils.distance_2d(s0.center, s1.center) < 1e-6:
                    return True
    return False


def _compute_component_bbox(operations):
    """Compute bounding box from all operations' contour segments.

    Returns (min_x, min_y, max_x, max_y) in cm, or None if no geometry.
    """
    min_x = float('inf')
    min_y = float('inf')
    max_x = float('-inf')
    max_y = float('-inf')
    has_points = False

    for op in operations:
        for contour in op.contours:
            for seg in contour.segments:
                points = _segment_bounds_points(seg)
                for px, py in points:
                    min_x = min(min_x, px)
                    min_y = min(min_y, py)
                    max_x = max(max_x, px)
                    max_y = max(max_y, py)
                    has_points = True

    if not has_points:
        return None

    return (min_x, min_y, max_x, max_y)


def _segment_bounds_points(seg):
    """Get bounding points for a segment (in cm)."""
    if isinstance(seg, LineSeg):
        return [seg.start, seg.end]
    elif isinstance(seg, ArcSeg):
        points = [seg.start, seg.end]
        cx, cy = seg.center
        r = seg.radius
        points.extend([
            (cx - r, cy), (cx + r, cy),
            (cx, cy - r), (cx, cy + r)
        ])
        return points
    elif isinstance(seg, CircleSeg):
        cx, cy = seg.center
        r = seg.radius
        return [
            (cx - r, cy - r),
            (cx + r, cy + r),
            (cx - r, cy + r),
            (cx + r, cy - r)
        ]
    return []


# ---------------------------------------------------------------------------
# Debug dump
# ---------------------------------------------------------------------------

def dump_debug_report(bodies, file_path):
    """Write a detailed debug report of all face geometry for the given bodies.

    The report includes every face on every body: type, normal, origin,
    area, Z position, loop count, and edge types per loop. This lets us
    see exactly what the Fusion API exposes and how classify_faces()
    interprets it.

    Args:
        bodies: list of adsk.fusion.BRepBody
        file_path: path to write the .txt report to
    """
    lines = []
    lines.append('=' * 70)
    lines.append('FUSION EXPORTER — DEBUG GEOMETRY REPORT')
    lines.append('=' * 70)
    lines.append('')

    for bi, body in enumerate(bodies):
        parent_comp = body.parentComponent
        body_name = body.name if body.name else parent_comp.name

        lines.append('-' * 70)
        lines.append('BODY {}: "{}"'.format(bi + 1, body_name))
        lines.append('  Parent component: {}'.format(parent_comp.name))
        lines.append('  Total faces: {}'.format(body.faces.count))
        lines.append('  Total edges: {}'.format(body.edges.count))
        lines.append('')

        # Dump every face
        horiz_faces = []
        for fi in range(body.faces.count):
            face = body.faces.item(fi)
            geom = face.geometry
            geom_type = type(geom).__name__

            lines.append('  FACE {}: type={}, area={:.6f} cm²'.format(
                fi, geom_type, face.area
            ))

            if isinstance(geom, adsk.core.Plane):
                n = geom.normal
                o = geom.origin
                lines.append('    Normal: ({:.6f}, {:.6f}, {:.6f})'.format(n.x, n.y, n.z))
                lines.append('    Origin: ({:.6f}, {:.6f}, {:.6f})'.format(o.x, o.y, o.z))
                lines.append('    |normal.z| = {:.6f}  (horizontal if > 0.9)'.format(abs(n.z)))

                is_horiz = abs(n.z) > 0.9
                lines.append('    Horizontal: {}'.format(is_horiz))
                if is_horiz:
                    horiz_faces.append({'face': face, 'z': o.z, 'area': face.area, 'idx': fi})

                # Check isParamReversed
                try:
                    lines.append('    isParamReversed: {}'.format(face.isParamReversed))
                except Exception:
                    pass

            elif isinstance(geom, adsk.core.Cylinder):
                lines.append('    Cylinder axis: ({:.6f}, {:.6f}, {:.6f})'.format(
                    geom.axis.x, geom.axis.y, geom.axis.z))
                lines.append('    Cylinder origin: ({:.6f}, {:.6f}, {:.6f})'.format(
                    geom.origin.x, geom.origin.y, geom.origin.z))
                lines.append('    Cylinder radius: {:.6f}'.format(geom.radius))

            elif isinstance(geom, adsk.core.Cone):
                lines.append('    Cone axis: ({:.6f}, {:.6f}, {:.6f})'.format(
                    geom.axis.x, geom.axis.y, geom.axis.z))
                lines.append('    Cone half-angle: {:.6f} rad'.format(geom.halfAngle))

            elif isinstance(geom, adsk.core.Sphere):
                lines.append('    Sphere center: ({:.6f}, {:.6f}, {:.6f})'.format(
                    geom.origin.x, geom.origin.y, geom.origin.z))
                lines.append('    Sphere radius: {:.6f}'.format(geom.radius))

            elif isinstance(geom, adsk.core.Torus):
                lines.append('    Torus (details omitted)')

            elif isinstance(geom, adsk.core.NurbsSurface):
                lines.append('    NurbsSurface (freeform)')

            # Dump loops and edges
            lines.append('    Loops: {}'.format(face.loops.count))
            for li in range(face.loops.count):
                loop = face.loops.item(li)
                co_edges = list(loop.coEdges)
                lines.append('      Loop {}: isOuter={}, coEdges={}'.format(
                    li, loop.isOuter, len(co_edges)
                ))
                for ci, co_edge in enumerate(co_edges):
                    edge = co_edge.edge
                    edge_geom = edge.geometry
                    edge_type = type(edge_geom).__name__
                    opposed = co_edge.isOpposedToEdge

                    detail = ''
                    if isinstance(edge_geom, adsk.core.Line3D):
                        sp = edge.startVertex.geometry
                        ep = edge.endVertex.geometry
                        detail = ' start=({:.4f},{:.4f},{:.4f}) end=({:.4f},{:.4f},{:.4f})'.format(
                            sp.x, sp.y, sp.z, ep.x, ep.y, ep.z)
                    elif isinstance(edge_geom, adsk.core.Arc3D):
                        detail = ' center=({:.4f},{:.4f},{:.4f}) r={:.4f}'.format(
                            edge_geom.center.x, edge_geom.center.y, edge_geom.center.z,
                            edge_geom.radius)
                    elif isinstance(edge_geom, adsk.core.Circle3D):
                        detail = ' center=({:.4f},{:.4f},{:.4f}) r={:.4f}'.format(
                            edge_geom.center.x, edge_geom.center.y, edge_geom.center.z,
                            edge_geom.radius)
                    elif isinstance(edge_geom, adsk.core.NurbsCurve3D):
                        detail = ' (nurbs curve)'

                    lines.append('        Edge {}: {} opposed={}{}'.format(
                        ci, edge_type, opposed, detail
                    ))

            lines.append('')

        # Summarize face classification using the actual algorithm
        lines.append('  --- Sheet Normal Classification ---')

        # Collect all planar faces for grouping
        all_planar = []
        for fi2 in range(body.faces.count):
            face2 = body.faces.item(fi2)
            geom2 = face2.geometry
            if isinstance(geom2, adsk.core.Plane):
                n2 = geom2.normal
                o2 = geom2.origin
                all_planar.append({
                    'face': face2,
                    'normal': (n2.x, n2.y, n2.z),
                    'origin': (o2.x, o2.y, o2.z),
                    'area': face2.area,
                    'idx': fi2,
                })

        if not all_planar:
            lines.append('  NO planar faces found!')
        else:
            lines.append('  {} planar face(s) found'.format(len(all_planar)))

            # Group by normal
            normal_groups = _group_faces_by_normal(all_planar)
            lines.append('  {} normal group(s):'.format(len(normal_groups)))
            for ngi, ng in enumerate(sorted(normal_groups, key=lambda g: g['total_area'], reverse=True)):
                nn = ng['normal']
                lines.append('    Normal group {}: ({:.4f}, {:.4f}, {:.4f}), '
                             '{} faces, total area={:.4f} cm²{}'.format(
                                 ngi, nn[0], nn[1], nn[2],
                                 len(ng['faces']), ng['total_area'],
                                 ' <-- SHEET PLANE' if ngi == 0 else ''
                             ))
                for sf in ng['faces']:
                    lines.append('      Face {}: area={:.6f}'.format(
                        sf.get('idx', '?'), sf['area']
                    ))

            # Show height classification for the best group
            best = max(normal_groups, key=lambda g: g['total_area'])
            sn = best['normal']
            lines.append('')
            lines.append('  Sheet normal: ({:.4f}, {:.4f}, {:.4f})'.format(sn[0], sn[1], sn[2]))

            for sf in best['faces']:
                ox, oy, oz = sf['origin']
                sf['height'] = ox * sn[0] + oy * sn[1] + oz * sn[2]

            height_groups = _group_faces_by_level(best['faces'], key='height')
            heights = [h for h, _ in height_groups]
            highest_h = max(heights)
            lowest_h = min(heights)
            thickness = highest_h - lowest_h
            lines.append('  Highest level: {:.6f}'.format(highest_h))
            lines.append('  Lowest level: {:.6f}'.format(lowest_h))
            lines.append('  Thickness: {:.6f} cm = {:.4f} mm = {:.6f} in'.format(
                thickness, thickness * 10, thickness / 2.54
            ))

            # Determine machining top using pocket face outward normals
            high_faces = []
            low_faces = []
            pocket_list = []
            for level, group in height_groups:
                if abs(level - highest_h) < _LEVEL_TOL:
                    high_faces.extend(group)
                elif abs(level - lowest_h) < _LEVEL_TOL:
                    low_faces.extend(group)
                else:
                    pocket_list.extend([(level, f) for f in group])

            machining_top_level = highest_h  # default
            if pocket_list and thickness > _LEVEL_TOL:
                dot_sum = 0.0
                for _, pf in pocket_list:
                    face_obj = pf['face']
                    fn = pf['normal']
                    if face_obj.isParamReversed:
                        outward = (-fn[0], -fn[1], -fn[2])
                    else:
                        outward = fn
                    dot_sum += (outward[0] * sn[0] +
                                outward[1] * sn[1] +
                                outward[2] * sn[2])
                pockets_open_toward_high = dot_sum > 0
                machining_top_level = highest_h if pockets_open_toward_high else lowest_h
                lines.append('  Pocket normal dot sum: {:.4f} → pockets open toward {} level'.format(
                    dot_sum, 'high' if pockets_open_toward_high else 'low'))

            lines.append('  Machining top level: {:.6f}'.format(machining_top_level))

            # Profile face selection (matches _classify_faces logic)
            pockets_open_high = True  # default
            if pocket_list and thickness > _LEVEL_TOL:
                pockets_open_high = pockets_open_toward_high
            if pockets_open_high:
                mt_faces = high_faces
                bt_faces = low_faces
            else:
                mt_faces = low_faces
                bt_faces = high_faces
            if len(mt_faces) <= len(bt_faces):
                profile_side = 'machining-top'
                through_hole_side = 'bottom'
            else:
                profile_side = 'bottom'
                through_hole_side = 'machining-top'
            lines.append('  Profile face from {} ({} faces), through-holes from {} ({} faces)'.format(
                profile_side, len(mt_faces) if profile_side == 'machining-top' else len(bt_faces),
                through_hole_side, len(bt_faces) if profile_side == 'machining-top' else len(mt_faces)))

            lines.append('')
            lines.append('  Height-level groups: {}'.format(len(height_groups)))
            for hgi, (level, group) in enumerate(height_groups):
                face_indices = [f.get('idx', '?') for f in group]
                label = ''
                if abs(level - highest_h) < _LEVEL_TOL:
                    label = ' <-- HIGH'
                elif abs(level - lowest_h) < _LEVEL_TOL:
                    label = ' <-- LOW'

                if thickness > _LEVEL_TOL and abs(level - highest_h) > _LEVEL_TOL and abs(level - lowest_h) > _LEVEL_TOL:
                    depth = abs(machining_top_level - level)
                    label = ' <-- POCKET (depth={:.4f} cm = {:.4f} mm = {:.6f} in)'.format(
                        depth, depth * 10, depth / 2.54
                    )

                # Add machining-top / bottom annotation
                if abs(level - machining_top_level) < _LEVEL_TOL:
                    label += ' [MACHINING TOP]'
                elif abs(level - highest_h) < _LEVEL_TOL or abs(level - lowest_h) < _LEVEL_TOL:
                    label += ' [BOTTOM]'

                lines.append('    Group {}: level={:.6f}, faces={}{}'.format(
                    hgi, level, face_indices, label
                ))

        lines.append('')

    lines.append('=' * 70)
    lines.append('END OF DEBUG REPORT')
    lines.append('=' * 70)

    report = '\n'.join(lines)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(report)

    utils.log('Debug report written to: {}'.format(file_path))
