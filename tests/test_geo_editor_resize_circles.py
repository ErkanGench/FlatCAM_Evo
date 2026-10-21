"""Resize Circles: geometric circle detection, scaling about the own center, one Undo step."""
import math
from unittest.mock import Mock

import pytest
from shapely.affinity import scale
from shapely.geometry import LinearRing, LineString, Point, Polygon, box

from appEditors import appGeoEditor as geo
from tests.test_geo_editor_join import join_editor
from tests.test_geo_editor_split import qt_application  # noqa: F401  (autouse Qt fixture)


def circle_polygon(center=(3.0, 4.0), radius=2.0, quad_segs=16):
    return Point(center).buffer(radius, quad_segs)


def circle_outline(center=(3.0, 4.0), radius=2.0, quad_segs=16):
    return LinearRing(circle_polygon(center, radius, quad_segs).exterior.coords)


def circle_editor(geometries, selected=None):
    editor, shapes = join_editor([[(0, 0), (1, 0)]])
    for shape in shapes:
        editor.storage.remove(shape)
    shapes = []
    for geometry in geometries:
        shape = geo.DrawToolShape(geometry)
        editor.storage.insert(shape)
        shapes.append(shape)
    editor.selected = list(shapes) if selected is None else [shapes[i] for i in selected]
    editor.update_all_vertex_count = lambda: None
    editor.plot_changes = Mock()
    return editor, shapes


def last_message(editor):
    return editor.app.inform.emit.call_args.args[0]


@pytest.mark.parametrize('make', [circle_polygon, circle_outline])
def test_circle_forms_are_detected(make):
    (cx, cy), radius = geo.circle_of(make())
    assert (cx, cy) == pytest.approx((3.0, 4.0))
    assert radius == pytest.approx(2.0)


def test_closed_linestring_is_a_circle():
    ring = LineString(circle_outline().coords)
    assert geo.circle_of(ring) is not None


def test_non_circles_are_rejected():
    ellipse = scale(Point(0, 0).buffer(1, 16), 2.0, 1.0)
    holed = Polygon(circle_polygon().exterior.coords, [circle_polygon(radius=0.5).exterior.coords])
    open_arc = LineString(circle_outline().coords[:-5])
    for geometry in (box(0, 0, 2, 2), LinearRing(box(0, 0, 2, 2).exterior.coords), ellipse, holed, open_arc,
                     Point(0, 0), LineString([(0, 0), (1, 1)]), Polygon()):
        assert geo.circle_of(geometry) is None


@pytest.mark.parametrize('make', [circle_polygon, circle_outline])
def test_resize_keeps_center_type_and_vertex_count(make):
    original = make()
    result = geo.resized_circle(original, 10.0)
    assert type(result) is type(original)
    assert len(result.exterior.coords if isinstance(result, Polygon) else result.coords) == \
        len(original.exterior.coords if isinstance(original, Polygon) else original.coords)
    (cx, cy), radius = geo.circle_of(result)
    assert (cx, cy) == pytest.approx((3.0, 4.0))
    assert radius == pytest.approx(5.0)


def test_resize_non_circle_returns_none():
    assert geo.resized_circle(box(0, 0, 1, 1), 3.0) is None


def test_mixed_selection_skips_non_circles_and_keeps_selection():
    editor, shapes = circle_editor([circle_polygon(), box(0, 0, 1, 1), circle_outline((9, 9), 1.0)])
    geo.AppGeoEditor.apply_resize_circles(editor, 6.0)
    assert last_message(editor) == '2 circles resized, 1 shapes skipped'
    stored = set(editor.storage.get_objects())
    assert shapes[1] in stored and shapes[0] not in stored and shapes[2] not in stored
    assert editor.selected[1] is shapes[1]
    assert {id(s) for s in editor.selected} == {id(s) for s in stored}
    assert geo.circle_of(editor.selected[0].geo)[1] == pytest.approx(3.0)
    assert geo.circle_of(editor.selected[2].geo) == (pytest.approx((9, 9)), pytest.approx(3.0))
    editor.plot_changes.assert_called()
    assert len(editor._history_undo) == 1


def test_resize_is_one_undo_step():
    editor, shapes = circle_editor([circle_polygon(), circle_polygon((10, 10), 1.0)])
    before = [s.geo.wkt for s in shapes]
    geo.AppGeoEditor.apply_resize_circles(editor, 8.0)
    assert len(editor._history_undo) == 1
    assert editor.undo()
    assert set(editor.storage.get_objects()) == set(shapes)
    assert [s.geo.wkt for s in shapes] == before
    assert editor.redo()
    assert set(editor.storage.get_objects()).isdisjoint(shapes)


@pytest.mark.parametrize('diameter', [0, -1, float('nan'), float('inf'), 'abc', None])
def test_invalid_diameter_warns_and_changes_nothing(diameter):
    editor, shapes = circle_editor([circle_polygon()])
    assert geo.AppGeoEditor.apply_resize_circles(editor, diameter) == 'fail'
    assert 'WARNING' in last_message(editor)
    assert set(editor.storage.get_objects()) == set(shapes)
    assert not editor._history_undo


def test_no_circle_selected_warns_and_changes_nothing():
    editor, shapes = circle_editor([circle_polygon(), box(0, 0, 1, 1)], selected=[1])
    assert geo.AppGeoEditor.apply_resize_circles(editor, 4.0) == 'fail'
    assert 'WARNING' in last_message(editor)
    assert set(editor.storage.get_objects()) == set(shapes)
    assert not editor._history_undo
    editor.selected = []
    assert geo.AppGeoEditor.apply_resize_circles(editor, 4.0) == 'fail'
    assert not editor._history_undo


def test_button_reads_entry():
    editor, shapes = circle_editor([circle_polygon()])
    editor.ui.resize_circles_entry.set_value(4.0)
    result = geo.AppGeoEditor.on_resize_circles(editor)
    assert math.isclose(geo.circle_of(result[0].geo)[1], 2.0, rel_tol=1e-9)
