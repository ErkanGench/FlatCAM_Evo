"""
Flattening helpers: turn ezdxf paths into plain 2D coordinate lists.
"""
import logging

import numpy as np
import shapely
from ezdxf.math import BoundingBox
from shapely import STRtree
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid

log = logging.getLogger('base')

# Default maximum distance (drawing units) between a curve and its flattened version.
# dxf_to_shapes() derives the real value from the drawing units ($INSUNITS).
FLATTEN_TOLERANCE = 0.01
# Relative floor for the tolerance so that huge curves keep a finite segment count.
RELATIVE_TOLERANCE = 1e-7
# Minimum flattened segments per Bezier piece (4 pieces per full circle).
MIN_SEGMENTS_PER_PIECE = 4

def path_to_rings(path, segments=MIN_SEGMENTS_PER_PIECE, tolerance=FLATTEN_TOLERANCE):
    """
    Flatten an ezdxf Path (maybe with several sub-paths) to 2D coordinate lists.

    :param path:        ezdxf.path.Path
    :param segments:    minimum number of segments per curve piece
    :param tolerance:   maximum curve-to-polyline distance in drawing units
    :return:            list of lists of (x, y) tuples, one list per sub-path with at least 2 points
    """
    result = []
    for sub in path.sub_paths():
        vertices = list(sub.control_vertices())
        if len(vertices) < 2:
            continue
        box = BoundingBox(vertices)
        size = max(box.size.x, box.size.y)
        distance = max(tolerance, size * RELATIVE_TOLERANCE)
        points = [(v.x, v.y) for v in sub.flattening(distance, segments=segments)]
        if sub.is_closed and points and points[0] != points[-1]:
            points.append(points[0])
        if len(points) >= 2:
            result.append(points)
    return result


def rings_to_polygons(rings):
    """
    Build filled shapes from closed contours with the even-odd rule: a ring inside another
    one is a hole, a ring inside that hole is filled again.

    :param rings:   list of coordinate lists
    :return:        list of Polygons
    """
    faces = []
    for ring in rings:
        if len(ring) < 4:
            continue
        face = Polygon(ring)
        if not face.is_valid:
            face = make_valid(face)
        faces.extend(g for g in getattr(face, 'geoms', [face]) if g.geom_type == 'Polygon' and g.area > 0)
    if not faces:
        return []

    # nesting depth of each face = number of other faces around it (one spatial query, no XOR chain)
    # bbox pairs first, then keep only boxes fully inside another box, then the exact test
    probe_idx, face_idx = STRtree(faces).query(faces)
    box = shapely.bounds(faces)
    inside = (probe_idx != face_idx) & np.all(box[probe_idx, :2] >= box[face_idx, :2], axis=1) & \
        np.all(box[probe_idx, 2:] <= box[face_idx, 2:], axis=1)
    probe_idx, face_idx = probe_idx[inside], face_idx[inside]
    faces_arr = np.asarray(faces, dtype=object)
    exact = shapely.within(faces_arr[probe_idx], faces_arr[face_idx])
    probe_idx, face_idx = probe_idx[exact], face_idx[exact]
    depth = np.bincount(probe_idx, minlength=len(faces))

    # an odd face is a hole of the smallest face around it that has one level less
    holes = {i: [] for i in range(len(faces)) if depth[i] % 2 == 0}
    parent = {}
    for p, f in zip(probe_idx, face_idx):
        if depth[p] % 2 == 1 and depth[f] == depth[p] - 1:
            parent[p] = f
    for h, s in parent.items():
        holes[s].append(faces[h])

    result = []
    for s, inner in holes.items():
        shell = faces[s]
        if inner:
            shape = Polygon(shell.exterior.coords, [h.exterior.coords for h in inner])
            if not shape.is_valid:
                shape = shell.difference(unary_union(inner))
            shell = shape
        result.extend(g for g in getattr(shell, 'geoms', [shell]) if g.geom_type == 'Polygon' and g.area > 0)
    return result
