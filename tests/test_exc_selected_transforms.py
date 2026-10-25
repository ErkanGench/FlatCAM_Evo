"""Selected native transforms use the real editor transaction and storage paths."""

from types import MethodType
from unittest.mock import Mock, MagicMock

import pytest

from appEditors.appExcEditor import AppExcEditor
from appEditors.exc_plugins.ExcProperties import native_feature_properties
from test_exc_editor_history import scene, drill
from tests.helpers_objects import app, _headless_qt, reparse_excellon  # noqa: F401,E402
from appHandlers.appIO import appIO
from PyQt6 import QtCore


def editor_scene():
    editor, drill, slot = scene()
    editor.transform_features = MethodType(AppExcEditor.transform_features, editor)
    return editor, drill, slot


@pytest.mark.parametrize('operation,value,reference,expected', [
    ('rotate', 90, 'origin', (-0.5, 5)),
    ('mirror_x', 1, 'origin', (5, -0.5)),
    ('mirror_y', 1, 'origin', (-5, 0.5)),
    ('rotate', 180, (2, 3), (-1, 5.5)),
    ('scale', 2, (2, 3), (8, -2)),
])
def test_native_slot_transform_and_history(operation, value, reference, expected):
    editor, drill, slot = editor_scene()
    editor.selected = [slot]
    assert editor.transform_features(operation, value, reference) != 'fail'
    transformed = editor.selected[0]
    diameter = 2 if operation == 'scale' else 1
    record = native_feature_properties(transformed, diameter, 0)
    assert record['center'] == pytest.approx(expected)
    assert len(transformed.exc_slot) == 2
    assert drill in editor.storage_dict[1].get_objects()
    assert len(editor.history.undo_stack) == 1
    assert editor.history.revision == 1
    assert editor.undo()
    assert editor.selected == [slot]
    assert editor.redo()
    assert editor.selected == [transformed]


@pytest.mark.parametrize('operation,value,reference', [
    ('scale', 0, 'origin'), ('scale', -2, 'origin'), ('scale', float('inf'), 'origin'),
    ('rotate', float('nan'), 'origin'), ('shear', 2, 'origin'),
    ('scale', (2, 3), 'origin'), ('rotate', 90, (float('nan'), 1)),
])
def test_invalid_transform_is_atomic(operation, value, reference):
    editor, drill, slot = editor_scene()
    assert editor.transform_features(operation, value, reference) == 'fail'
    assert list(editor.storage_dict[1].get_objects()) == [drill, slot]
    assert not editor.history.undo_stack
    assert not editor.is_modified


@pytest.mark.parametrize('source_units', ['MM'])
@pytest.mark.parametrize('editor_units', ['MM', 'IN'])
@pytest.mark.parametrize('export_units', ['METRIC'])
@pytest.mark.parametrize('in_place', [True])
@pytest.mark.parametrize('string_ids', [True])
@pytest.mark.parametrize('export_format', ['dec', 'ndec'])
def test_source_loader_transform_save_native_unit_roundtrip(app, tmp_path, source_units, editor_units,
                                                           export_units, in_place, string_ids, export_format):
    header = 'METRIC' if source_units == 'MM' else 'INCH'
    text = 'M48\n%s,TZ\nT01C0.100\nT02C0.200\n%%\nT01\nX1.0Y2.0\nX3.0Y4.0\nT02\nX5.0Y6.0G85X7.0Y9.0\nM30\n' % header
    source = reparse_excellon(app, text, tmp_path, name='source')
    source.tools[1]['data'] = {'tag': 'drill'}
    source.tools[2]['data'] = {'tag': 'slot'}
    if string_ids:
        source.tools = {str(key): values for key, values in source.tools.items()}
    original = source.tools
    editor, _, _ = editor_scene()
    editor.app, editor.units, editor.decimals = app, editor_units, 8
    app.app_units = editor_units    # the editor takes its units from the application when it loads
    editor.storage_dict.clear()
    editor.selected.clear()
    editor.dec_format = lambda value: round(value, 8)
    editor.deactivate, editor.activate, editor.set_editor_ui = Mock(), Mock(), Mock()
    editor.on_tool_edit = Mock()
    editor._save_excellon_in_place = MethodType(AppExcEditor._save_excellon_in_place, editor)
    editor.ui = MagicMock()
    AppExcEditor.edit_fcexcellon(editor, source)
    editor.edited_obj_name = 'source'
    factor = 1 if source_units == editor_units else (25.4 if editor_units == 'MM' else 1 / 25.4)
    diameters = sorted(editor.storage_dict)
    first, untouched = list(editor.storage_dict[diameters[0]].get_objects())
    slot = next(iter(editor.storage_dict[diameters[1]].get_objects()))
    assert first.geo.centroid.x == pytest.approx(factor)
    editor.selected = [first, slot]
    editor.transform_features('rotate', 37)
    editor.transform_features('scale', 1.5)
    expected = [(diameter, native_feature_properties(shape, diameter, 0))
                for diameter, storage in editor.storage_dict.items() for shape in storage.get_objects()]
    assert untouched.geo.centroid.x == pytest.approx(3 * factor)
    assert source.tools is original and source.units == source_units
    editor.worker_result = Mock()
    editor.deactivate = Mock(side_effect=editor.history.reset)
    app.worker_task = Mock()
    app.app_units = editor_units
    app.f_handlers = appIO(app)
    app.options['excellon_exp_units'] = export_units
    app.options['excellon_exp_decimals'] = 8
    app.options['excellon_exp_format'] = export_format
    app.main_thread = QtCore.QThread.currentThread()
    created = []

    def create(kind, name, initialize):
        obj = type(source)(name, app=app)
        initialize(obj, app)
        created.append(obj)
        return obj

    app.app_obj.new_object.side_effect = create
    assert AppExcEditor.update_fcexcellon(editor, source, in_place=in_place) == 'pending'
    app.worker_task.emit.call_args.args[0]['fcn']()
    assert 'error' not in editor.worker_result.emit.call_args.args[0], app.log.error.call_args_list
    editor.history.finish(editor.worker_result.emit.call_args.args[0])
    saved = source if in_place else created[0]
    assert saved.units == editor_units
    again = reparse_excellon(app, saved.source_file, tmp_path)
    output_factor = 1 if again.units == editor_units else (25.4 if editor_units == 'MM' else 1 / 25.4)
    actual = []
    actual_slots = []
    for values in again.tools.values():
        diameter = values['tooldia'] * output_factor
        actual.extend((diameter, (point.x * output_factor, point.y * output_factor))
                      for point in values.get('drills', []))
        for start, stop in values.get('slots', []):
            actual_slots.append(((start.x * output_factor, start.y * output_factor),
                                 (stop.x * output_factor, stop.y * output_factor)))
            actual.append((diameter, ((start.x + stop.x) / 2 * output_factor,
                                      (start.y + stop.y) / 2 * output_factor)))
    assert len(actual) == len(expected)
    for diameter, record in expected:
        assert any(abs(diameter - d) < 1e-6 and center == pytest.approx(record['center'], abs=1e-6)
                   for d, center in actual)
        if record['type'] == 'slot':
            assert any(all(point == pytest.approx(wanted, abs=1e-6)
                           for point, wanted in zip(sorted(endpoints), sorted(record['endpoints'])))
                       for endpoints in actual_slots)
    assert {values['data']['tag'] for values in saved.tools.values()} == {'drill', 'slot'}
    if not in_place:
        assert source.tools is original and source.units == source_units


def test_transform_order_merge_and_rollback():
    editor, first, slot = editor_scene()
    editor.transform_features('rotate', 45)
    assert list(editor.storage_dict[1].get_objects()) == [editor.selected[0], slot]
    assert editor.undo()
    target = editor.make_storage()
    other = drill(10)
    target.insert_many([other])
    editor.storage_dict[2] = target
    editor.points_edit[2], editor.slot_points_edit[2] = [(10, 0)], []
    editor.olddia_newdia[2] = 2
    editor.tool2tooldia['second'] = 2
    editor.transform_features('scale', 2)
    assert list(editor.storage_dict) == [1, 2]
    assert list(target.get_objects()) == [other, editor.selected[0]]
    assert editor.undo()
    editor.build_ui.side_effect = RuntimeError('render failed')
    with pytest.raises(RuntimeError, match='render failed'):
        editor.transform_features('rotate', 17)
    assert list(editor.storage_dict[1].get_objects()) == [first, slot]
    assert editor.selected == [first]


