"""
Order of the paths of a G-code job: a nearest neighbour walk on a grid of the end points, followed by a 2-opt pass
(Or-opt for a single path) that only shortens the rapid travel.

A path is entered at its first or at its last point (the path is then cut in the reverse direction, as before), so
each path p has the 2 points 2p (first) and 2p + 1 (last). The point with the lowest id wins a tie, so the same input
gives the same order. Nothing here depends on scipy, the time is bounded by a count of steps, not by the clock.
"""
import math
from array import array

import numpy as np
import shapely


# the most cells of a grid
MAX_CELLS = 1 << 22


class PointGrid:
    """
    Grid of points (an (M, 2) array) for the nearest point that is still alive and for the k nearest points.
    The ids of the points are the rows of the array.
    """

    def __init__(self, points: np.ndarray, ids=None, xs=None, ys=None, per_cell: float = 2.0):
        """
        :param points: (M, 2) array
        :param ids:    optional array of the rows to put in the grid (the others are not in it)
        :param xs:     optional points[:, 0].tolist(), when the caller has it
        :param ys:     optional points[:, 1].tolist()
        """
        self.xs = points[:, 0].tolist() if xs is None else xs
        self.ys = points[:, 1].tolist() if ys is None else ys
        sub = points if ids is None else points[ids]
        count = len(sub)
        x0, y0 = sub.min(axis=0).tolist()
        x1, y1 = sub.max(axis=0).tolist()
        self.x0 = x0
        self.y0 = y0
        w = max(x1 - x0, 0.0)
        h = max(y1 - y0, 0.0)
        cells = max(count / per_cell, 1.0)
        if w > 0 and h > 0:
            size = math.sqrt(w * h / cells)
            # a very thin box: at most `cells` cells along the long side
            size = max(size, max(w, h) / cells)
        elif w > 0 or h > 0:
            size = max(w, h) / cells
        else:
            size = 1.0
        # points in groups (holes in the board, text): smaller cells, so the cells that are used have few points
        for __ in range(3):
            self._build(sub, ids, size, w, h)
            used = sum(1 for c in self.cells if c)
            if count / used <= 2.5 * per_cell or self.nx * self.ny > MAX_CELLS // 4:
                break
            size /= math.sqrt(count / used / per_cell)
        self.pts = points

    def _build(self, sub, ids, size, w, h):
        self.size = size
        self.nx = int(w / size) + 1
        self.ny = int(h / size) + 1
        inv = 1.0 / size
        cx = np.minimum(((sub[:, 0] - self.x0) * inv).astype(np.int64), self.nx - 1)
        cy = np.minimum(((sub[:, 1] - self.y0) * inv).astype(np.int64), self.ny - 1)
        cell = cy * self.nx + cx
        # point ids in each cell, ascending (a stable sort keeps the id order)
        order = np.argsort(cell, kind='stable')
        sorted_cells = cell[order]
        if ids is not None:
            order = np.asarray(ids)[order]
        # the cells that are used, not all the (many) cells
        used, starts = np.unique(sorted_cells, return_index=True)
        ends = starts[1:].tolist() + [len(order)]
        order = order.tolist()
        self.cells = [()] * (self.nx * self.ny)
        for c, lo, hi in zip(used.tolist(), starts.tolist(), ends):
            self.cells[c] = order[lo:hi]

    def _cell_of(self, x, y):
        ci = int((x - self.x0) / self.size)
        cj = int((y - self.y0) / self.size)
        return min(max(ci, 0), self.nx - 1), min(max(cj, 0), self.ny - 1)

    def _ring(self, ci, cj, r):
        """The cells at the Chebyshev distance r from the cell (ci, cj)."""
        nx, ny = self.nx, self.ny
        if r == 0:
            return [cj * nx + ci]
        out = []
        lo_i, hi_i = ci - r, ci + r
        lo_j, hi_j = cj - r, cj + r
        i0 = max(lo_i, 0)
        i1 = min(hi_i, nx - 1)
        if lo_j >= 0:
            out.extend(range(lo_j * nx + i0, lo_j * nx + i1 + 1))
        if hi_j < ny:
            out.extend(range(hi_j * nx + i0, hi_j * nx + i1 + 1))
        j0 = max(lo_j + 1, 0)
        j1 = min(hi_j - 1, ny - 1)
        if lo_i >= 0:
            out.extend(j * nx + lo_i for j in range(j0, j1 + 1))
        if hi_i < nx:
            out.extend(j * nx + hi_i for j in range(j0, j1 + 1))
        return out

    def nearest_alive(self, x, y, alive):
        """
        The nearest point whose alive[id] is true; the lowest id among the points at the same distance. Dead points
        are dropped from the cells on the way.

        :return: point id, or -1 when no point is alive
        """
        xs, ys, cells = self.xs, self.ys, self.cells
        ci, cj = self._cell_of(x, y)
        size = self.size
        best = -1
        best_d = 0.0
        max_r = max(self.nx, self.ny)
        r = 0
        while r <= max_r:
            for c in self._ring(ci, cj, r):
                ids = cells[c]
                if not ids:
                    continue
                dead = False
                for g in ids:
                    if not alive[g]:
                        dead = True
                        continue
                    dx = xs[g] - x
                    dy = ys[g] - y
                    d = dx * dx + dy * dy
                    if best < 0 or d < best_d or (d == best_d and g < best):
                        best = g
                        best_d = d
                if dead:
                    cells[c] = [g for g in ids if alive[g]]
            # a point in a ring farther than r is at least r * size away
            if best >= 0 and best_d <= (r * size) ** 2:
                break
            r += 1
        return best

    def knn(self, x, y, k, skip=-1):
        """The k nearest points (all points, dead or alive) by (distance, id), without the point `skip`."""
        xs, ys, cells = self.xs, self.ys, self.cells
        ci, cj = self._cell_of(x, y)
        size = self.size
        found = []
        max_r = max(self.nx, self.ny)
        r = 0
        while r <= max_r:
            for c in self._ring(ci, cj, r):
                for g in cells[c]:
                    if g != skip:
                        dx = xs[g] - x
                        dy = ys[g] - y
                        found.append((dx * dx + dy * dy, g))
            if len(found) >= k:
                found.sort()
                if found[k - 1][0] <= (r * size) ** 2:
                    break
            r += 1
        found.sort()
        return [g for __, g in found[:k]]

    def knn_all(self, k):
        """
        The k nearest points (without itself, by distance then id) of each point of the grid, which has all the
        points (no ids). The points of a cell are done together with the points of the cells around it; a point
        whose k-th point is not nearer than the border of those cells is done by knn().

        :return: list of lists of ids
        """
        pts = self.pts
        px = pts[:, 0]
        py = pts[:, 1]
        nx, ny, size = self.nx, self.ny, self.size
        cells = self.cells
        out = [None] * len(pts)
        slow = []
        for cj in range(ny):
            for ci in range(nx):
                ids = cells[cj * nx + ci]
                if not ids:
                    continue
                i0, i1 = max(ci - 1, 0), min(ci + 2, nx)
                j0, j1 = max(cj - 1, 0), min(cj + 2, ny)
                cand = []
                for j in range(j0, j1):
                    for i in range(i0, i1):
                        cand.extend(cells[j * nx + i])
                if len(cand) <= k or len(cand) * len(ids) > 1000000:
                    slow.extend(ids)
                    continue
                cand = np.sort(np.asarray(cand))
                q = np.asarray(ids)
                qx = px[q]
                qy = py[q]
                d = (qx[:, None] - px[cand][None, :]) ** 2 + (qy[:, None] - py[cand][None, :]) ** 2
                d[q[:, None] == cand[None, :]] = np.inf
                near = np.argsort(d, axis=1, kind='stable')[:, :k]
                dk = np.take_along_axis(d, near, axis=1)[:, -1]
                # the distance to the border of the block of cells, where there are cells beyond
                margin = np.full(len(q), np.inf)
                if ci > 0:
                    margin = np.minimum(margin, qx - (self.x0 + i0 * size))
                if i1 < nx:
                    margin = np.minimum(margin, (self.x0 + i1 * size) - qx)
                if cj > 0:
                    margin = np.minimum(margin, qy - (self.y0 + j0 * size))
                if j1 < ny:
                    margin = np.minimum(margin, (self.y0 + j1 * size) - qy)
                good = (dk < margin ** 2) & np.isfinite(dk)
                result = cand[near].tolist()
                for n, g in enumerate(good.tolist()):
                    if g:
                        out[ids[n]] = result[n]
                    else:
                        slow.append(ids[n])
        for t in slow:
            out[t] = self.knn(self.xs[t], self.ys[t], k, skip=t)
        return out


def walk_nearest(points: np.ndarray, start=(0.0, 0.0)):
    """
    Greedy nearest neighbour walk over the paths. points is a (2N, 2) array, the points 2p and 2p + 1 are the 2 ends
    of the path p. From the current position the nearest end of a path that was not visited is taken (the lowest id
    on a tie), then the walk goes on from the other end of that path.

    :return: list of the point ids where the paths are entered, in the order of the visit
    """
    total = len(points)
    if total == 0:
        return []
    alive = bytearray(b'\x01') * total
    grid = PointGrid(points)
    grid_pts = total
    left = total
    order = []
    xs, ys = grid.xs, grid.ys
    cx, cy = start
    while left:
        # fewer live points than half of the grid: a new grid for the points that are left (the rings stay short)
        if left * 2 < grid_pts and grid_pts > 256:
            keep = np.flatnonzero(np.frombuffer(alive, dtype=np.uint8))
            grid = PointGrid(points, ids=keep, xs=xs, ys=ys)
            grid_pts = len(keep)
        best = grid.nearest_alive(cx, cy, alive)
        order.append(best)
        path = best >> 1
        alive[2 * path] = 0
        alive[2 * path + 1] = 0
        left -= 2
        other = best ^ 1
        cx = xs[other]
        cy = ys[other]
    return order


def improve_order(points, entries, start=(0.0, 0.0), max_rev=None, max_work=None, k=10, oropt_window=1000,
                  use_oropt=True):
    """
    Shortens the rapid travel of an order of the paths: 2-opt (the part of the order between 2 paths is reversed, the
    paths in it are cut in the opposite direction) and Or-opt (a path is moved to another place), both with the k
    nearest points of each point as candidates. The first move is from `start`, the end is free. Only a move that
    shortens the travel is made; the work is bounded by counts (max_work), so the result does not depend on the speed
    of the machine.

    :param points:      (2N, 2) array, the points 2p and 2p + 1 are the first and the last point of the path p
    :param entries:     point ids where the paths are entered, in the order of the visit (see walk_nearest())
    :param max_rev:     the most paths in a part that is reversed (default: all)
    :param max_work:    the most steps (default: 8 for each path, the pass is at its end by 4)
    :param oropt_window the farthest place (in paths) where Or-opt puts a path
    :return:            the new list of entry point ids
    """
    n = len(entries)
    if n < 3:
        return list(entries)
    N = len(points) // 2
    # the path N is a point at `start` that stays first
    P = np.vstack([points, [list(start), list(start)]])
    seq = [e >> 1 for e in entries]
    ori = [0] * N
    for e in entries:
        ori[e >> 1] = e & 1
    if max_rev is None:
        max_rev = n
    X = P[:, 0].tolist()
    Y = P[:, 1].tolist()
    k = min(k, len(P) - 1)
    nb = PointGrid(P, xs=X, ys=Y, per_cell=5.0).knn_all(k)
    hyp = math.hypot
    seq = array('i', [N] + list(seq))
    ori = array('b', ori + [0])
    m = n + 1
    pos = array('i', [0]) * (N + 1)
    seq_np = np.frombuffer(seq, dtype=np.int32)
    ori_np = np.frombuffer(ori, dtype=np.int8)
    pos_np = np.frombuffer(pos, dtype=np.int32)
    pos_np[seq_np] = np.arange(m, dtype=np.int32)
    if max_work is None:
        max_work = 8 * n
    active = list(range(n - 1, -1, -1))
    inq = bytearray(b'\x01') * (N + 1)
    work = 0
    eps = 1e-9

    def D(u):
        if u + 1 >= m:
            return 0.0
        pu = seq[u]
        pv = seq[u + 1]
        a = 2 * pu + 1 - ori[pu]
        b = 2 * pv + ori[pv]
        return hyp(X[a] - X[b], Y[a] - Y[b])

    def push(p):
        if not inq[p]:
            inq[p] = 1
            active.append(p)

    while active and work < max_work:
        a = active.pop()
        inq[a] = 0
        improved = True
        while improved and work < max_work:
            improved = False
            work += 1
            i = pos[a]
            for side in (0, 1):
                if side == 0:
                    t = 2 * a + 1 - ori[a]
                    u0 = i
                else:
                    t = 2 * a + ori[a]
                    u0 = i - 1
                    if u0 < 0:
                        continue
                g1 = D(u0)
                tx = X[t]
                ty = Y[t]
                for c in nb[t]:
                    if hyp(tx - X[c], ty - Y[c]) >= g1:
                        break
                    q = c >> 1
                    if q == a:
                        continue
                    if side == 0:
                        if c != 2 * q + 1 - ori[q]:
                            continue
                        v0 = pos[q]
                    else:
                        if q == N or c != 2 * q + ori[q]:
                            continue
                        v0 = pos[q] - 1
                    u, v = (u0, v0) if u0 < v0 else (v0, u0)
                    if u == v or v - u > max_rev:
                        continue
                    pu = seq[u]
                    pv = seq[v]
                    xu = 2 * pu + 1 - ori[pu]
                    xv = 2 * pv + 1 - ori[pv]
                    g = D(u) + D(v) - hyp(X[xu] - X[xv], Y[xu] - Y[xv])
                    if v + 1 < m:
                        q1 = seq[u + 1]
                        q2 = seq[v + 1]
                        e1 = 2 * q1 + ori[q1]
                        e2 = 2 * q2 + ori[q2]
                        g -= hyp(X[e1] - X[e2], Y[e1] - Y[e2])
                    if g > eps:
                        seg = seq_np[u + 1:v + 1][::-1].copy()
                        seq_np[u + 1:v + 1] = seg
                        pos_np[seg] = np.arange(u + 1, v + 1, dtype=np.int32)
                        ori_np[seg] ^= 1
                        push(seq[u]) if seq[u] != N else None
                        push(seq[u + 1])
                        push(seq[v])
                        if v + 1 < m:
                            push(seq[v + 1])
                        improved = True
                        break
                if improved:
                    break
            if improved or not use_oropt:
                continue
            # ---- or-opt of the single path a
            i = pos[a]
            pp = seq[i - 1]
            prev = 2 * pp + 1 - ori[pp]
            rem = D(i - 1) + D(i)
            if i + 1 < m:
                pn = seq[i + 1]
                nx = 2 * pn + ori[pn]
                rem -= hyp(X[prev] - X[nx], Y[prev] - Y[nx])
            if rem <= eps:
                continue
            ea0 = 2 * a + ori[a]
            xa0 = 2 * a + 1 - ori[a]
            for t, tmode in ((ea0, 0), (xa0, 1)):
                tx = X[t]
                ty = Y[t]
                for c in nb[t]:
                    if hyp(tx - X[c], ty - Y[c]) >= rem:
                        break
                    q = c >> 1
                    if q == a:
                        continue
                    j = pos[q]
                    if abs(j - i) > oropt_window:
                        continue
                    if c == 2 * q + 1 - ori[q]:
                        flip = tmode == 1
                        after = j
                    elif q != N and c == 2 * q + ori[q]:
                        flip = tmode == 0
                        after = j - 1
                    else:
                        continue
                    if after == i or after == i - 1:
                        continue
                    ea, xa = (xa0, ea0) if flip else (ea0, xa0)
                    pq = seq[after]
                    xp = 2 * pq + 1 - ori[pq]
                    ins = hyp(X[xp] - X[ea], Y[xp] - Y[ea])
                    if after + 1 < m:
                        pr = seq[after + 1]
                        en = 2 * pr + ori[pr]
                        ins += hyp(X[xa] - X[en], Y[xa] - Y[en]) - D(after)
                    if rem - ins > eps:
                        if flip:
                            ori[a] ^= 1
                        k0 = after if after < i else after - 1
                        lo = min(i, k0 + 1)
                        hi = max(i, k0 + 1)
                        if i < k0 + 1:
                            seq_np[i:k0 + 1] = seq_np[i + 1:k0 + 2].copy()
                        else:
                            seq_np[k0 + 2:i + 1] = seq_np[k0 + 1:i].copy()
                        seq[k0 + 1] = a
                        pos_np[seq_np[lo:hi + 1]] = np.arange(lo, hi + 1, dtype=np.int32)
                        push(seq[k0]) if seq[k0] != N else None
                        push(a)
                        if k0 + 2 < m:
                            push(seq[k0 + 2])
                        if lo - 1 >= 1:
                            push(seq[lo - 1])
                        if hi + 1 < m:
                            push(seq[hi + 1])
                        improved = True
                        break
                if improved:
                    break
    return [2 * p + o for p, o in zip(seq_np[1:].tolist(), ori_np[seq_np[1:]].tolist())]


def path_end_points(paths):
    """
    The first and the last point (x, y) of each path.

    :param paths: list of objects with coords (LineString, LinearRing, ...); None is left out
    :return:      (kept paths, (2M, 2) float array; the points 2p and 2p + 1 are the ends of the kept path p). A path
                  whose coords cannot be read or are empty is left out.
    """
    paths = [g for g in paths if g is not None]
    if not paths:
        return [], np.zeros((0, 2))
    arr = np.empty(len(paths), dtype=object)
    arr[:] = paths
    try:
        # all the paths are lines with points: the ends of all at once
        if not np.all(np.isin(shapely.get_type_id(arr), (1, 2))):
            raise ValueError
        counts = shapely.get_num_coordinates(arr)
        if not counts.all():
            raise ValueError
        coords = shapely.get_coordinates(arr)
        last = np.cumsum(counts) - 1
        first = last - counts + 1
        points = np.empty((2 * len(paths), 2))
        points[0::2] = coords[first]
        points[1::2] = coords[last]
        return paths, points
    except Exception:
        pass
    kept = []
    rows = []
    for g in paths:
        try:
            c = g.coords
            a = c[0]
            b = c[-1]
            rows.append((a[0], a[1]))
            rows.append((b[0], b[1]))
            kept.append(g)
        except Exception:
            pass
    return kept, np.asarray(rows, dtype=np.float64).reshape(-1, 2)


def order_paths(paths, start=(0.0, 0.0), improve=True):
    """
    The paths in the order to cut them, to keep the rapid travel short: a nearest neighbour walk from `start`, then
    improve_order(). The same input gives the same output.

    :param paths:   list of shapely lines (a path can be cut from its first or its last point)
    :param start:   where the tool is at the start
    :param improve: False: only the walk
    :return:        list of (entry point (x, y), path): the entry point is the first or the last point of the path;
                    when it is the last one (and the path is not closed) the path has to be cut in reverse. Empty
                    list when no path has points.
    """
    paths, points = path_end_points(paths)
    if not paths:
        return []
    entries = walk_nearest(points, start)
    if improve:
        entries = improve_order(points, entries, start)
    xs = points[:, 0].tolist()
    ys = points[:, 1].tolist()
    out = []
    for e in entries:
        # a closed path is entered at its first point
        if xs[e] == xs[e ^ 1] and ys[e] == ys[e ^ 1]:
            e &= ~1
        out.append(((xs[e], ys[e]), paths[e >> 1]))
    return out


def order_points(points, start=(0.0, 0.0), improve=True):
    """
    The order to visit single points (drills): the same walk and travel improvement as order_paths().

    :param points:  (M, 2) array
    :param start:   where the tool is at the start
    :param improve: False: only the walk
    :return:        list of the row numbers of the points, in the order of the visit
    """
    points = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    if not len(points):
        return []
    # a path with the same point at both ends
    doubled = np.repeat(points, 2, axis=0)
    entries = walk_nearest(doubled, start)
    if improve:
        entries = improve_order(doubled, entries, start)
    return [e >> 1 for e in entries]
