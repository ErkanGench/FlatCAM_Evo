"""Distance math and geometry-only snap selection."""

import math
from shapely import Point, MultiLineString, Polygon
from shapely.strtree import STRtree


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
        if feature.polarity != 'dark' or not current_pt.within(feature.solid):
            continue
        if kind == 'gerber':
            if feature.kind == 'flash':
                clicked_geo.append(feature.follow)
        else:
            clicked_geo.append(feature.solid.centroid)
    return clicked_geo


def closest_center(points, current_pt):
    tree = STRtree(points)
    closest_pt = points[int(tree.nearest(current_pt))]
    assert isinstance(closest_pt, Point)
    return closest_pt


def exc_snap_position(geometry, pos):
    current_pt = Point(pos)
    if isinstance(geometry, MultiLineString):
        radius = geometry.geoms[0].length / 2.0
        center_pt = geometry.centroid
        geo_buffered = center_pt.buffer(radius)
        if current_pt.within(geo_buffered):
            pos = (center_pt.x, center_pt.y)
    elif isinstance(geometry, Polygon):
        geo_buffered = geometry.buffer(0)
        center_pt = geo_buffered.centroid
        if current_pt.within(geo_buffered):
            pos = (center_pt.x, center_pt.y)
    return pos
