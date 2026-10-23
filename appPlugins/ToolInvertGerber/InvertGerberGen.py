"""Geometry computation for the Invert Gerber plugin. No Qt here."""

from shapely import box


def invert_geometry(geometry, bounds, margin, circle_steps, join_style):
    """Subtract the source copper from its buffered bounding box."""
    result = box(*bounds).buffer(margin, quad_segs=circle_steps, join_style=join_style)
    for poly in geometry:
        result = result.difference(poly)
    return result
