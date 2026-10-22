"""Tests of camlib.map_geometry, the shared coordinate walker of the Gerber / Excellon transforms."""

import pytest
from shapely import affinity
from shapely.geometry import (GeometryCollection, LineString, MultiLineString, MultiPoint, MultiPolygon, Point,
                              box)

from camlib import map_geometry


def shift(g):
    return affinity.translate(g, 1.0, 2.0)


def test_none_stays_none():
    assert map_geometry(None, shift) is None


@pytest.mark.parametrize('geom', [
    Point(0, 0),
    LineString([(0, 0), (1, 1)]),
    box(0, 0, 1, 1),
    MultiPoint([(0, 0), (1, 1)]),
    MultiLineString([[(0, 0), (1, 1)], [(2, 2), (3, 3)]]),
    MultiPolygon([box(0, 0, 1, 1), box(2, 2, 3, 3)]),
    GeometryCollection([Point(0, 0), box(0, 0, 1, 1)]),
])
def test_single_geometry_is_one_leaf_and_type_is_kept(geom):
    calls = []

    def fn(g):
        calls.append(g)
        return shift(g)

    out = map_geometry(geom, fn)
    assert len(calls) == 1 and calls[0] is geom
    assert type(out) is type(geom)
    assert out.equals(shift(geom))


def test_list_stays_list_and_nested_lists_keep_shape():
    a, b, c = Point(0, 0), box(0, 0, 1, 1), LineString([(0, 0), (1, 0)])
    out = map_geometry([a, [b, [c]], []], shift)
    assert type(out) is list and len(out) == 3
    assert out[0].equals(shift(a))
    assert type(out[1]) is list and out[1][0].equals(shift(b))
    assert type(out[1][1]) is list and out[1][1][0].equals(shift(c))
    assert out[2] == []


def test_on_leaf_runs_once_per_leaf_before_fn():
    order = []

    def fn(g):
        order.append('fn')
        return g

    out = map_geometry([Point(0, 0), [Point(1, 1)], None], fn, on_leaf=lambda g: order.append('leaf'))
    assert order == ['leaf', 'fn'] * 3
    assert len(out) == 3

