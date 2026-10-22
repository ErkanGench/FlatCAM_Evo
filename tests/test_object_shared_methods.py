"""Stage 4, item 1: methods that were copied into every object class now live once on FlatCAMObj (or on a small
mixin). Headless: ShapeCollection is patched, the ObjectUI is a Mock."""

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call, patch

import numpy as np
import pytest
from PyQt6 import QtCore

from appObjects.AppObjectTemplate import FlatCAMObj
from appObjects.CNCJobObject import CNCJobObject
from appObjects.DocumentObject import DocumentObject
from appObjects.ExcellonObject import ExcellonObject
from appObjects.GeometryObject import GeometryObject
from appObjects.GerberObject import GerberObject
from appObjects.ScriptObject import ScriptObject
from tests.helpers_objects import make_app_0b as make_app, no_shape_collection  # noqa: F401,E402

ALL_CLASSES = [GerberObject, ScriptObject]


def defining_class(cls, name):
    """The first class in the MRO whose own __dict__ defines `name`."""
    for klass in cls.__mro__:
        if name in vars(klass):
            return klass
    return None


def make_obj(cls):
    app = make_app()
    return cls('obj', app)


# ---------------------------------------------------------------- random_color

def test_random_color_is_an_opaque_rgba_array(no_shape_collection):  # noqa: F811
    obj = make_obj(GerberObject)
    for _ in range(20):
        color = obj.random_color()
        assert isinstance(color, np.ndarray)
        assert color.shape == (4,)
        assert color[3] == 1
        assert np.all((color >= 0) & (color <= 1))


def test_shape_and_annotation_ownership_without_backend_flag(no_shape_collection):  # noqa: F811
    obj = make_obj(CNCJobObject)
    canvas = obj.app.plotcanvas
    canvas.new_shape_group.assert_called_once_with()
    canvas.new_text_collection.assert_called_once_with()
    canvas.new_text_group.assert_called_once_with(collection=obj.text_col)
    assert obj.text_col.enabled is True
    assert obj.annotation is canvas.new_text_group.return_value

    obj = make_obj(GeometryObject)
    # temp_shapes (Geometry) and mark_shapes (FlatCAMObj), both made through the canvas
    assert obj.app.plotcanvas.new_shape_collection.call_args_list == [call(layers=1), call(layers=1)]

    obj = make_obj(GerberObject)
    assert not hasattr(obj, 'axes')
    obj.mark_shapes_storage = {10: [1]}
    obj.clear_plot_apertures()
    obj.mark_shapes.clear.assert_called_once_with(update=True)


def test_annotations_follow_checkboxes_and_cached_visibility(no_shape_collection):  # noqa: F811
    obj = make_obj(CNCJobObject)
    obj.shapes._indexes = [1]
    obj.shapes._collection.data = {1: {}}
    obj.mark_full_plot()
    obj._full_plot_kind = 'all'
    obj.ui = MagicMock()
    obj.plot_annotations = Mock()
    for checked, visible in ((True, True), (True, False), (False, True)):
        obj.ui.annotation_cb.get_value.return_value = checked
        assert obj.show_plotted_shapes(visible)
        obj.plot_annotations.assert_called_with(obj=obj, visible=checked and visible)
        assert obj.shapes.visible is visible

        obj.ui.plot_cb.get_value.return_value = visible
        obj.on_annotation_change(checked)
        obj.plot_annotations.assert_called_with(obj=obj, visible=checked and visible)
    obj.shapes.add.assert_not_called()
    obj.shapes.add_batch.assert_not_called()

    obj.plot_annotations.side_effect = AttributeError
    obj.on_annotation_change(True)
    obj.annotation.clear.assert_called_once_with(update=True)


def test_exclusion_events_use_named_callbacks_without_backend_flag():
    from appCommon.Common import ExclusionAreas

    app = make_app()
    app.on_mouse_click_over_plot = Mock()
    app.on_mouse_move_over_plot = Mock()
    app.on_mouse_click_release_over_plot = Mock()
    app.grid_status = lambda: False
    app.plotcanvas.translate_coords.side_effect = lambda pos: pos
    with patch('appCommon.Common.ShapeCollection', Mock()):
        areas = ExclusionAreas(app)
    areas.on_add_area_click(Mock(get_value=Mock(return_value='square')), Mock(), Mock(), Mock(), [], 'geometry')
    assert [c.args[0] for c in app.plotcanvas.graph_event_disconnect.call_args_list] == [
        'mouse_press', 'mouse_move', 'mouse_release']
    app.plotcanvas.graph_event_disconnect.reset_mock()
    areas.on_mouse_release(SimpleNamespace(pos=(1, 2), button=2))
    assert [c.args for c in app.plotcanvas.graph_event_disconnect.call_args_list] == [
        ('mouse_release', areas.on_mouse_release), ('mouse_move', areas.on_mouse_move)]
    assert app.call_source == 'app'
    expected_connections = [
        ('mouse_press', app.on_mouse_click_over_plot),
        ('mouse_move', app.on_mouse_move_over_plot),
        ('mouse_release', app.on_mouse_click_release_over_plot)]
    assert [c.args for c in app.plotcanvas.graph_event_connect.call_args_list][-3:] == expected_connections
    assert not {'mp', 'mm', 'mr'} & vars(app).keys()

    app.plotcanvas.graph_event_connect.reset_mock()
    app.plotcanvas.graph_event_disconnect.reset_mock()
    app.sel_shapes = Mock()
    areas.area_disconnect()
    assert [c.args for c in app.plotcanvas.graph_event_disconnect.call_args_list] == [
        ('mouse_release', areas.on_mouse_release), ('mouse_move', areas.on_mouse_move)]
    assert [c.args for c in app.plotcanvas.graph_event_connect.call_args_list] == expected_connections
    assert not {'mp', 'mm', 'mr'} & vars(app).keys()


# ------------------------------------------------- on_properties / on_properties_expanded

PROPERTIES_CLASSES = [GerberObject, ExcellonObject]


@pytest.mark.parametrize('cls', [GeometryObject])
def test_on_properties_checked(cls, no_shape_collection):  # noqa: F811
    obj = make_obj(cls)
    obj.ui = MagicMock()
    with patch.object(FlatCAMObj, 'add_properties_items') as add_items:
        obj.on_properties(True)
    obj.ui.info_frame.show.assert_called_once_with()
    obj.ui.info_frame.hide.assert_not_called()
    obj.ui.treeWidget.clear.assert_called_once_with()
    add_items.assert_called_once_with(obj=obj, treeWidget=obj.ui.treeWidget)
    obj.ui.treeWidget.setSizePolicy.assert_called_once()
    obj.ui.treeWidget.resize_sig.emit.assert_called_once_with()


def test_gerber_on_properties_checked(no_shape_collection):  # noqa: F811
    obj = make_obj(GerberObject)
    obj.ui = MagicMock()
    with patch.object(FlatCAMObj, 'add_properties_items') as add_items:
        obj.on_properties(True)
    obj.ui.info_frame.show.assert_called_once_with()
    obj.ui.treeWidget.clear.assert_called_once_with()
    add_items.assert_called_once_with(obj=obj, treeWidget=obj.ui.treeWidget)
    obj.ui.treeWidget.setSizePolicy.assert_not_called()
    obj.ui.treeWidget.resize_sig.emit.assert_called_once_with()


@pytest.mark.parametrize('cls', PROPERTIES_CLASSES)
def test_on_properties_unchecked_hides_and_stops(cls, no_shape_collection):  # noqa: F811
    obj = make_obj(cls)
    obj.ui = MagicMock()
    with patch.object(FlatCAMObj, 'add_properties_items') as add_items:
        obj.on_properties(False)
    obj.ui.info_frame.hide.assert_called_once_with()
    obj.ui.info_frame.show.assert_not_called()
    obj.ui.treeWidget.clear.assert_not_called()
    add_items.assert_not_called()


@pytest.mark.parametrize('cls', PROPERTIES_CLASSES)
def test_on_properties_expanded_resizes_every_column(cls, no_shape_collection):  # noqa: F811
    obj = make_obj(cls)
    obj.ui = MagicMock()
    # the method reads the count from self.treeWidget (not self.ui.treeWidget): same as before the move
    obj.treeWidget = Mock()
    obj.treeWidget.columnCount.return_value = 3
    obj.on_properties_expanded()
    assert [c.args for c in obj.ui.treeWidget.resizeColumnToContents.call_args_list] == [(0,), (1,), (2,)]


# ------------------------------------------------------------- change_level

@pytest.mark.parametrize('cls', ALL_CLASSES)
@pytest.mark.parametrize('level, checked', [('a', True), ('b', False), ('anything else', False)])
def test_change_level_sets_the_toggle_then_notifies(cls, level, checked):
    # ScriptObject and DocumentObject cannot be built with the headless app, so the function found through the class
    # is called with a stand-in for self (it only uses self.ui.level and self.on_level_changed)
    me = SimpleNamespace(ui=MagicMock(), on_level_changed=Mock())
    me.ui.level.isChecked.return_value = checked
    cls.change_level(me, level)
    me.ui.level.setChecked.assert_called_once_with(checked)
    me.on_level_changed.assert_called_once_with(checked)


# --------------------------------------------------------- set_offset_values

OFFSET_CLASSES = [GerberObject, GeometryObject]


@pytest.mark.parametrize('cls', OFFSET_CLASSES)
def test_set_offset_values_writes_the_bounds_centre(cls, no_shape_collection):  # noqa: F811
    obj = make_obj(cls)
    obj.ui = MagicMock()
    obj.app.dec_format = lambda value, decimals: round(value, decimals)
    with patch.object(cls, 'bounds', return_value=(1.0, 2.0, 5.0, 3.0)):
        obj.set_offset_values()
    obj.ui.offsetvector_entry.set_value.assert_called_once_with('(3.0, 2.5)')


# ------------------------------------------------------------ optionChanged

@pytest.mark.parametrize('cls', [GerberObject, CNCJobObject])
def test_option_changed_emits_the_key_for_built_objects(cls, no_shape_collection):  # noqa: F811
    obj = make_obj(cls)
    slot = Mock()
    obj.optionChanged.connect(slot)
    with patch.object(cls, 'set_form_item'):
        obj.on_options_change('multicolored')
    slot.assert_called_once_with('multicolored')


@pytest.mark.parametrize('cls', [ScriptObject])
def test_option_changed_emits_the_key_for_script_and_document(cls):
    # these 2 cannot be built with the headless app (their __init__ passes app= to QObject), so only the QObject part
    # is initialized: enough to bind and emit the inherited signal
    obj = cls.__new__(cls)
    QtCore.QObject.__init__(obj)
    slot = Mock()
    obj.optionChanged.connect(slot)
    obj.optionChanged.emit('plot')
    slot.assert_called_once_with('plot')

