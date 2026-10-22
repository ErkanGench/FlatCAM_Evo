"""Order-preserving spatial filtering of panel path snapping."""

from random import Random
from time import perf_counter

import pytest
from shapely.geometry import LineString, MultiLineString, box
from shapely.ops import linemerge, snap, unary_union

from appParsers import panelize_core as pc
from camlib import grace


TOLERANCE = 1e-7


def pairwise_merge(lines):
    """The original snapping loop, retained as an independent output/benchmark oracle."""
    lines = list(lines)
    for idx, line in enumerate(lines):
        for idx_s in range(idx + 1, len(lines)):
            result = snap(lines[idx_s], line, tolerance=TOLERANCE)
            if result and not result.is_empty:
                lines[idx_s] = result
    return unary_union(linemerge(lines))


def indexed_merge(lines):
    tools = {1: {'solid_geometry': list(lines)}}
    pc.merge_tool_lines(tools, snap_overlaps=True)
    return tools[1]['solid_geometry'][0]


def sparse_lines(pairs):
    return [LineString([(x, row * 10), (x, row * 10 + 1)])
            for row in range(pairs) for x in (0, TOLERANCE / 2)]


def test_snapping_skips_distant_pairs(monkeypatch):
    calls = []

    def counted_snap(*args, **kwargs):
        calls.append(1)
        return snap(*args, **kwargs)

    monkeypatch.setattr(pc, 'snap', counted_snap)
    lines = sparse_lines(100)
    actual = indexed_merge(lines)
    assert actual.equals_exact(pairwise_merge(lines), 0)
    assert len(calls) == 100  # One nearby pair per row, rather than 19,900 pairs.


@pytest.mark.parametrize('gap', [0, 0.5 * TOLERANCE, TOLERANCE, 1.01 * TOLERANCE])
def test_snapping_tolerance_boundary(gap):
    lines = [LineString([(0, 0), (0, 1)]), LineString([(gap, 0), (gap, 1)])]
    assert indexed_merge(lines).equals_exact(pairwise_merge(lines), 0)


@pytest.mark.parametrize('seed', range(10))
def test_snapping_matches_pairwise_order_for_clustered_paths(seed):
    rng = Random(seed)
    lines = [LineString([(rng.randrange(3) + rng.uniform(-1, 1) * TOLERANCE, 0),
                         (rng.randrange(3) + rng.uniform(-1, 1) * TOLERANCE, 1)]) for _ in range(25)]
    assert indexed_merge(lines).equals_exact(pairwise_merge(lines), 0)


def test_snapping_honors_cancellation_between_candidates(monkeypatch):
    cancelled = False

    def cancel_after_snap(*args, **kwargs):
        nonlocal cancelled
        result = snap(*args, **kwargs)
        cancelled = True
        return result

    monkeypatch.setattr(pc, 'snap', cancel_after_snap)
    lines = sparse_lines(3)
    tools = {1: {'solid_geometry': lines}}
    with pytest.raises(grace):
        pc.merge_tool_lines(tools, snap_overlaps=True, abort=lambda: cancelled)
    assert tools[1]['solid_geometry'] is lines


def benchmark():
    """Run manually; timings aren't assertions because CI machines have different speeds."""
    for label, lines in [('sparse-200', sparse_lines(100)), ('sparse-800', sparse_lines(400)),
                         ('dense-200', [LineString([(0, 0), (1, 1 + i * 1e-10)]) for i in range(200)])]:
        times = []
        for merge in (pairwise_merge, indexed_merge):
            samples = []
            for _ in range(3):
                start = perf_counter()
                merge(lines)
                samples.append(perf_counter() - start)
            times.append(min(samples))
        print('%s: pairwise=%.4fs indexed=%.4fs speedup=%.2fx' % (label, *times, times[0] / times[1]))
