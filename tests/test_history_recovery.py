"""Transactional replay and exact lightweight transform metadata regressions."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from shapely.geometry import Point

from appCommon.Common import LoudDict
from appHandlers.appHistory import (HistoryManager, MatrixStep, SnapshotStep, GroupStep, CreateStep,
                                    DeleteStep, RenameStep, object_state, transform_metadata, retained_sizes,
                                    states_equal)
from appHandlers.appObjectOps import AppObjectOps
from test_app_history import fake_app


class Object:
    kind = 'geometry'
    ser_attrs = ['obj_options', 'solid_geometry']

    def __init__(self, uid):
        self.history_uid = uid
        self.obj_options = LoudDict(name=uid, plot=True)
        self.solid_geometry = [Point(1, 2)]
        self.multigeo = False
        self.plot = Mock()
        self.set_offset_values = Mock()

    def from_dict(self, state):
        self.obj_options.update(state['obj_options'])
        self.solid_geometry = state['solid_geometry']

    def bounds(self):
        return self.solid_geometry[0].bounds


def setup_history():
    objects = [Object('a'), Object('b')]
    app = fake_app()
    collection = SimpleNamespace(get_list=lambda: list(objects))
    collection.rename_object = lambda obj, name: obj.obj_options.__setitem__('name', name)
    h = HistoryManager(app, collection)
    app.history = h
    app.app_obj = SimpleNamespace(object_changed=Mock())
    h.delete_objects = lambda objs: [objects.remove(obj) for obj in objs]

    def rebuild(state):
        obj = Object(state['history_uid'])
        objects.append(obj)
        h.restore_state(obj, state)
    h.rebuild = rebuild
    return h, objects


@pytest.mark.parametrize('matrix', [(1, 0, 0, 0, 0, 0), (np.nan, 0, 0, 1, 0, 0),
                                    (1, 0, 0, 1, np.inf, 0), (1, 0, 0, 1)])
def test_invalid_matrix_prevalidated_before_any_mutation(matrix):
    h, objects = setup_history()
    original = objects[0].solid_geometry[0]
    h.push(MatrixStep('bad', [('a', (1, 0, 0, 1, 3, 0)), ('b', matrix)]))
    assert not h.undo()
    assert objects[0].solid_geometry[0] is original
    assert h.can_undo() and not h.can_redo()


def test_missing_object_prevalidated_before_group_mutation():
    h, objects = setup_history()
    original = object_state(objects[0])
    h.push(GroupStep('missing', [MatrixStep('missing', [('gone', (1, 0, 0, 1, 3, 0))]),
                                 MatrixStep('move', [('a', (1, 0, 0, 1, 3, 0))])]))
    assert not h.undo()
    assert states_equal(object_state(objects[0]), original)
    assert h.undo_label() == 'missing'


def test_partial_group_rolls_back_and_can_retry():
    h, objects = setup_history()
    a, b = objects
    before = object_state(a)
    a.solid_geometry = [Point(8, 9)]
    after = object_state(a)
    # Undo runs the snapshot before the matrix; plotting b then fails once.
    b.plot.side_effect = [RuntimeError('plot'), None, None]
    h.push(GroupStep('group', [MatrixStep('move', [('b', (1, 0, 0, 1, 2, 0))]),
                               SnapshotStep('edit', [('a', before, after)])]))
    assert not h.undo()
    assert states_equal(object_state(a), after)
    assert b.solid_geometry[0].equals_exact(Point(1, 2), 0)
    assert h.undo_label() == 'group'
    assert h.undo()
    assert a.solid_geometry[0].equals_exact(Point(1, 2), 0)


def test_failed_rollback_invalidates_history():
    h, objects = setup_history()
    objects[0].plot.side_effect = RuntimeError('persistent plot failure')
    h.push(MatrixStep('move', [('a', (1, 0, 0, 1, 2, 0))]))
    assert not h.undo()
    assert not h.can_undo() and not h.can_redo()
    assert any('recovery incomplete' in call.args[0] for call in h.app.inform.emit.call_args_list)


def test_partial_create_undo_restores_membership_and_bookkeeping():
    h, objects = setup_history()
    original_delete = h.delete_objects

    def fail(objs):
        original_delete(objs[:1])
        raise RuntimeError('partial delete')
    h.delete_objects = fail
    step = CreateStep('create', ['a', 'b'])
    h.push(step)
    assert not h.undo()
    assert {obj.history_uid for obj in objects} == {'a', 'b'}
    assert step.states == {} and step.geometry_sizes() == {}
    h.delete_objects = original_delete
    assert h.undo() and not objects
    assert h.redo() and len(objects) == 2


def test_partial_delete_undo_removes_rebuilt_objects_on_failure():
    h, objects = setup_history()
    step = DeleteStep('delete', [object_state(obj) for obj in objects])
    objects.clear()
    rebuild = h.rebuild
    calls = []

    def fail(state):
        calls.append(state)
        if len(calls) == 2:
            raise RuntimeError('partial rebuild')
        rebuild(state)
    h.rebuild = fail
    h.push(step)
    assert not h.undo()
    assert objects == [] and h.undo_label() == 'delete'
    h.rebuild = rebuild
    assert h.undo() and len(objects) == 2


def test_rename_conflict_prevalidated_and_partial_rename_recovered():
    h, objects = setup_history()
    h.push(RenameStep('conflict', [('a', 'b', 'a')]))
    assert not h.undo()
    assert objects[0].obj_options['name'] == 'a'
    h.clear()
    step = RenameStep('rename', [('a', 'old_a', 'a'), ('b', 'old_b', 'b')])
    rename = h.rename
    calls = []

    def fail(obj, name):
        calls.append(name)
        if len(calls) == 2:
            raise RuntimeError('rename')
        rename(obj, name)
    h.rename = fail
    h.push(step)
    assert not h.undo()
    assert [obj.obj_options['name'] for obj in objects] == ['a', 'b']
    h.rename = rename
    assert h.undo()


def test_matrix_metadata_options_presence_roundtrip():
    h, objects = setup_history()
    obj = objects[0]
    before = transform_metadata(obj)
    obj.solid_geometry = [Point(3, 2)]
    obj.obj_options['offset_x'] = 2
    h.record_matrix('move', [(obj, (1, 0, 0, 1, 2, 0), before)])
    assert h.undo() and 'offset_x' not in obj.obj_options
    assert h.redo() and obj.obj_options['offset_x'] == 2


def test_snapshot_replay_keeps_callback_and_refreshes_visibility_after_restore():
    h, objects = setup_history()
    obj = objects[0]
    obj.shapes = SimpleNamespace(visible=True)
    obj.optionChanged = Mock()
    options = obj.obj_options
    callback = Mock()
    options.set_change_callback(callback)
    with h.snapshot('visibility', [obj]):
        options['plot'] = False
        options['temporary'] = True
    callback.reset_mock()
    obj.optionChanged.emit.side_effect = lambda key: (
        obj.shapes.visible == obj.obj_options['plot'] or pytest.fail('incomplete restoration'))
    assert h.undo()
    assert obj.obj_options is options and options.callback is callback
    assert obj.shapes.visible and 'temporary' not in options
    callback.assert_not_called()
    obj.optionChanged.emit.assert_any_call('temporary')
    assert h.redo() and not obj.shapes.visible
    options['plot'] = True
    callback.assert_called_once_with('plot')


def test_exact_snapshot_comparison_and_mixed_changes():
    h, objects = setup_history()
    with h.snapshot('mixed', objects):
        objects[1].obj_options['value'] = np.array([1, 2])
    assert [uid for uid, _b, _a in h.undo_stack[-1].items] == ['b']
    assert states_equal({'a': [np.array([1, 2]), Point(1, 2)]}, {'a': [np.array([1, 2]), Point(1, 2)]})
    assert not states_equal(Point(1, 2), Point(1 + 1e-12, 2))


def test_non_geometry_identity_dedup_and_numpy_storage():
    text = 'x' * 2000000
    array = np.arange(100)
    state = {'source_file': text, 'gcode_parsed': [{'x': array, 'same': text}]}
    sizes = retained_sizes(state, state)
    assert sum(sizes.values()) >= len(text) + array.nbytes
    assert len([key for key in sizes if key == ('storage', id(text))]) == 1


def test_create_acquired_storage_retains_newest_replay_and_releases_on_redo():
    h, objects = setup_history()
    h.app.options['global_history_memory_mb'] = 1
    objects[0].obj_options['text'] = 'x' * 2000000
    h.push(MatrixStep('older', [('b', (1, 0, 0, 1, 1, 0))]))
    h.push(CreateStep('newest', ['a']))
    assert h.undo()
    assert h.redo_label() == 'newest'
    assert h.total_size() >= 2000000
    assert h.redo()
    assert h.total_size() < 2000000


def test_merge_refreshes_non_geometry_accounting():
    h, _objects = setup_history()
    h.push(SnapshotStep('edit', [('a', {}, {'text': 'x' * 2000000})], merge_key='text'))
    assert h.total_size() >= 2000000
    h.push(SnapshotStep('edit', [('a', {}, {'text': 'small'})], merge_key='text'))
    assert len(h.undo_stack) == 1
    assert h.total_size() < 10000


@pytest.mark.parametrize('bulk', [False, True])
def test_delete_inactive_keeps_surviving_properties(bulk):
    active, gone, other = Object('active'), Object('gone'), Object('other')
    objects = [active, gone, other]
    collection = SimpleNamespace(get_list=lambda: objects, get_active=lambda: active,
                                 delete_objects=lambda selected: [objects.remove(obj) for obj in selected])
    app = SimpleNamespace(collection=collection, setup_default_properties_tab=Mock(),
                          delete_selection_shape=Mock(), exc_areas=Mock())
    holder = SimpleNamespace(app=app, inform=Mock(), log=Mock())
    AppObjectOps.delete_objects_now(holder, [gone, other] if bulk else [gone])
    app.setup_default_properties_tab.assert_not_called()
    assert active in objects
