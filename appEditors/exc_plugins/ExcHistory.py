"""Excellon-local grouped transactions over immutable Shapely values and wrapper deltas."""

from contextlib import contextmanager
from functools import wraps
from threading import get_ident
import builtins
import gettext

from appHandlers.appHistory import HistoryManager, state_size

_ = builtins.__dict__.get('_', gettext.gettext)


def excellon_operation(label, generic=False, selected=False):
    """Group the changes of the decorated method in one undo step.

    :param label:   label of the step; pass a literal wrapped in _() at the decoration site, so it is extractable
    :param generic: True for a wrapper operation: a nested operation gives its own label to the step
    :param selected: Capture only source/target tools of a native selected-feature transform.
    """
    def decorate(method):
        @wraps(method)
        def operation(self, *args, **kwargs):
            editor = self if hasattr(self, 'storage_dict') else self.draw_app
            history = getattr(editor, 'history', None)
            if not isinstance(history, ExcellonHistory) or history.suspended:
                return method(self, *args, **kwargs)
            scope = None
            if selected and not history.depth:
                scope = {key for key, storage in editor.storage_dict.items()
                         if any(id(shape) in storage.indexes and
                                storage.objects[storage.indexes[id(shape)]] is shape for shape in editor.selected)}
                if (args[0] if args else kwargs.get('operation')) == 'scale':
                    try:
                        factor = float(args[1] if len(args) > 1 else kwargs.get('value', 1.0))
                        scope.update(key * factor for key in tuple(scope))
                    except (ValueError, TypeError, OverflowError):
                        pass  # the native transform reports invalid input without changing storage
            with history.operation(label, generic, scope=scope) as accepted:
                if not accepted:
                    return 'fail'
                result = method(self, *args, **kwargs)
                if result == 'fail':
                    history.failed = True
                return result
        return operation
    return decorate


def excellon_session(method):
    @wraps(method)
    def load(self, *args, **kwargs):
        if not self.history.ready():
            return 'fail'
        self.history.reset()
        self.history.suspended = True
        try:
            return method(self, *args, **kwargs)
        finally:
            self.history.suspended = False
            self.is_modified = False
            self.history.reset()
    return load


class ExcellonHistory:
    def __init__(self, editor):
        self.editor = editor
        self.gui_thread = get_ident()
        self.depth = 0
        self.session = 0
        self.revision = 0
        self.pending = None
        self.replaying = False
        self.suspended = False
        self.undo_stack = []
        self.redo_stack = []
        self.baseline_evicted = False
        self.step_label = ''
        self.step_generic = False

    def notify(self):
        self.editor._exc_snap_index = None
        self.editor.history_changed.emit()

    def reset(self):
        self.session += 1
        self.pending = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.baseline_evicted = False
        self.notify()

    def ready(self):
        if get_ident() != self.gui_thread:
            self.editor.app.inform.emit('[WARNING_NOTCL] %s' % _("Editor changes must run on the GUI thread."))
            return False
        return True

    def submit(self, work, apply):
        if not self.ready() or self.pending is not None or self.depth or self.suspended:
            return 'fail'
        token = object()
        self.pending = (token, self.session, self.revision, apply)
        self.notify()

        def run():
            try:
                result = {'token': token, 'value': work()}
            except Exception as error:
                result = {'token': token, 'error': str(error)}
            self.editor.worker_result.emit(result)

        try:
            self.editor.app.worker_task.emit({'fcn': run, 'params': []})
        except Exception:
            self.pending = None
            self.notify()
            raise
        return 'pending'

    def finish(self, result):
        if not self.ready() or not isinstance(result, dict) or self.pending is None:
            return
        token, session, revision, apply = self.pending
        if result.get('token') is not token:
            return
        try:
            if (session, revision) != (self.session, self.revision):
                return
            if 'error' in result:
                raise ValueError(result['error'])
            apply(result['value'])
        except Exception as error:
            self.editor.app.log.error('Excellon editor worker --> %s' % str(error))
            self.editor.app.inform.emit('[ERROR_NOTCL] %s' % _("The edited content could not be saved."))
        finally:
            # A continuation may have reset the session and started another operation.
            if self.pending is not None and self.pending[0] is token:
                self.pending = None
            self.notify()

    def state(self):
        editor = self.editor
        return {'selection': tuple(editor.selected), 'last': editor.last_tool_selected,
                'modified': editor.is_modified, 'order': tuple(editor.storage_dict),
                'aliases': dict(editor.olddia_newdia), 'tools': dict(editor.tool2tooldia)}

    def counters(self, scope=None):
        return {name: {key: tuple(values) for key, values in getattr(self.editor, name).items()
                       if scope is None or key in scope}
                for name in ('points_edit', 'slot_points_edit')}

    @contextmanager
    def operation(self, label, generic=False, scope=None):
        if not self.ready() or self.pending is not None:
            yield False
            return
        if self.replaying or self.suspended:
            yield True
            return
        outer = self.depth == 0
        if outer:
            self.step_label, self.step_generic = label, generic
        elif self.step_generic and not generic:
            # the innermost real operation names the step, not the generic wrapper
            self.step_label, self.step_generic = label, False
        before, counters, storages, records = {}, {}, {}, {}
        if outer:
            before = self.state()
            counters = self.counters(scope)
            # Transient references only. Retained steps below contain only changed records;
            # immutable Shapely values aren't copied or serialized for every board edit.
            storages = {key: storage for key, storage in self.editor.storage_dict.items()
                        if scope is None or key in scope}
            records = {key: tuple((shape, shape.geo) for shape in storage.get_objects())
                       for key, storage in storages.items()}
            self.failed = False
        self.depth += 1
        try:
            yield True
        except Exception:
            self.failed = True
            raise
        finally:
            self.depth -= 1
            if outer:
                step = self.delta(self.step_label, before, counters, records, scope)
                if self.failed:
                    for key in step['tools']:
                        if key in storages:
                            storage = storages[key]
                            for shape, geo in records[key]:
                                shape.geo = geo
                            storage.replace(removed=list(storage.get_objects()),
                                            inserted=[shape for shape, geo in records[key]])
                            self.editor.storage_dict[key] = storage
                        else:
                            self.editor.storage_dict.pop(key, None)
                    for name, changes in step['counters'].items():
                        values = getattr(self.editor, name)
                        for key, (old, new) in changes.items():
                            if old is None:
                                values.pop(key, None)
                            else:
                                values[key] = list(old)
                    self.restore_state(before)
                    if step['tools'] or step['counters'] or before['aliases'] != step['after']['aliases'] \
                            or before['selection'] != step['after']['selection']:
                        self.refresh()
                else:
                    if step['tools'] or step['counters'] or before['aliases'] != step['after']['aliases']:
                        self.editor.is_modified = True
                        self.revision += 1
                        step['after']['modified'] = True
                        self.undo_stack.append(step)
                        self.redo_stack.clear()
                        self.enforce_limits()
                    else:
                        self.editor.is_modified = before['modified']
                self.notify()

    def delta(self, label, before, counters, records, scope=None):
        tools = {}
        editor = self.editor
        for key in (set(records) | set(editor.storage_dict) if scope is None else scope):
            old = records.get(key, ())
            new = tuple((shape, shape.geo) for shape in editor.storage_dict[key].get_objects()) \
                if key in editor.storage_dict else ()
            old_ids, new_ids = {id(shape) for shape, geo in old}, {id(shape) for shape, geo in new}
            reordered = [id(shape) for shape, geo in old if id(shape) in new_ids] != \
                [id(shape) for shape, geo in new if id(shape) in old_ids]
            removed = [(index, shape, geo) for index, (shape, geo) in enumerate(old)
                       if reordered or id(shape) not in new_ids]
            inserted = [(index, shape, geo) for index, (shape, geo) in enumerate(new)
                        if reordered or id(shape) not in old_ids]
            old_geos = {id(shape): geo for shape, geo in old}
            changed = [(shape, old_geos[id(shape)], geo) for shape, geo in new
                       if id(shape) in old_geos and old_geos[id(shape)] is not geo]
            if removed or inserted or changed or (key in records) != (key in editor.storage_dict):
                tools[key] = (key in records, key in editor.storage_dict, removed, inserted, changed)
        counter_delta = {}
        for name, values in self.counters(scope).items():
            for key in set(counters[name]) | set(values):
                old, new = counters[name].get(key), values.get(key)
                if old != new:
                    counter_delta.setdefault(name, {})[key] = (old, new)
        return {'label': label, 'tools': tools, 'counters': counter_delta,
                'before': before, 'after': self.state()}

    def restore_state(self, state):
        editor = self.editor
        editor.selected = list(state['selection'])
        editor.last_tool_selected = state['last']
        editor.is_modified = state['modified']
        editor.olddia_newdia = dict(state['aliases'])
        editor.tool2tooldia = dict(state['tools'])
        ordered = {key: editor.storage_dict[key] for key in state['order'] if key in editor.storage_dict}
        ordered.update(editor.storage_dict)
        editor.storage_dict.clear()
        editor.storage_dict.update(ordered)
        dia = editor.tool2tooldia.get(editor.last_tool_selected)
        editor.current_storage = editor.storage_dict.get(dia)

    def refresh(self):
        self.editor.build_ui()
        self.editor.replot()

    def replay(self, redo=False):
        if not self.ready() or self.depth or self.suspended or self.pending is not None:
            return False
        self.enforce_limits()
        source, target = (self.redo_stack, self.undo_stack) if redo else (self.undo_stack, self.redo_stack)
        if not source:
            return False
        step = source[-1]
        editor = self.editor
        self.replaying = True
        try:
            if editor.active_tool is not None and hasattr(editor.active_tool, 'clean_up'):
                editor.active_tool.clean_up()
            editor.utility.clear()
            editor.tool_shape.clear(update=True)
            editor.in_action = False
            for key, (old_exists, new_exists, removed, inserted, changed) in step['tools'].items():
                if not (new_exists if redo else old_exists):
                    editor.storage_dict.pop(key, None)
                    continue
                if key not in editor.storage_dict:
                    editor.storage_dict[key] = editor.make_storage()
                storage = editor.storage_dict[key]
                shapes = list(storage.get_objects())
                discard, restore = (removed, inserted) if redo else (inserted, removed)
                discard_ids = {id(shape) for index, shape, geo in discard}
                shapes = [shape for shape in shapes if id(shape) not in discard_ids]
                for index, shape, geo in restore:
                    shape.geo = geo
                    shapes.insert(index, shape)
                for shape, old, new in changed:
                    shape.geo = new if redo else old
                storage.replace(removed=list(storage.get_objects()), inserted=shapes)
            for name, changes in step['counters'].items():
                values = getattr(editor, name)
                for key, (old, new) in changes.items():
                    value = new if redo else old
                    if value is None:
                        values.pop(key, None)
                    else:
                        values[key] = list(value)
            self.restore_state(step['after'] if redo else step['before'])
            editor.select_tool('drill_select')
            target.append(source.pop())
            self.revision += 1
        finally:
            self.replaying = False
        self.refresh()
        self.notify()
        return True

    def retained_shapes(self):
        shapes = set()
        for step in self.undo_stack + self.redo_stack:
            for old_exists, new_exists, removed, inserted, changed in step['tools'].values():
                shapes.update(shape for index, shape, geo in removed + inserted)
                shapes.update(shape for shape, old, new in changed)
        return shapes

    def enforce_limits(self):
        max_steps, max_bytes = HistoryManager(self.editor.app, None).limits()

        def size():
            geos = []
            for step in self.undo_stack + self.redo_stack:
                for old_exists, new_exists, removed, inserted, changed in step['tools'].values():
                    geos.extend(geo for index, shape, geo in removed + inserted)
                    geos.extend(geo for shape, old, new in changed for geo in (old, new))
                geos.append(step['counters'])
            return state_size(geos)

        while len(self.undo_stack) + len(self.redo_stack) > max_steps or \
                (len(self.undo_stack) + len(self.redo_stack) > 1 and size() > max_bytes):
            if self.undo_stack:
                self.undo_stack.pop(0)
                self.baseline_evicted = True
            else:
                self.redo_stack.pop(0)
