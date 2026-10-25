"""Geometry Editor: the Copy tool makes the copies also when the cursor did not move after the reference click."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from shapely.affinity import rotate, translate

from shapely.geometry import LineString, box

from appEditors.appGeoEditor import FCCopy, DrawToolShape


def radio(value):
    return SimpleNamespace(get_value=lambda: value)


def copy_tool(selected, mode='n'):
    """An FCCopy with the shapes already selected, without the Copy plugin GUI."""
    editor = SimpleNamespace(selected=list(selected), app=SimpleNamespace(inform=Mock(), jump_signal=Mock()))
    editor.get_selected = lambda: editor.selected

    tool = FCCopy.__new__(FCCopy)
    tool.draw_app = editor
    tool.complete = False
    tool.points = []
    tool.geometry = None
    tool.origin = None
    tool.destination = None
    tool.util_geo = None
    tool.clicked_postion = None
    tool.has_selection = True
    tool.sel_limit = 30
    tool.draw_cursor_data = Mock()
    tool.copy_tool = SimpleNamespace(ui=SimpleNamespace(
        mode_radio=radio(mode), array_type_radio=radio('linear'), axis_radio=radio('X'), pitch_entry=radio(10.0),
        linear_angle_spinner=radio(0.0), array_size_entry=radio(3)))
    tool.selection_shape = tool.selection_bbox()
    return tool


class TestGeoEditorCopy(unittest.TestCase):

    def setUp(self):
        self.square = DrawToolShape(box(0, 0, 1, 1))
        self.line = DrawToolShape(LineString([(0, 0), (2, 0)]))

    def test_second_click_without_cursor_move_copies_to_the_destination(self):
        tool = copy_tool([self.square, self.line])
        tool.click((0.0, 0.0))      # reference point
        tool.click((3.0, 1.0))      # destination, no mouse move event in between
        self.assertTrue(tool.complete)
        self.assertEqual([shp.geo.bounds for shp in tool.geometry], [(3.0, 1.0, 4.0, 2.0), (3.0, 1.0, 5.0, 1.0)])
        # the source shapes are not changed
        self.assertEqual(self.square.geo.bounds, (0.0, 0.0, 1.0, 1.0))


    def test_linear_array_without_cursor_move(self):
        tool = copy_tool([self.square], mode='a')
        tool.click((0.0, 0.0))
        tool.click((1.0, 0.0))
        self.assertEqual([shp.geo.bounds[0] for shp in tool.geometry], [1.0, 11.0, 21.0])



@pytest.mark.parametrize('mode,array_type', [('a', 'circular')])
def test_copy_preserves_independent_metadata(mode, array_type):
    sources = [DrawToolShape(box(0, 0, 1, 1)), DrawToolShape(LineString([(2, 0), (3, 1)]))]
    for i, source in enumerate(sources):
        source.data.update(custom={'name': str(i)}, keeps_direction=True)
    tool = copy_tool(sources, mode)
    ui = tool.copy_tool.ui
    ui.array_type_radio = radio(array_type)
    ui.array_dir_radio, ui.angle_entry = radio('CCW'), radio(90)
    ui.placement_radio, ui.rows, ui.columns = radio('o'), radio(2), radio(2)
    ui.spacing_rows = ui.spacing_columns = radio(1)
    ui.offsetx_entry = ui.offsety_entry = radio(4)
    tool.click((0, 0))
    tool.click((5, 0))
    for i, result in enumerate(tool.geometry):
        assert result.data['custom'] == sources[i % 2].data['custom']
        assert result.data['keeps_direction'] is True
        assert result.data['bounds'] == result.bounds()
        result.data['custom']['name'] = 'changed'
    assert [source.data['custom']['name'] for source in sources] == ['0', '1']


@pytest.mark.parametrize('direction,sign', [('CW', -1)])
def test_circular_copy_rotates_radially_at_final_destination(direction, sign):
    source = DrawToolShape(LineString([(2, 3), (4, 3)]))
    tool = copy_tool([source], 'a')
    ui = tool.copy_tool.ui
    ui.array_type_radio = radio('circular')
    ui.array_dir_radio, ui.angle_entry = radio(direction), radio(90)
    tool.click((2, 3))
    tool.util_geo = DrawToolShape(box(100, 100, 101, 101))
    tool.click((7, 3))
    for i, result in enumerate(tool.geometry):
        import math
        angle = sign * 90 * i
        expected = translate(rotate(source.geo, angle, origin=(2, 3)),
                             5 * math.cos(math.radians(angle)), 5 * math.sin(math.radians(angle)))
        assert result.geo.equals_exact(expected, 1e-12)
    assert list(source.geo.coords) == [(2, 3), (4, 3)]


if __name__ == '__main__':
    unittest.main()
