"""Geometry for the move selection preview."""

from shapely import Polygon


def selection_corners(bounds):
    xmin = min(b[0] for b in bounds)
    ymin = min(b[1] for b in bounds)
    xmax = max(b[2] for b in bounds)
    ymax = max(b[3] for b in bounds)
    return [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]


def translated_box(coords, offset):
    return Polygon([(x + offset[0], y + offset[1]) for x, y in coords])


def selection_shape(shape, units, as_line):
    if units.upper() == 'MM':
        groove = shape.buffer(-0.1)
        shape = groove.buffer(0.2) if not groove.is_empty else shape.buffer(0.2)
    else:
        groove = shape.buffer(-0.00393)
        shape = groove.buffer(0.00787) if not groove.is_empty else shape.buffer(0.00787)
    return shape.exterior if as_line else shape
