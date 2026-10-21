"""Exit Editor: Save (in place) and Save as New for the Geometry, Gerber and Excellon editors. Headless."""

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from PyQt6 import QtCore
from shapely.geometry import Point, box

from appEditors.appExcEditor import AppExcEditor, match_tool_data, tools_with_data
from appEditors.appGerberEditor import AppGerberEditor, edit_copy_name, get_finite_bounds
from appHandlers.appIO import appIO
from appMain import App
from appObjects.GeometryObject import GeometryObject

from test_unify_characterization import (  # noqa: F401  (the fixtures must be visible in this module)
    NATIVE_GBR, _headless_qt, app, make_gerber, make_same_diameter_excellon,
)

BOUNDS_KEYS = ('xmin', 'ymin', 'xmax', 'ymax')


# ---------------------------------------------------------------------------------------------------------------
# the Exit Editor dialog and the flow of each button
# ---------------------------------------------------------------------------------------------------------------

class FakeBox:
    """Stands in for FCMessageBox: records the buttons, 'clicks' the button with the text in FakeBox.click."""
    click = None
    last = None

    def __init__(self, *args, **kwargs):
        self.buttons = {}
        FakeBox.last = self

    def addButton(self, text, role):
        button = SimpleNamespace(text=text, role=role)
        self.buttons[text] = button
        return button

    def clickedButton(self):
        return self.buttons.get(FakeBox.click)

    def __getattr__(self, name):
        return Mock()


def editor_app(kind, empty=False):
    app_stub = MagicMock()
    app_stub.call_source = 'grb_editor'
    app_stub.resource_location = ''
    app_stub.old_state_of_tools_toolbar = False
    app_stub.ui.notebook.count.return_value = 0
    app_stub.history = None
    obj = SimpleNamespace(kind=kind, obj_options={'name': 'obj'}, set_offset_values=Mock(), build_ui=Mock(),
                          plot=Mock(), bounds=Mock(return_value=(0, 0, 1, 1)))
    app_stub.collection.get_active.return_value = obj
    app_stub._edited_obj_is_empty = Mock(return_value=empty)
    app_stub._history_edit_saved = Mock()
    app_stub._history_edit = object()
    return app_stub, obj


def finish(app_stub, click, force_cancel=None):
    FakeBox.click = click
    with patch('appMain.FCMessageBox', FakeBox):
        return App.on_editing_finished(app_stub, force_cancel=force_cancel)


@pytest.mark.parametrize('kind', ['geometry', 'gerber', 'excellon'])
def test_dialog_has_save_save_as_new_no_cancel(kind):
    app_stub, _obj = editor_app(kind)
    finish(app_stub, None)
    assert list(FakeBox.last.buttons) == ['Save', 'Save as New', 'No', 'Cancel']


def test_cncjob_dialog_keeps_yes_no_and_force_cancel():
    app_stub, _obj = editor_app('cncjob')
    finish(app_stub, None)
    assert list(FakeBox.last.buttons) == ['Yes', 'No']
    finish(app_stub, None, force_cancel=True)
    assert list(FakeBox.last.buttons) == ['Yes', 'No', 'Cancel']


def test_gerber_save_updates_in_place_and_records_after_the_update():
    app_stub, obj = editor_app('gerber', empty=True)
    assert finish(app_stub, 'Save') == 'pending'
    app_stub.grb_editor.update_fcgerber.assert_not_called()
    on_complete = app_stub.grb_editor.update_fcgerber_in_place.call_args.kwargs['on_complete']
    # the source is not updated yet: no history step, no teardown
    app_stub._history_edit_saved.assert_not_called()
    app_stub.post_edit_sig.emit.assert_not_called()
    on_complete()
    app_stub._history_edit_saved.assert_called_once_with(obj)
    app_stub.grb_editor.refresh_edited_gerber.assert_called_once_with(obj)
    app_stub.post_edit_sig.emit.assert_called_once()
    # an in-place save never deletes the source, even when it is empty
    app_stub.collection.delete_by_name.assert_not_called()


def test_gerber_save_as_new_keeps_the_source_and_the_empty_source_rule():
    app_stub, obj = editor_app('gerber', empty=True)
    finish(app_stub, 'Save as New')
    app_stub.grb_editor.update_fcgerber.assert_called_once_with()
    app_stub.grb_editor.update_fcgerber_in_place.assert_not_called()
    app_stub.grb_editor.refresh_edited_gerber.assert_not_called()
    app_stub.collection.delete_by_name.assert_called_once_with('obj')
    app_stub._history_edit_saved.assert_not_called()
    assert app_stub._history_edit is None

    app_stub, obj = editor_app('gerber', empty=False)
    finish(app_stub, 'Save as New')
    app_stub.collection.delete_by_name.assert_not_called()


def test_excellon_save_in_place_and_save_as_new():
    app_stub, obj = editor_app('excellon', empty=True)
    assert finish(app_stub, 'Save') == 'pending'
    call = app_stub.exc_editor.update_fcexcellon.call_args
    assert call.args == (obj,) and call.kwargs['in_place'] is True
    app_stub._history_edit_saved.assert_not_called()
    call.kwargs['on_complete']()
    app_stub._history_edit_saved.assert_called_once_with(obj)
    app_stub.exc_editor.refresh_edited_excellon.assert_called_once_with(obj)
    app_stub.collection.delete_by_name.assert_not_called()

    app_stub, obj = editor_app('excellon', empty=True)
    assert finish(app_stub, 'Save as New') == 'pending'
    call = app_stub.exc_editor.update_fcexcellon.call_args
    assert call.args == (obj,) and call.kwargs['in_place'] is False
    app_stub.post_edit_sig.emit.assert_not_called()
    call.kwargs['on_complete']()
    app_stub.collection.delete_by_name.assert_not_called()
    app_stub._history_edit_saved.assert_not_called()
    assert app_stub._history_edit is None


def test_excellon_save_failure_before_the_worker_returns_fail():
    app_stub, _obj = editor_app('excellon')
    app_stub.exc_editor.update_fcexcellon.side_effect = KeyError('boom')
    assert finish(app_stub, 'Save') == 'fail'
    app_stub._history_edit_saved.assert_not_called()


def test_geometry_save_writes_into_the_source():
    app_stub, obj = editor_app('geometry')
    app_stub.geo_editor.update_editor_geometry.return_value = 'pending'
    assert finish(app_stub, 'Save') == 'pending'
    call = app_stub.geo_editor.update_editor_geometry.call_args
    assert call.args == (obj,)
    call.kwargs['on_complete']()
    app_stub._history_edit_saved.assert_called_once_with(obj)
    obj.build_ui.assert_called_once()
    app_stub._copy_geometry_for_save_as_new.assert_not_called()


def test_geometry_save_as_new_writes_into_a_copy_and_leaves_the_source():
    app_stub, obj = editor_app('geometry')
    copy_obj = SimpleNamespace(kind='geometry', obj_options={'name': 'obj_edit'}, set_offset_values=Mock(),
                               build_ui=Mock(), plot=Mock(), bounds=Mock(return_value=(0, 0, 2, 2)))
    app_stub._copy_geometry_for_save_as_new = Mock(return_value=copy_obj)
    app_stub.geo_editor.update_editor_geometry.return_value = 'pending'
    assert finish(app_stub, 'Save as New') == 'pending'
    call = app_stub.geo_editor.update_editor_geometry.call_args
    assert call.args == (copy_obj,)
    call.kwargs['on_complete']()
    copy_obj.build_ui.assert_called_once()
    copy_obj.plot.assert_called_once()
    obj.build_ui.assert_not_called()
    obj.plot.assert_not_called()
    app_stub._history_edit_saved.assert_not_called()
    assert app_stub._history_edit is None


def test_geometry_save_as_new_selects_the_copy(monkeypatch):
    app_stub, _obj = editor_app('geometry')
    copy_obj = SimpleNamespace(kind='geometry', obj_options={'name': 'obj_edit'}, set_offset_values=Mock(),
                               build_ui=Mock(), plot=Mock(), bounds=Mock(return_value=(0, 0, 2, 2)))
    app_stub._copy_geometry_for_save_as_new = Mock(return_value=copy_obj)
    app_stub.geo_editor.update_editor_geometry.return_value = 'pending'
    queued = []
    monkeypatch.setattr(QtCore.QTimer, 'singleShot', lambda _ms, fn: queued.append(fn))
    finish(app_stub, 'Save as New')
    app_stub.geo_editor.update_editor_geometry.call_args.kwargs['on_complete']()
    # the selection waits for the editor teardown
    app_stub.collection.set_active.assert_not_called()
    for fn in queued:
        fn()
    app_stub.collection.set_active.assert_called_once_with('obj_edit')


def test_geometry_save_as_new_removes_the_copy_when_the_save_is_rejected():
    app_stub, _obj = editor_app('geometry')
    copy_obj = SimpleNamespace(obj_options={'name': 'obj_edit'})
    app_stub._copy_geometry_for_save_as_new = Mock(return_value=copy_obj)
    app_stub.geo_editor.update_editor_geometry.return_value = 'fail'
    assert finish(app_stub, 'Save as New') == 'fail'
    app_stub.collection.delete_by_name.assert_called_once_with('obj_edit')


# ---------------------------------------------------------------------------------------------------------------
# names, bounds
# ---------------------------------------------------------------------------------------------------------------

def test_edit_copy_name():
    assert edit_copy_name('board') == 'board_edit'
    assert edit_copy_name('board_edit') == 'board_edit_1'
    assert edit_copy_name('board_edit_1') == 'board_edit_2'


def test_get_finite_bounds():
    assert get_finite_bounds(SimpleNamespace(bounds=lambda: (1, 2, 3, 4))) == (1.0, 2.0, 3.0, 4.0)
    assert get_finite_bounds(SimpleNamespace(bounds=lambda: (float('inf'), 0, -float('inf'), 0))) == (0.0,) * 4

    def broken():
        raise ValueError('empty')
    assert get_finite_bounds(SimpleNamespace(bounds=broken)) == (0.0,) * 4


# ---------------------------------------------------------------------------------------------------------------
# Geometry: Save as New copy
# ---------------------------------------------------------------------------------------------------------------

def test_geometry_copy_for_save_as_new(app):
    source = GeometryObject('geo', app)
    source.solid_geometry = [box(0, 0, 4, 4)]
    source.obj_options['tools_mill_tooldia'] = 0.37
    source.obj_options['name'] = 'geo'
    created = {}

    def new_object(kind, name, initialize, **kwargs):
        obj = GeometryObject(name, app)
        initialize(obj, app)
        created.update(obj=obj, kind=kind, name=name, kwargs=kwargs)
        return obj

    stub = SimpleNamespace(app_obj=SimpleNamespace(new_object=new_object), log=Mock(), inform=Mock())
    copy_obj = App._copy_geometry_for_save_as_new(stub, source)
    assert copy_obj is created['obj'] and created['kind'] == 'geometry' and created['name'] == 'geo_edit'
    assert created['kwargs'] == {'plot': False, 'autoselected': False, 'record_history': False}
    assert copy_obj.obj_options['tools_mill_tooldia'] == 0.37
    assert copy_obj.solid_geometry == source.solid_geometry and copy_obj.solid_geometry is not source.solid_geometry
    assert source.obj_options['name'] == 'geo'


def test_geometry_copy_failure_gives_none(app):
    stub = SimpleNamespace(app_obj=SimpleNamespace(new_object=Mock(return_value='fail')), log=Mock(), inform=Mock())
    source = GeometryObject('geo', app)
    assert App._copy_geometry_for_save_as_new(stub, source) is None
    stub.inform.emit.assert_called_once()


# ---------------------------------------------------------------------------------------------------------------
# Gerber
# ---------------------------------------------------------------------------------------------------------------

def gerber_storage(source, drop_first_aperture=False):
    storage = {}
    for ap, tool in source.tools.items():
        storage[ap] = {k: v for k, v in tool.items() if k != 'geometry'}
        storage[ap]['geometry'] = [SimpleNamespace(geo=dict(rec)) for rec in tool['geometry']]
    if drop_first_aperture:
        storage.pop(next(ap for ap in storage if storage[ap]['geometry']))
    return storage


def gerber_stand_in(app, source, storage):
    app.f_handlers = appIO(app)
    app.app_units = 'MM'
    app.custom_signal = MagicMock()
    app.main_thread = QtCore.QThread.currentThread()
    return SimpleNamespace(app=app, gerber_obj=source, gerber_obj_options=source.obj_options, results=[1],
                           loaded_as_regions=False, storage_dict=storage, edited_obj_name=source.obj_options['name'])


def non_bounds_options(obj):
    return {k: v for k, v in obj.obj_options.items() if k not in BOUNDS_KEYS}


def test_gerber_in_place_apply_keeps_identity_and_replaces_content(app):
    source = make_gerber(app, NATIVE_GBR, name='board')
    uid = source.history_uid
    options = non_bounds_options(source)
    apertures_before = set(source.tools)
    stand_in = gerber_stand_in(app, source, gerber_storage(source, drop_first_aperture=True))

    AppGerberEditor.build_edited_gerber(stand_in, 'board', stand_in.storage_dict)
    # the build did not touch the source
    assert set(source.tools) == apertures_before
    result = app.custom_signal.emit.call_args.args[0]
    edited = result['obj']
    assert edited is not source and len(edited.tools) == len(apertures_before) - 1

    AppGerberEditor.apply_edited_gerber(source, edited)
    assert source.history_uid == uid and source.obj_options['name'] == 'board'
    assert non_bounds_options(source) == options
    assert set(source.tools) == set(edited.tools) and len(source.tools) == len(apertures_before) - 1
    assert source.solid_geometry is edited.solid_geometry
    assert source.source_file and source.source_file == edited.source_file
    assert tuple(source.obj_options[k] for k in BOUNDS_KEYS) == pytest.approx(edited.bounds())


def test_gerber_in_place_build_failure_leaves_the_source_unchanged(app):
    source = make_gerber(app, NATIVE_GBR, name='board')
    tools_before = repr(sorted(source.tools))
    solid_before = source.solid_geometry
    storage = gerber_storage(source)
    storage[next(iter(storage))]['geometry'] = [SimpleNamespace(geo=None)]
    stand_in = gerber_stand_in(app, source, storage)

    AppGerberEditor.build_edited_gerber(stand_in, 'board', storage)
    result = app.custom_signal.emit.call_args.args[0]
    assert 'obj' not in result and result['error']

    handlers = []
    app.connect_custom_signal = lambda target, params: handlers.append(target)
    stand_in.deactivate_grb_editor = Mock()
    stand_in.build_edited_gerber = Mock()
    on_complete = Mock()
    AppGerberEditor.update_fcgerber_in_place(stand_in, on_complete=on_complete)
    handlers[0](result)
    stand_in.deactivate_grb_editor.assert_not_called()
    on_complete.assert_not_called()
    assert app.inform.emit.call_args.args[0].startswith('[ERROR_NOTCL]')
    assert repr(sorted(source.tools)) == tools_before and source.solid_geometry is solid_before


def test_gerber_in_place_handler_applies_then_deactivates_then_completes(app):
    source = make_gerber(app, NATIVE_GBR, name='board')
    stand_in = gerber_stand_in(app, source, gerber_storage(source, drop_first_aperture=True))
    AppGerberEditor.build_edited_gerber(stand_in, 'board', stand_in.storage_dict)
    result = app.custom_signal.emit.call_args.args[0]

    handlers, order = [], []
    app.connect_custom_signal = lambda target, params: handlers.append(target)
    app.worker_task = Mock()
    stand_in.deactivate_grb_editor = lambda: order.append(('deactivate', len(source.tools)))
    stand_in.build_edited_gerber = Mock()
    AppGerberEditor.update_fcgerber_in_place(stand_in, on_complete=lambda: order.append(('complete', len(source.tools))))
    task = app.worker_task.emit.call_args.args[0]
    assert task['fcn'] is stand_in.build_edited_gerber and task['params'][0] == 'board'
    handlers[0](result)
    count = len(result['obj'].tools)
    # the source has the new content when the editor is deactivated and when the continuation runs
    assert order == [('deactivate', count), ('complete', count)]


def test_gerber_save_as_new_posts_a_new_name_and_leaves_the_source(app):
    source = make_gerber(app, NATIVE_GBR, name='board')
    tools_before = repr(source.tools)
    solid_before = source.solid_geometry
    stand_in = gerber_stand_in(app, source, gerber_storage(source, drop_first_aperture=True))
    handlers = []
    app.connect_custom_signal = lambda target, params: handlers.append(target)
    app.worker_task = Mock()
    stand_in.deactivate_grb_editor = Mock()
    AppGerberEditor.update_fcgerber(stand_in)
    task = app.worker_task.emit.call_args.args[0]
    assert task['params'][0] == 'board_edit'

    created = {}

    def new_object(kind, name, initialize, *args, **kwargs):
        new_obj = type(source)(name, app)
        initialize(new_obj, app)
        created[name] = new_obj

    app.app_obj.new_object.side_effect = new_object
    app.custom_signal = MagicMock()
    task['fcn'](*task['params'])
    handlers[0](app.custom_signal.emit.call_args.args[0])
    stand_in.deactivate_grb_editor.assert_called_once()
    new_obj = created['board_edit']
    assert new_obj.history_uid != source.history_uid and new_obj.obj_options['name'] == 'board_edit'
    assert len(new_obj.tools) == len(source.tools) - 1
    assert repr(source.tools) == tools_before and source.solid_geometry is solid_before
    assert source.obj_options['name'] == 'board'


# ---------------------------------------------------------------------------------------------------------------
# Excellon
# ---------------------------------------------------------------------------------------------------------------

def tools(*dias):
    return {i + 1: {'tooldia': dia} for i, dia in enumerate(dias)}


def test_match_tool_data_follows_a_renumbering():
    assert match_tool_data(tools(0.8, 1.0), tools(1.0, 0.8), {0.8: 0.8, 1.0: 1.0}, 4) == {1: 2, 2: 1}


def test_match_tool_data_follows_a_diameter_edit():
    assert match_tool_data(tools(0.8), tools(1.2), {0.8: 1.2}, 4) == {1: 1}


def test_match_tool_data_new_tool_has_no_match_and_does_not_steal():
    assert match_tool_data(tools(0.8), tools(3.0), {0.8: 0.8}, 4) == {1: None}
    # the old 0.8 tool became 1.0: a new 0.8 tool is a different tool
    assert match_tool_data(tools(0.8), tools(0.8, 1.0), {0.8: 1.0}, 4) == {1: None, 2: 1}


def test_match_tool_data_uses_each_old_tool_once_and_rounds():
    assert match_tool_data(tools(1.0, 1.0), tools(1.0, 1.0, 1.0), {}, 4) == {1: 1, 2: 2, 3: None}
    assert match_tool_data(tools(1.00001), tools(1.0), {}, 4) == {1: 1}


def test_tools_with_data_keeps_data_and_defaults_the_new_tool():
    old = {1: {'tooldia': 1.0, 'data': {'cutz': -1.7}}, 2: {'tooldia': 2.0, 'data': {}}}
    new = {1: {'tooldia': 1.0, 'drills': [Point(0, 0)]}, 2: {'tooldia': 2.0}, 3: {'tooldia': 5.0}}
    result = tools_with_data(old, new, {1.0: 1.0, 2.0: 2.0}, {'cutz': -9}, 4)
    assert result[1]['data'] == {'cutz': -1.7}
    # an old tool without data and a tool with no match get the defaults
    assert result[2]['data'] == {'cutz': -9} and result[3]['data'] == {'cutz': -9}
    # copies: the source data is not shared
    assert result[1]['data'] is not old[1]['data'] and 'data' not in new[1]


def test_excellon_in_place_apply_keeps_identity_options_and_tool_data(app):
    source = make_same_diameter_excellon(app, name='holes')
    uid = source.history_uid
    options = non_bounds_options(source)
    app.f_handlers = appIO(app)
    app.custom_signal = MagicMock()
    app.main_thread = QtCore.QThread.currentThread()
    new_tools = {
        1: {'tooldia': 1.0, 'drills': [Point(5, 5)], 'solid_geometry': []},
        2: {'tooldia': 2.5, 'drills': [Point(1, 1)], 'solid_geometry': []},
    }
    built = []

    def submit(build, commit):
        # the build runs detached from the source, the commit changes the source
        edited = build()
        built.append(edited)
        assert len(source.tools) == 2 and source.tools[1]['data']['tag'] == 'first'
        assert edited is not source
        commit(edited)

    stand_in = SimpleNamespace(app=app, edited_obj=source, edited_obj_name='holes', new_tools=new_tools,
                               olddia_newdia={1.0: 1.0}, data_defaults={'default': True}, decimals=4,
                               storage_dict={}, units=source.units.upper(), deactivate=Mock(),
                               history=SimpleNamespace(submit=submit))

    AppExcEditor._queue_excellon_save(stand_in, source, True, None)
    edited = built[0]
    assert source.history_uid == uid and source.obj_options['name'] == 'holes'
    assert non_bounds_options(source) == options
    assert set(source.tools) == {1, 2}
    assert source.tools[1]['data']['tag'] == 'first' and source.tools[1]['data']['cutz'] == -1.7
    assert source.tools[2]['data'] == {'default': True}
    assert [(p.x, p.y) for p in source.tools[1]['drills']] == [(5, 5)]
    assert len(source.solid_geometry) == 2
    assert source.source_file
    assert tuple(source.obj_options[k] for k in BOUNDS_KEYS) == pytest.approx(edited.bounds())


def test_excellon_save_as_new_queues_the_save_and_leaves_the_source_unchanged(app):
    source = make_same_diameter_excellon(app, name='holes')
    tools_before = repr(source.tools)
    new_tools = {1: {'tooldia': 1.0, 'drills': [Point(5, 5)], 'solid_geometry': []}}
    app.main_thread = QtCore.QThread.currentThread()
    app.f_handlers = appIO(app)
    submitted = []
    stand_in = SimpleNamespace(
        app=app, edited_obj=source, edited_obj_name='holes', is_modified=True, new_tools=new_tools,
        olddia_newdia={1.0: 1.0}, data_defaults={}, decimals=4, storage_dict={}, units=source.units.upper(),
        deactivate=Mock(), history=SimpleNamespace(
            ready=lambda: True, pending=None, submit=lambda build, commit: submitted.append(build) or 'pending'),
    )
    assert AppExcEditor.update_fcexcellon(stand_in, source) == 'pending'
    # the save is queued; the source is not touched
    assert len(submitted) == 1
    assert repr(source.tools) == tools_before and source.obj_options['name'] == 'holes'
