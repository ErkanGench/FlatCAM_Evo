"""Isolation rest machining uses bounded bulk queries for sparse passes and early exit for dense passes.
The result must be the one of the test of each pass against every other polygon.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import shapely
from shapely import Polygon, box

from appPlugins.ToolIsolation import ToolIsolation

TOOLDIA = 0.2
OVERLAP = 0.1


def polygons():
    """Pairs of pads at gaps from 0.05 mm to 1.5 mm, a pad with 2 holes too small for the tool and 1 with 2 large
    holes."""
    pads = []
    for column, gap in enumerate((0.05, 0.3, 0.45, 0.6, 0.8, 1.0, 1.5, 0.35, 0.7, 0.25)):
        x = column * 3.0
        pads.append(box(x, 0, x + 1, 1))
        pads.append(box(x, 1 + gap, x + 1, 2 + gap))
    pads.append(Polygon(box(0, 10, 3, 13).exterior.coords,
                        [box(0.5, 11, 0.6, 11.1).exterior.coords, box(2, 11, 2.1, 11.1).exterior.coords]))
    pads.append(Polygon(box(10, 10, 16, 14).exterior.coords,
                        [box(11, 11, 13, 13).exterior.coords, box(14, 11, 15, 13).exterior.coords]))
    return pads


def rest_passes_pairwise(geometry, tooldia, passes, overlap, negative_dia, forced_rest):
    """The passes of generate_rest_geometry() tested against every other polygon (the code before the index)."""
    work_geo, not_isolated = [], []
    for idx, geo in enumerate(geometry):
        good = []
        for nr_pass in range(passes):
            iso_offset = tooldia * ((2 * nr_pass + 1) / 2.0) - (nr_pass * overlap * tooldia)
            if negative_dia:
                iso_offset = -iso_offset
            check_geo = geo.buffer(iso_offset * 1.99999)
            if any(check_geo.intersects(other) for i, other in enumerate(geometry) if i != idx):
                continue
            temp_geo = geo.buffer(iso_offset)
            if nr_pass == 0 and forced_rest is False and len(geo.interiors) > 1:
                parts = [temp_geo] if isinstance(temp_geo, Polygon) else list(temp_geo.geoms)
                if len(parts) != 1 or len(parts[0].interiors) != len(geo.interiors):
                    break
            good.append(temp_geo)
        if good:
            work_geo += good
        else:
            not_isolated.append(geo)
    isolated = []
    for geo in work_geo:
        for poly in getattr(geo, 'geoms', [geo]):
            if poly.is_empty:
                continue
            isolated += [poly.exterior] + list(poly.interiors)
    return isolated, not_isolated


def run_rest(geometry, passes, negative_dia=False, forced_rest=False):
    tool = SimpleNamespace(app=SimpleNamespace(log=Mock()))
    return ToolIsolation.generate_rest_geometry(tool, geometry, TOOLDIA, passes, OVERLAP, invert=False,
                                                env_iso_type=2, negative_dia=negative_dia, forced_rest=forced_rest)


@pytest.mark.parametrize('passes', [1, 2, 3])
@pytest.mark.parametrize('forced_rest', [False, True])
@pytest.mark.parametrize('negative_dia', [False, True])
def test_same_passes_as_the_pairwise_test(passes, forced_rest, negative_dia):
    geometry = polygons()
    isolated, not_isolated = run_rest(geometry, passes, negative_dia, forced_rest)
    expected_isolated, expected_not_isolated = rest_passes_pairwise(
        geometry, TOOLDIA, passes, OVERLAP, negative_dia, forced_rest)
    assert [g.wkb for g in isolated] == [g.wkb for g in expected_isolated]
    assert [g.wkb for g in not_isolated] == [g.wkb for g in expected_not_isolated]


def test_close_pads_and_small_holes_are_left_for_a_smaller_tool():
    geometry = polygons()
    __, not_isolated = run_rest(geometry, 1)
    # the 2 pads 0.05 mm apart (the check buffer of the first pass is 0.2 mm) and the pad with the small holes
    assert [g.wkb for g in not_isolated] == [g.wkb for g in geometry[0:2] + geometry[20:21]]
    __, not_isolated = run_rest(geometry, 1, forced_rest=True)
    assert [g.wkb for g in not_isolated] == [g.wkb for g in geometry[0:2]]


def test_no_pairwise_intersection_tests():
    geometry = polygons()
    with patch.object(shapely, 'intersects', wraps=shapely.intersects) as intersects:
        run_rest(geometry, 3)
    assert intersects.call_count == 0


def test_a_polygon_abandoned_in_the_first_pass_is_not_tested_in_the_next_passes():
    geometry = polygons()
    with patch.object(shapely, 'buffer', wraps=shapely.buffer) as buffer:
        __, not_isolated = run_rest(geometry, 3)
    assert geometry[20] in not_isolated
    # the check buffers of the 3 passes (array calls); the pad with the small holes is abandoned in the first pass
    check_buffers = [c.args[0] for c in buffer.call_args_list if not isinstance(c.args[0], shapely.Geometry)]
    assert [len(arr) for arr in check_buffers] == [len(geometry), len(geometry) - 1, len(geometry) - 1]
    assert any(geo is geometry[20] for geo in check_buffers[0])
    assert not any(geo is geometry[20] for arr in check_buffers[1:] for geo in arr)


@pytest.mark.parametrize('dense', [False, True], ids=['missed_cluster', 'dense'])
def test_query_results_are_bounded(dense):
    geometry = [box(i * 3, 0, i * 3 + 1, 1) for i in range(400)]
    # The small cluster lies between the evenly spaced sample indexes.
    for i in (range(400) if dense else range(1, 20)):
        geometry[i] = box(-10, 0, -9, 1)
    original_tree = shapely.STRtree
    query_sizes = []

    class RecordedTree:
        def __init__(self, geos):
            self.tree = original_tree(geos)

        def query(self, geos, *args, **kwargs):
            query_count = 1 if isinstance(geos, shapely.Geometry) else len(geos)
            query_sizes.append(query_count)
            # Even when every bounding box matches, a query cannot return more than this many pairs.
            assert query_count * len(self.tree.geometries) <= 65536
            return self.tree.query(geos, *args, **kwargs)

    with patch.object(shapely, 'STRtree', RecordedTree):
        actual = run_rest(geometry, 1)
    expected = rest_passes_pairwise(geometry, TOOLDIA, 1, OVERLAP, False, False)
    assert [[g.wkb for g in part] for part in actual] == [[g.wkb for g in part] for part in expected]
    assert query_sizes


def test_dense_layout_uses_early_exit_for_unsampled_polygons():
    geometry = [box((i % 30) * 0.1, (i // 30) * 0.1,
                    (i % 30) * 0.1 + 0.02, (i // 30) * 0.1 + 0.02) for i in range(900)]
    original_intersects = shapely.geometry.base.BaseGeometry.intersects
    with patch.object(shapely.geometry.base.BaseGeometry, 'intersects', autospec=True,
                      side_effect=original_intersects) as intersects:
        isolated, not_isolated = run_rest(geometry, 1)
    assert not isolated
    assert [g.wkb for g in not_isolated] == [g.wkb for g in geometry]
    # The sample doesn't cover the whole board; remaining polygons stop at a nearby collision.
    assert 0 < intersects.call_count < len(geometry) * 16


@pytest.mark.parametrize('negative_dia', [False, True])
@pytest.mark.parametrize('forced_rest', [False, True])
def test_dense_passes_preserve_paths_and_abandoned_polygons(negative_dia, forced_rest):
    geometry = [box((i % 30) * 0.1, (i // 30) * 0.1,
                    (i % 30) * 0.1 + 0.02, (i // 30) * 0.1 + 0.02) for i in range(900)]
    geometry += [Polygon(box(10, 0, 13, 3).exterior.coords,
                         [box(10.5, 1, 10.6, 1.1).exterior.coords, box(12, 1, 12.1, 1.1).exterior.coords]),
                 box(20, 0, 22, 2)]
    actual = run_rest(geometry, 3, negative_dia, forced_rest)
    expected = rest_passes_pairwise(geometry, TOOLDIA, 3, OVERLAP, negative_dia, forced_rest)
    assert [[g.wkb for g in part] for part in actual] == [[g.wkb for g in part] for part in expected]
