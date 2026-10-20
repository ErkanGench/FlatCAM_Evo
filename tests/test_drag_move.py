"""Moving the selected objects by dragging them with the mouse on the canvas (AppCanvasEvents). The press, move and
release handlers are the real ones; the application and the canvas are stand-ins, the Move Tool is a stand-in or the
real ToolMove (TestDragMoveWithTheMoveTool). Everything is headless."""

import os
import unittest
from types import SimpleNamespace
from contextlib import nullcontext
from unittest.mock import MagicMock, Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon

from appHandlers.appCanvasEvents import AppCanvasEvents
from appPlugins.ToolMove import ToolMove

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

NO_MOD = Qt.KeyboardModifier.NoModifier
CONTROL = Qt.KeyboardModifier.ControlModifier


def fake_object(name, geometry, tools=None):
    xmin, ymin, xmax, ymax = geometry.bounds
    return SimpleNamespace(obj_options={'name': name, 'plot': True, 'xmin': xmin, 'ymin': ymin, 'xmax': xmax,
                                        'ymax': ymax},
                           visible=True, solid_geometry=[] if tools else [geometry], tools=tools or {})


def make_events(selected, pixel=0.1, grid=None):
    """An AppCanvasEvents on a stand-in application; 1 screen pixel is `pixel` plot units."""
    app = SimpleNamespace(
        log=MagicMock(), inform=MagicMock(), ui=MagicMock(), defaults={},
        options={'global_pan_button': '2', 'global_selection_shape': True, 'global_hover_shape': False},
        call_source='app', command_active=None, rel_point1=None, rel_point2=None, mouse_down=False,
        event_is_dragging=False, selection_type=None, doubleclick=False, mouse_click_pos=[0, 0], mouse_pos=[0, 0],
        collection=SimpleNamespace(get_selected=lambda: list(selected)),
        plotcanvas=SimpleNamespace(translate_coords=lambda pos: (pos[0], pos[1]), pixel_size=lambda: pixel,
                                   native=MagicMock(), on_update_text_hud=MagicMock(), cursor_color='black'),
        grid_status=lambda: grid is not None,
        geo_editor=SimpleNamespace(snap=lambda x, y: (round(x / grid) * grid, round(y / grid) * grid)),
        app_cursor=MagicMock(), move_tool=MagicMock(), app_plugins=[],
    )
    app.ui.shell_dock.isVisible.return_value = False
    app.ui.popMenu.popup_active = False
    events = AppCanvasEvents(app)
    events.delete_selection_shape = MagicMock()
    events.draw_moving_selection_shape = MagicMock()
    events.selection_area_handler = MagicMock()
    events.select_objects = MagicMock()
    events.delete_hover_shape = MagicMock()
    return events, app


def press(events, x, y):
    events.on_mouse_click_over_plot(SimpleNamespace(button=1, pos=(x, y)))


def move(events, x, y):
    events.on_mouse_move_over_plot(SimpleNamespace(button=1, pos=(x, y)))


def release(events, x, y):
    events.on_mouse_click_release_over_plot(SimpleNamespace(button=1, pos=(x, y)))


class TestDragMove(unittest.TestCase):

    def setUp(self):
        patcher = patch.object(QtWidgets.QApplication, 'keyboardModifiers', return_value=NO_MOD)
        self.modifiers = patcher.start()
        self.addCleanup(patcher.stop)
        self.outline = fake_object('outline', LineString([(0, 0), (40, 0), (40, 90), (0, 90), (0, 0)]))
        self.copper = fake_object('copper', Polygon([(5, 5), (10, 5), (10, 10), (5, 10)]))

    def test_drag_on_an_object_moves_all_the_selected_objects_together(self):
        events, app = make_events([self.outline, self.copper])
        press(events, 0.25, 45)                 # 0.25 from the outline: within 5 px of 0.1
        move(events, 0.5, 45)                   # 2.5 px: not a move yet
        app.move_tool.draw_sel_bbox.assert_not_called()
        move(events, 5.25, 47)
        app.move_tool.draw_sel_bbox.assert_called_once_with()
        app.move_tool.update_sel_bbox.assert_called_with((5.0, 2))
        release(events, 12.25, 40)
        app.move_tool.move_handler.assert_called_once_with(offset=(12.0, -5), objects=[self.outline, self.copper])
        # no selection box and no selection by click
        events.draw_moving_selection_shape.assert_not_called()
        events.selection_area_handler.assert_not_called()
        events.select_objects.assert_not_called()

    def test_press_inside_the_copper_is_on_the_object(self):
        events, app = make_events([self.copper])
        press(events, 7, 7)
        move(events, 17, 7)
        release(events, 17, 7)
        app.move_tool.move_handler.assert_called_once_with(offset=(10, 0), objects=[self.copper])

    def test_the_offset_is_snapped_to_the_grid(self):
        events, app = make_events([self.copper], grid=1.0)
        press(events, 7.2, 7.3)
        move(events, 10.4, 8.6)
        release(events, 10.4, 8.6)
        app.move_tool.move_handler.assert_called_once_with(offset=(3.0, 2.0), objects=[self.copper])

    def test_a_press_on_a_free_place_draws_the_selection_box(self):
        events, app = make_events([self.outline, self.copper])
        press(events, 20, 50)                   # inside the outline box, but far from its lines
        move(events, 30, 60)
        events.draw_moving_selection_shape.assert_called()
        release(events, 30, 60)
        events.selection_area_handler.assert_called_once()
        app.move_tool.draw_sel_bbox.assert_not_called()
        app.move_tool.move_handler.assert_not_called()

    def test_the_hit_tolerance_is_in_screen_pixels(self):
        events, app = make_events([self.outline], pixel=0.1)
        press(events, 0.6, 45)                  # 6 px from the line
        self.assertIsNone(events._drag_move)
        events, app = make_events([self.outline], pixel=1.0)
        press(events, 0.6, 45)                  # 0.6 px from the line (zoomed out)
        self.assertIsNotNone(events._drag_move)

    def test_a_click_without_moving_still_selects(self):
        events, app = make_events([self.outline])
        press(events, 0, 45)
        move(events, 0.3, 45)
        release(events, 0.3, 45)
        events.select_objects.assert_called_once_with()
        app.move_tool.move_handler.assert_not_called()

    def test_a_click_that_moves_1_pixel_over_a_grid_line_still_selects(self):
        events, app = make_events([self.copper], pixel=0.1, grid=1.0)
        press(events, 7.45, 7)                  # snapped to (7, 7)
        move(events, 7.55, 7)                   # 1 px further, snapped to (8, 7)
        release(events, 7.55, 7)
        app.move_tool.draw_sel_bbox.assert_not_called()
        app.move_tool.move_handler.assert_not_called()
        events.select_objects.assert_called_once_with()

    def test_escape_cancels_the_move(self):
        events, app = make_events([self.outline])
        press(events, 0, 45)
        move(events, 10, 45)
        events.cancel_drag_move()
        app.move_tool.delete_shape.assert_called_once_with()
        move(events, 20, 45)                    # still no selection box
        release(events, 20, 45)                 # the release does nothing
        events.draw_moving_selection_shape.assert_not_called()
        events.select_objects.assert_not_called()
        app.move_tool.move_handler.assert_not_called()
        self.assertIsNone(events._drag_move)

    def test_escape_without_a_drag_does_nothing(self):
        events, app = make_events([self.outline])
        events.cancel_drag_move()
        self.assertIsNone(events._drag_move)
        app.move_tool.delete_shape.assert_not_called()

    def test_no_drag_with_a_key_modifier_a_command_or_outside_the_app(self):
        events, app = make_events([self.outline])
        self.modifiers.return_value = CONTROL   # Ctrl + click is the multiple selection
        press(events, 0, 45)
        self.assertIsNone(events._drag_move)
        self.modifiers.return_value = NO_MOD

        app.command_active = 'Move'
        press(events, 0, 45)
        self.assertIsNone(events._drag_move)

        app.command_active = None
        app.call_source = 'geo_editor'
        press(events, 0, 45)
        self.assertIsNone(events._drag_move)

    def test_no_drag_while_a_plugin_is_open(self):
        # e.g. the Polygon Selection of the Isolation Plugin: the Plugin gets the release and uses the selection box
        events, app = make_events([self.copper])
        app.ui.notebook.currentWidget.return_value.objectName.return_value = 'plugin_tab'
        press(events, 7, 7)
        self.assertIsNone(events._drag_move)
        move(events, 17, 9)
        events.draw_moving_selection_shape.assert_called()
        self.assertIs(app.selection_type, True)
        app.move_tool.draw_sel_bbox.assert_not_called()

    def test_no_drag_without_a_selection(self):
        events, app = make_events([])
        press(events, 0, 45)
        self.assertIsNone(events._drag_move)
        move(events, 10, 45)
        events.draw_moving_selection_shape.assert_called()

    def test_only_the_plotted_objects_are_moved(self):
        hidden = fake_object('hidden', Polygon([(50, 50), (60, 50), (60, 60), (50, 60)]))
        hidden.obj_options['plot'] = False
        events, app = make_events([self.copper, hidden])
        press(events, 55, 55)                   # on the hidden object
        self.assertIsNone(events._drag_move)
        press(events, 7, 7)
        move(events, 17, 7)
        release(events, 17, 7)
        app.move_tool.move_handler.assert_called_once_with(offset=(10, 0), objects=[self.copper])

    def test_the_geometry_in_the_tools_is_hit(self):
        # Excellon and multi-geometry objects keep the geometry in the tools
        holes = [Point(20, 20).buffer(0.5), Point(30, 20).buffer(0.5)]
        drills = fake_object('drills', MultiPolygon(holes), tools={1: {'solid_geometry': holes[:1]},
                                                                    2: {'solid_geometry': holes[1:]}})
        self.assertTrue(AppCanvasEvents._object_hit(drills, Point(30.55, 20), 0.1))
        self.assertFalse(AppCanvasEvents._object_hit(drills, Point(25, 20), 0.1))   # in the box, between the holes

    def test_multipart_shapes_and_nested_lists_are_hit(self):
        pads = MultiPolygon([Point(20, 20).buffer(0.5), Point(30, 20).buffer(0.5)])
        board = fake_object('board', pads)
        self.assertTrue(AppCanvasEvents._object_hit(board, Point(30.55, 20), 0.1))
        self.assertFalse(AppCanvasEvents._object_hit(board, Point(25, 20), 0.1))
        board.solid_geometry = [[], [None, [pads]]]
        self.assertTrue(AppCanvasEvents._object_hit(board, Point(20, 20), 0.1))
        board.solid_geometry = None
        self.assertFalse(AppCanvasEvents._object_hit(board, Point(20, 20), 0.1))


class TestEscapeKey(unittest.TestCase):

    def test_escape_on_the_canvas_cancels_the_drag(self):
        from appGUI.MainGUI import MainGUI

        ui = MagicMock()
        ui.app.call_source = 'app'
        ui.toggle_f_screen = False
        event = SimpleNamespace(key='Escape', native=SimpleNamespace(isAutoRepeat=lambda: False))
        with patch.object(QtWidgets.QApplication, 'keyboardModifiers', return_value=NO_MOD):
            MainGUI.keyPressEvent(ui, event)
        ui.app.on_deselect_all.assert_called_once_with()
        ui.app.cancel_drag_move.assert_called_once_with()


class TestDragMoveWithTheMoveTool(unittest.TestCase):
    """The drag uses the outline, the move and the worker of the real Move Tool."""

    def setUp(self):
        patcher = patch.object(QtWidgets.QApplication, 'keyboardModifiers', return_value=NO_MOD)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def movable(name, geometry):
        obj = fake_object(name, geometry)
        obj.kind = 'geometry'
        obj.plot = Mock()

        def offset(vector):
            obj.solid_geometry = [affinity.translate(geo, *vector) for geo in obj.solid_geometry]

        obj.offset = offset
        obj.bounds = lambda: MultiPolygon([geo.buffer(0.01) for geo in obj.solid_geometry]).bounds
        return obj

    def test_the_selected_objects_move_together(self):
        outline = self.movable('outline', LineString([(0, 0), (40, 0), (40, 90), (0, 90), (0, 0)]))
        copper = self.movable('copper', Polygon([(5, 5), (10, 5), (10, 10), (5, 10)]))
        events, app = make_events([outline, copper], grid=1.0)

        tool_app = Mock()
        tool_app.decimals = 4
        tool_app.proc_container.new.side_effect = lambda text: nullcontext()
        tool_app.collection.get_selected.return_value = [outline, copper]
        app.move_tool = ToolMove(tool_app)
        self.addCleanup(app.move_tool.close)

        press(events, 40.2, 30)                 # on the right side of the outline
        move(events, 45, 31)
        self.assertEqual(4, len(app.move_tool.old_coords))     # the outline of the Move Tool is drawn
        release(events, 52.4, 11.6)             # snapped: a move of (12, -18)

        task = tool_app.worker_task.emit.call_args.args[0]
        task['fcn'](*task['params'])
        self.assertTrue(outline.solid_geometry[0].equals(
            LineString([(12, -18), (52, -18), (52, 72), (12, 72), (12, -18)])))
        self.assertTrue(copper.solid_geometry[0].equals(Polygon([(17, -13), (22, -13), (22, -8), (17, -8)])))
        outline.plot.assert_called_once_with()
        copper.plot.assert_called_once_with()
        self.assertTrue(tool_app.should_we_save)


if __name__ == '__main__':
    unittest.main()
