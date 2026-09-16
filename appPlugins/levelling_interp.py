#!/usr/bin/env python
# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing          #
# Pure interpolation helpers for the autolevelling feature.  #
#                                                              #
# No Qt imports, no app imports - standard library only, so   #
# these functions can be unit tested without the GUI stack.   #
# ##########################################################

import bisect
import math


def build_bilinear_grid(points, tol=1e-6):
    """
    Build a rectangular bilinear-interpolation grid out of a cloud of
    probed (x, y, height) points.

    X values within `tol` of each other are grouped into a single grid
    column, and the same is done for Y values into grid rows (probe
    coordinates are rounded by dec_format, so small floating point noise
    like 10.0 vs 10.0000001 must still land in the same column/row).

    :param points: list of (x, y, height) tuples, in any order.
    :param tol: tolerance used to group close X/Y values together.
    :return: a tuple (xs, ys, grid) where xs and ys are sorted ascending
        lists of the grouped X/Y values and grid[j][i] is the height at
        (xs[i], ys[j]); or None if the points do not form a full
        rectangular grid (missing cell, duplicate cell, fewer than 2
        distinct X or Y values, or a point that does not snap to any
        group).
    """
    if not points:
        return None

    xs = _group_values(sorted(set(p[0] for p in points)), tol)
    ys = _group_values(sorted(set(p[1] for p in points)), tol)

    if len(xs) < 2 or len(ys) < 2:
        return None

    grid = [[None] * len(xs) for _ in range(len(ys))]

    for x, y, z in points:
        i = _snap_index(xs, x, tol)
        j = _snap_index(ys, y, tol)
        if i is None or j is None:
            return None
        if grid[j][i] is not None:
            # duplicate cell
            return None
        grid[j][i] = z

    for row in grid:
        for cell in row:
            if cell is None:
                # missing cell
                return None

    return xs, ys, grid


def _group_values(sorted_unique_values, tol):
    """
    Group sorted unique values that lie within `tol` of each other,
    collapsing each group to its mean.

    :param sorted_unique_values: ascending list of unique values.
    :param tol: grouping tolerance.
    :return: ascending list of grouped (mean) values.
    """
    groups = []
    current = []
    for v in sorted_unique_values:
        if current and (v - current[0]) > tol:
            groups.append(sum(current) / len(current))
            current = []
        current.append(v)
    if current:
        groups.append(sum(current) / len(current))
    return groups


def _snap_index(grouped_values, value, tol):
    """
    Find the index of the grouped value that `value` belongs to.

    :param grouped_values: ascending list of grouped values.
    :param value: value to snap.
    :param tol: grouping tolerance.
    :return: index into grouped_values, or None if no group is within tol.
    """
    idx = bisect.bisect_left(grouped_values, value)
    candidates = []
    if 0 <= idx < len(grouped_values):
        candidates.append(idx)
    if 0 <= idx - 1 < len(grouped_values):
        candidates.append(idx - 1)

    best_idx = None
    best_dist = None
    for c in candidates:
        d = abs(grouped_values[c] - value)
        if d <= tol and (best_dist is None or d < best_dist):
            best_idx = c
            best_dist = d
    return best_idx


def bilinear_offset(grid_data, x, y):
    """
    Compute the bilinearly interpolated height offset at (x, y) using a
    grid built by build_bilinear_grid.

    x and y are clamped into the grid's range before interpolation.

    :param grid_data: tuple (xs, ys, grid) as returned by
        build_bilinear_grid.
    :param x: query X coordinate.
    :param y: query Y coordinate.
    :return: interpolated height offset (float).
    """
    xs, ys, grid = grid_data

    x = min(max(x, xs[0]), xs[-1])
    y = min(max(y, ys[0]), ys[-1])

    i = bisect.bisect_right(xs, x) - 1
    i = min(max(i, 0), len(xs) - 2)
    j = bisect.bisect_right(ys, y) - 1
    j = min(max(j, 0), len(ys) - 2)

    x0, x1 = xs[i], xs[i + 1]
    y0, y1 = ys[j], ys[j + 1]

    tx = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
    ty = 0.0 if y1 == y0 else (y - y0) / (y1 - y0)

    z00 = grid[j][i]
    z10 = grid[j][i + 1]
    z01 = grid[j + 1][i]
    z11 = grid[j + 1][i + 1]

    return (
        (1 - tx) * (1 - ty) * z00
        + tx * (1 - ty) * z10
        + (1 - tx) * ty * z01
        + tx * ty * z11
    )


def nearest_offset(points, x, y):
    """
    Return the height of the point in `points` nearest to (x, y).

    :param points: list of (x, y, height) tuples.
    :param x: query X coordinate.
    :param y: query Y coordinate.
    :return: height (float) of the nearest point. If two points are at
        equal distance, the first one in the list wins.
    :raises ValueError: if `points` is empty.
    """
    if not points:
        raise ValueError("nearest_offset() requires a non-empty list of points")

    best_z = None
    best_dist = None
    for px, py, pz in points:
        d = math.hypot(px - x, py - y)
        if best_dist is None or d < best_dist:
            best_dist = d
            best_z = pz
    return best_z
