"""Point-to-point measurement math."""

import math
from shapely import Point, MultiPolygon
from shapely.ops import nearest_points, unary_union


def measurement_points(first, second, center=False, normalize=True, drills=False):
    geometry = []
    for geo in (first, second):
        if drills:
            xmin, ymin, xmax, ymax = geo.bounds
            radius = (xmax - xmin) / 2
            geo = Point(xmin + radius, ymin + radius).buffer(radius)
        elif normalize and isinstance(geo, list):
            try:
                geo = MultiPolygon(geo)
            except Exception:
                geo = unary_union(geo)
        geometry.append(geo)
    if not center:
        return nearest_points(*geometry)
    centers = []
    for geo in geometry:
        xmin, ymin, xmax, ymax = geo.bounds
        centers.append(Point((xmin + (xmax - xmin) / 2, ymin + (ymax - ymin) / 2)))
    return tuple(centers)


def update_angle(dx, dy):
    angle = math.degrees(math.atan2(dy, dx))
    if angle < 0:
        angle += 360
    return angle


def update_deltas(first_pt, second_pt):
    return first_pt.x - second_pt.x, first_pt.y - second_pt.y


def update_distance(dx, dy):
    return math.sqrt(dx ** 2 + dy ** 2)


def update_half_distance(first_pos, last_pos, dx, dy):
    return min(first_pos.x, last_pos.x) + (abs(dx) / 2), min(first_pos.y, last_pos.y) + (abs(dy) / 2)
