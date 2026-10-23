"""Characterization of the 'app' snapping branch of ``ToolDistance.Distance.snap_handler``: the center of the Gerber
pad (flash) or of the Excellon drill / slot under the cursor. It must pass before and after the move to
``feature_access.iter_features``.
"""

from unittest.mock import MagicMock, Mock
from types import MethodType, SimpleNamespace

import pytest

from appPlugins.ToolDistance import Distance

from tests.helpers_objects import app, excellon, gerber, _headless_qt, make_excellon, make_gerber  # noqa: F401,E402


def snap(app_objects, pos):
    """Run the unbound snap_handler with a fake tool; return (returned position, jump location or None)."""
    fake_app = MagicMock()
    fake_app.collection.get_list.return_value = app_objects
    fake_app.options = {}
    fake_app.defaults = {}
    fake_tool = Mock()
    fake_tool.original_call_source = 'app'
    fake_tool.app = fake_app
    fake_tool.make_storage = Mock()
    fake_tool.ui.big_cursor_cb.get_value.return_value = False
    result = Distance.snap_handler(fake_tool, pos)
    jumps = fake_app.on_jump_to.call_args_list
    assert len(jumps) <= 1
    return result, (jumps[0].kwargs['custom_location'] if jumps else None)


@pytest.fixture
def objs(gerber, excellon):
    return [gerber, excellon]


class TestGerberPads:
    @pytest.mark.parametrize('click, center', [
        ((5.2, 5.1), (5.0, 5.0)),         # C flash
        ((10.3, 5.1), (10.0, 5.0)),       # R flash
        ((15.4, 5.0), (15.0, 5.0)),       # O flash (also near drill T1 at 15,5: same center)
        ((20.1, 5.1), (20.0, 5.0)),       # P flash
    ])
    def test_click_inside_a_pad_snaps_to_its_center(self, objs, click, center):
        result, jump = snap([objs[0]], click)
        assert result == pytest.approx(center)
        assert jump == pytest.approx(center)

    def test_click_on_a_track_does_not_snap(self, objs):
        result, jump = snap([objs[0]], (20.0, 10.1))      # inside the C1 track, not a flash
        assert result == (20.0, 10.1) and jump is None

class TestExcellon:
    @pytest.mark.parametrize('click, center', [
        ((5.1, 12.1), (5.0, 12.0)),       # T2 drill
    ])
    def test_click_inside_a_drill(self, objs, click, center):
        result, jump = snap([objs[1]], click)
        assert result == pytest.approx(center)
        assert jump == pytest.approx(center)

    def test_click_inside_a_slot_snaps_to_the_slot_centroid(self, objs):
        result, jump = snap([objs[1]], (24.0, 12.2))      # T2 slot (20,12)-(28,12)
        assert result == pytest.approx((24.0, 12.0))
        assert jump == pytest.approx((24.0, 12.0))

class TestBothObjects:
    def test_overlapping_pad_and_drill_snap_to_the_same_center(self, objs):
        result, jump = snap(objs, (5.2, 5.1))             # C flash and T1 drill both at (5, 5)
        assert result == pytest.approx((5.0, 5.0))

    def test_the_closest_center_wins(self, app, objs):
        # a second Excellon drill whose disc covers the click but whose center is further away
        exc = make_excellon(app, name='exc2')
        from shapely.geometry import Point
        exc.tools = {1: {'tooldia': 1.0, 'drills': [Point(5.3, 5.0)], 'slots': [], 'solid_geometry': [], 'data': {}}}
        assert exc.create_geometry() is None
        result, jump = snap([objs[0], exc], (5.1, 5.0))   # gerber pad center (5, 5) is closer than (5.3, 5)
        assert result == pytest.approx((5.0, 5.0))
        result, jump = snap([objs[0], exc], (5.25, 5.0))  # now the drill center (5.3, 5) is closer
        assert result == pytest.approx((5.3, 5.0))


def test_snap_with_big_cursor_keeps_the_user_cursor_color(objs):
    # The cursor color from Preferences must survive a snap, so that on_exit restores it (not black).
    fake_app = MagicMock()
    fake_app.collection.get_list.return_value = [objs[0]]
    fake_app.options = {}
    fake_app.defaults = {}
    fake_app.plotcanvas = SimpleNamespace(cursor_color='#FF0000FF')
    fake_tool = Mock()
    fake_tool.original_call_source = 'app'
    fake_tool.app = fake_app
    fake_tool.cursor_color_memory = '#FF0000FF'
    fake_tool.ui.big_cursor_cb.get_value.return_value = True

    assert Distance.snap_handler(fake_tool, (5.2, 5.1)) == pytest.approx((5.0, 5.0))
    assert fake_app.plotcanvas.cursor_color == '#FF0000FF'
    assert fake_tool.cursor_color_memory == '#FF0000FF'
    assert fake_app.app_cursor.set_data.call_args.kwargs['edge_color'] == '#FF0000FF'


def test_multipoint_motion_replaces_the_first_preview_without_losing_committed_lines(_headless_qt):
    from vispy.gloo.context import FakeCanvas
    from appGUI.VisPyVisuals import ShapeCollectionVisual
    from shapely.geometry import LineString

    _canvas = FakeCanvas()
    tool = Mock()
    tool.sel_shapes = ShapeCollectionVisual(pool=None)
    tool.ui.multipoint_cb.get_value.return_value = True
    tool.app.plotcanvas.translate_coords.side_effect = lambda pos: pos
    tool.update_position_info.side_effect = lambda pos: pos
    tool.points = [(0, 0), (1, 1)]
    tool.total_distance = 1.0
    tool.update_distance.return_value = 1.0
    tool.add_utility_shape = MethodType(Distance.add_utility_shape, tool)
    tool.delete_utility_shape = MethodType(Distance.delete_utility_shape, tool)
    tool.add_utility_shape((1, 1), (10, 10))
    # The first preview has key zero. Committed segments must survive its replacement.
    tool.sel_shapes.add(LineString([(0, 0), (1, 1)]), color='blue', update=True, layer=0)
    Distance.on_mouse_move(tool, SimpleNamespace(pos=(2, 3), is_dragging=False))
    assert tool.sel_shapes.bounds(axis=0) == pytest.approx((0, 2))
    assert tool.sel_shapes.bounds(axis=1) == pytest.approx((0, 3))
    tool.app.log.error.assert_not_called()
