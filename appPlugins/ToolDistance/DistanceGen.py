"""Distance math and geometry-only snap selection."""

import math
from shapely import Point, MultiLineString, Polygon
from shapely.strtree import STRtree
from appParsers.feature_access import iter_features
from camlib import flatten_shapely_geometry


def measurement_angle(dx, dy):
    angle = math.degrees(math.atan2(dy, dx))
    if angle < 0:
        angle += 360
    return angle


def point_deltas(pos, previous):
    return pos[0] - previous[0], pos[1] - previous[1]


def point_distance(pos, previous):
    dx, dy = point_deltas(pos, previous)
    return math.sqrt(dx ** 2 + dy ** 2)


def app_snap_centers(kind, features, current_pt):
    clicked_geo = []
    for feature in features:
        # A clear (LPC) feature is not a pad.
        if feature.polarity != 'dark' or not feature.solid.covers(current_pt):
            continue
        if kind == 'gerber':
            if feature.kind == 'flash':
                clicked_geo.append(feature.follow)
        else:
            clicked_geo.append(feature.solid.centroid)
    return clicked_geo


def closest_center(points, current_pt):
    return min(points, key=current_pt.distance)


def exc_snap_position(geometry, pos):
    current_pt = Point(pos)
    if isinstance(geometry, MultiLineString):
        radius = geometry.geoms[0].length / 2.0
        center_pt = geometry.centroid
        geo_buffered = center_pt.buffer(radius)
        if geo_buffered.covers(current_pt):
            pos = (center_pt.x, center_pt.y)
    elif isinstance(geometry, Polygon):
        geo_buffered = geometry.buffer(0)
        center_pt = geo_buffered.centroid
        if geo_buffered.covers(current_pt):
            pos = (center_pt.x, center_pt.y)
    return pos


class SnapIndex:
    """A session snapshot: footprint containment first, nearest center second.

    ``covered_by`` includes the exact footprint boundary. Gerber copper is queried
    separately: aperture records don't preserve the global polarity order.
    """

    def __init__(self, footprints, centers, copper=None):
        self.tree = STRtree(footprints)
        self.centers = centers
        self.copper = None if copper is None else STRtree(copper)
        self.editor_shapes: list | None = None

    def closest(self, current_pt):
        if self.copper is not None and not self.copper.query(current_pt, predicate='covered_by').size:
            return None
        hits = self.tree.query(current_pt, predicate='covered_by')
        if not hits.size:
            return None
        # Stable tie breaking, without constructing another tree for a handful of hits.
        if self.editor_shapes is not None:
            # AppRTreeStorage.remove() leaves a tombstone without changing list length.
            # Check only spatial hits, not every stored drill on every hover.
            live_hits = []
            for i in hits:
                storage, shape = self.editor_shapes[i]
                obj_index = storage.indexes.get(id(shape))
                if obj_index is not None and storage.objects[obj_index] is shape:
                    live_hits.append(i)
            hits = live_hits
        index = min(hits, key=lambda i: (current_pt.distance(self.centers[i]), int(i)), default=None)
        return self.centers[index] if index is not None else None


def app_snap_index(obj):
    footprints, centers = [], []
    for feature in iter_features(obj):
        if feature.polarity != 'dark' or feature.solid.is_empty:
            continue
        if obj.kind == 'gerber' and (feature.kind != 'flash' or not isinstance(feature.follow, Point)):
            continue
        footprints.append(feature.solid)
        centers.append(feature.follow if obj.kind == 'gerber' else feature.solid.centroid)
    copper = flatten_shapely_geometry(obj.solid_geometry) if obj.kind == 'gerber' else None
    return SnapIndex(footprints, centers, copper=copper)


def editor_snap_index(source, storage_dict):
    footprints, centers = [], []
    editor_shapes = []
    for storage in storage_dict.values():
        shapes = storage.get_objects() if source == 'exc_editor' else storage.get('geometry', ())
        for shape in shapes:
            geometry = shape.geo
            if source == 'exc_editor':
                if isinstance(geometry, MultiLineString) and len(geometry.geoms):
                    center = geometry.centroid
                    solid = center.buffer(geometry.geoms[0].length / 2.0)
                elif isinstance(geometry, Polygon):
                    solid = geometry.buffer(0)
                    center = solid.centroid
                else:
                    continue
            else:
                # The editor displays edited solids. LPC imports are already composed
                # into regions by AppGerberEditor.build_edit_tools().
                solid, center = geometry.get('solid'), geometry.get('follow')
                if not isinstance(center, Point) or solid is None:
                    continue
            if not solid.is_empty and not center.is_empty:
                footprints.append(solid)
                centers.append(center)
                if source == 'exc_editor':
                    editor_shapes.append((storage, shape))
    index = SnapIndex(footprints, centers)
    if source == 'exc_editor':
        index.editor_shapes = editor_shapes
    return index
