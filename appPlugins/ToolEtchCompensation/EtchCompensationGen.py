"""Copper and aperture compensation. No Qt or application objects here."""

from copy import deepcopy
import math

from shapely.ops import unary_union


def compensate_geometry(geometry, apertures, offset, circle_steps):
    """Return buffered copper and copied, compensated aperture data."""
    new_solid_geometry = []
    for poly in geometry:
        new_solid_geometry.append(poly.buffer(offset, int(circle_steps)))
    new_solid_geometry = unary_union(new_solid_geometry)

    new_apertures = deepcopy(apertures)
    for ap in new_apertures:
        ap_type = new_apertures[ap]['type']
        for k in new_apertures[ap]:
            if ap_type == 'R' or ap_type == 'O':
                if k == 'width' or k == 'height':
                    new_apertures[ap][k] += offset
            else:
                if k == 'size' or k == 'width' or k == 'height':
                    new_apertures[ap][k] += offset

            if k == 'geometry':
                for geo_el in new_apertures[ap][k]:
                    if 'solid' in geo_el:
                        geo_el['solid'] = geo_el['solid'].buffer(offset, int(circle_steps))

    # Recompute rectangular and obround aperture diagonals after updating their dimensions.
    for ap in new_apertures:
        ap_type = new_apertures[ap]['type']
        for k in new_apertures[ap]:
            if ap_type == 'R' or ap_type == 'O':
                if k == 'size':
                    new_apertures[ap][k] = math.sqrt(
                        new_apertures[ap]['width'] ** 2 + new_apertures[ap]['height'] ** 2)

    return new_solid_geometry, new_apertures
