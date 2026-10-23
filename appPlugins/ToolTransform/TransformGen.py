"""Bounds used by the transformation reference selection."""

import numpy as np


def bounds_center(bounds):
    xmin, ymin, xmax, ymax = bounds
    return (xmax + xmin) * 0.5, (ymax + ymin) * 0.5


def alt_bounds(obj_list):
    """Return recursive bounds, skipping CNC jobs and non-finite geometry bounds."""
    def bounds_rec(lst):
        minx = np.inf
        miny = np.inf
        maxx = -np.inf
        maxy = -np.inf
        try:
            for obj in lst:
                if obj.kind != 'cncjob':
                    minx_, miny_, maxx_, maxy_ = bounds_rec(obj)
                    if not all(np.isfinite((minx_, miny_, maxx_, maxy_))):
                        continue
                    minx = min(minx, minx_)
                    miny = min(miny, miny_)
                    maxx = max(maxx, maxx_)
                    maxy = max(maxy, maxy_)
            return minx, miny, maxx, maxy
        except TypeError:
            return lst.bounds()

    return bounds_rec(obj_list)
