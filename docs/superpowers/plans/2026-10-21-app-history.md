# App Undo / Redo History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One Undo / Redo history for each project, outside the editors, that tools can record into with 1 line.

**Architecture:** A new module `appHandlers/appHistory.py` holds the step types and `HistoryManager`. Each `ProjectContext` owns a `HistoryManager`; `app.history` points to the one of the active project. Steps find objects by a stable `history_uid`, so a deleted and rebuilt object keeps its identity. The Edit menu, a toolbar and Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y drive it.

**Tech Stack:** Python 3.11+, PyQt6, Shapely 2, numpy, unittest/pytest.

**Spec:** `docs/superpowers/specs/2026-10-21-app-history-design.md`

**Rules for every task:**
- Run Python only as `& .\.venv\Scripts\python.exe ...` from PowerShell. Git Bash cannot start the .venv Python.
- Another session can edit the repo at the same time. Edit only the lines that the task names. Never revert, stash, reset or reformat other code. Never touch a git ref or worktree that you did not make.
- No mixin classes. No `Co-Authored-By` lines. Do not commit unless the task says so; the lead commits.
- Keep the code style of the file you edit (comment density, `_()` for user strings, `self.app.inform.emit('[WARNING_NOTCL] %s' % ...)`).

---

## File map

| File | Change |
|---|---|
| `appHandlers/appHistory.py` | **new**: `HistoryError`, steps, `HistoryManager`, `object_state`, `state_size`, `invert_matrix`, `apply_matrix_to_object` |
| `tests/test_app_history.py` | **new**: manager tests with fake steps (Task 1), real-object tests (Task 3) |
| `appObjects/AppObjectTemplate.py` | `history_uid` in `FlatCAMObj.__init__`; keep it in `from_dict` |
| `appObjects/ProjectContext.py` | `self.history = None` |
| `appHandlers/appProjects.py` | create / swap `app.history` in `__init__` and `_load` |
| `appMain.py` | `history_changed` signal; `self.history` attribute |
| `appObjects/AppObject.py` | `new_object(..., record_history=True)`; record a `CreateStep` in `on_object_created` |
| `appHandlers/appIO.py` | `open_project` passes `record_history=False` |
| `tclCommands/TclCommand.py` | the 2 `execute_wrapper` run inside `app.history.suspended()` |
| `appGUI/MainGUI.py` | Edit menu items, toolbar actions, keys |
| `appHandlers/appObjectOps.py` | record flip / rotate / skew / origin / delete / rename |
| `appHandlers/appEdit.py` | record custom origin |
| `appObjects/AppObjectTemplate.py` | record Properties Offset / Scale / Skew |
| `appObjects/ObjectCollection.py` | record a rename in `setData` |
| `appPlugins/ToolTransform.py` | record each action as 1 group |
| `appPlugins/ToolAlignObjects/Align.py`, `AlignUI.py` | use the app history; remove the own stacks and buttons; import `apply_matrix_to_object` from `appHistory` |
| `appMain.py` (`on_editing_finished`) | `history.forget(uid)` after an editor save |
| `defaults.py`, preferences UI | `global_history_steps`, `global_history_memory_mb` |

---

### Task 1: The history module and its manager tests

**Files:**
- Create: `appHandlers/appHistory.py`
- Create: `tests/test_app_history.py`

- [ ] **Step 1: Write the failing manager tests**

`tests/test_app_history.py`:

```python
"""Tests of the app Undo / Redo history (appHandlers/appHistory.py)."""

import os
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from appHandlers.appHistory import HistoryError, HistoryManager, HistoryStep, invert_matrix


class FakeStep(HistoryStep):
    def __init__(self, label, log, size=0, uids=(), fail=False):
        self.label = label
        self.size = size
        self._uids = set(uids)
        self.log = log
        self.fail = fail

    def uids(self):
        return self._uids

    def undo(self, history):
        if self.fail:
            raise HistoryError('gone')
        self.log.append(('undo', self.label))

    def redo(self, history):
        self.log.append(('redo', self.label))


def fake_app(**options):
    app = SimpleNamespace(headless=False, call_source='app', inform=Mock(), history_changed=Mock(), log=Mock(),
                          options=dict(options), projects=SimpleNamespace(is_busy=lambda: False))
    return app


def manager(**options):
    app = fake_app(**options)
    history = HistoryManager(app, collection=SimpleNamespace(get_list=lambda: []))
    app.history = history
    return history, app


class TestManager(unittest.TestCase):

    def test_undo_redo_order_and_redo_cleared(self):
        h, _app = manager()
        log = []
        for name in 'abc':
            h.push(FakeStep(name, log))
        self.assertTrue(h.undo())
        self.assertTrue(h.undo())
        self.assertTrue(h.redo())
        self.assertEqual(log, [('undo', 'c'), ('undo', 'b'), ('redo', 'b')])
        self.assertEqual((h.undo_label(), h.redo_label()), ('b', 'c'))
        h.push(FakeStep('d', log))
        self.assertFalse(h.can_redo())
        self.assertFalse(h.redo())

    def test_count_limit(self):
        h, _app = manager(global_history_steps=3)
        log = []
        for i in range(10):
            h.push(FakeStep(str(i), log))
        self.assertEqual([s.label for s in h.undo_stack], ['7', '8', '9'])

    def test_memory_limit(self):
        h, _app = manager(global_history_memory_mb=1)
        log = []
        for i in range(5):
            h.push(FakeStep(str(i), log, size=400 * 1024))
        # 1 MB holds 2 steps of 400 KB
        self.assertEqual([s.label for s in h.undo_stack], ['3', '4'])
        # a single step bigger than the limit is kept, so the last action can always be undone
        h.push(FakeStep('big', log, size=5 * 1024 * 1024))
        self.assertEqual([s.label for s in h.undo_stack], ['big'])

    def test_group(self):
        h, _app = manager()
        log = []
        with h.group('all'):
            h.push(FakeStep('a', log))
            with h.group('inner'):
                h.push(FakeStep('b', log))
        self.assertEqual(len(h.undo_stack), 1)
        self.assertEqual(h.undo_label(), 'all')
        h.undo()
        self.assertEqual(log, [('undo', 'b'), ('undo', 'a')])
        h.redo()
        self.assertEqual(log[2:], [('redo', 'a'), ('redo', 'b')])

    def test_empty_group_pushes_nothing(self):
        h, _app = manager()
        with h.group('nothing'):
            pass
        self.assertFalse(h.can_undo())

    def test_suspended_and_headless(self):
        h, app = manager()
        log = []
        with h.suspended():
            h.push(FakeStep('a', log))
        self.assertFalse(h.can_undo())
        app.headless = True
        h.push(FakeStep('b', log))
        self.assertFalse(h.can_undo())

    def test_blocked_in_editor_and_busy(self):
        h, app = manager()
        log = []
        h.push(FakeStep('a', log))
        app.call_source = 'geo_editor'
        self.assertFalse(h.undo())
        app.call_source = 'app'
        app.projects.is_busy = lambda: True
        self.assertFalse(h.undo())
        self.assertEqual(log, [])
        self.assertTrue(h.can_undo())

    def test_failing_step_is_dropped(self):
        h, app = manager()
        log = []
        h.push(FakeStep('ok', log))
        h.push(FakeStep('bad', log, fail=True))
        self.assertFalse(h.undo())
        self.assertEqual(h.undo_label(), 'ok')
        self.assertFalse(h.can_redo())
        self.assertIn('[ERROR_NOTCL]', app.inform.emit.call_args[0][0])

    def test_forget(self):
        h, _app = manager()
        log = []
        h.push(FakeStep('a', log, uids={'u1'}))
        h.push(FakeStep('b', log, uids={'u2'}))
        with h.group('g'):
            h.push(FakeStep('c', log, uids={'u1'}))
        h.forget('u1')
        self.assertEqual([s.label for s in h.undo_stack], ['b'])

    def test_changed_signal_only_for_the_active_history(self):
        h, app = manager()
        h.push(FakeStep('a', []))
        app.history_changed.emit.assert_called_with('a', '')
        app.history_changed.emit.reset_mock()
        app.history = object()
        h.push(FakeStep('b', []))
        app.history_changed.emit.assert_not_called()

    def test_push_from_threads(self):
        h, _app = manager(global_history_steps=1000)
        log = []

        def work(n):
            for i in range(50):
                h.push(FakeStep('%d-%d' % (n, i), log))

        threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(h.undo_stack), 200)

    def test_invert_matrix(self):
        m = (0.0, -2.0, 2.0, 0.0, 5.0, -3.0)
        a, b, d, e, xoff, yoff = invert_matrix(m)
        # m then its inverse on the point (1, 1)
        x, y = 0.0 * 1 - 2.0 * 1 + 5.0, 2.0 * 1 + 0.0 * 1 - 3.0
        self.assertAlmostEqual(a * x + b * y + xoff, 1.0)
        self.assertAlmostEqual(d * x + e * y + yoff, 1.0)
        with self.assertRaises(HistoryError):
            invert_matrix((1.0, 2.0, 2.0, 4.0, 0.0, 0.0))


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run the tests; they must fail**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_app_history.py -q`
Expected: ERROR at collection, `ModuleNotFoundError: No module named 'appHandlers.appHistory'`.

- [ ] **Step 3: Write `appHandlers/appHistory.py`**

```python
# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 10/21/2026                                         #
# MIT Licence                                              #
# ##########################################################

"""
The Undo / Redo history of a project, outside the editors.

A step does not keep object references: it keeps the history_uid of the objects, so an object that Undo rebuilds
(after a delete) is the same object for the other steps. See docs/superpowers/specs/2026-10-21-app-history-design.md.
"""

import logging
import threading
from contextlib import contextmanager

import numpy as np
import shapely
from shapely.geometry.base import BaseGeometry

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')

DEFAULT_STEPS = 100
DEFAULT_MEMORY_MB = 256
# the history records nothing in headless mode; the tests of a headless App set this True
RECORD_IN_HEADLESS = False
# bytes for 1 coordinate pair of a Shapely geometry
COORD_BYTES = 16


class HistoryError(Exception):
    """A step can not run (for example, its object does not exist anymore). str(e) is a user message."""


# ##################################################################################################################
# Helpers
# ##################################################################################################################

def invert_matrix(matrix):
    """The inverse of the shapely affine 6-tuple (a, b, d, e, xoff, yoff)."""
    a, b, d, e, xoff, yoff = matrix
    det = a * e - b * d
    if abs(det) <= 1e-12:
        raise HistoryError(_("The transformation can not be undone."))
    ia, ib, id_, ie = e / det, -b / det, -d / det, a / det
    return ia, ib, id_, ie, -(ia * xoff + ib * yoff), -(id_ * xoff + ie * yoff)


def is_rigid(matrix):
    a, b, d, e = matrix[:4]
    return abs(a * a + d * d - 1.0) <= 1e-9 and abs(b * b + e * e - 1.0) <= 1e-9 and abs(a * b + d * e) <= 1e-9


def apply_matrix_to_object(obj, matrix):
    """
    Apply ONE affine matrix (a, b, d, e, xoff, yoff) to the geometry of a Gerber, Excellon or Geometry object,
    through the vectorized paths of the transforms. Updates the bounds in obj_options.
    """
    from appParsers.ParseExcellon import Excellon
    from appParsers.ParseGerber import Gerber
    from camlib import Geometry

    kind = obj.kind.lower()
    if kind == 'gerber':
        Gerber._affine_all(obj, matrix)
        obj._after_transform()
    elif kind == 'excellon':
        rigid = is_rigid(matrix)
        # a rigid matrix maps the hole shapes too (as offset does); scale and skew keep the tool diameters
        Excellon._transform_tools(obj, matrix, transform_solid=rigid)
        if not rigid:
            obj.create_geometry()
    elif kind == 'geometry':
        Geometry._affine_solid_geometry(obj, matrix, any_iterable=True)
    else:
        raise HistoryError('%s: %s' % (_("Object type not supported"), obj.kind))

    xmin, ymin, xmax, ymax = obj.bounds()
    obj.obj_options['xmin'] = xmin
    obj.obj_options['ymin'] = ymin
    obj.obj_options['xmax'] = xmax
    obj.obj_options['ymax'] = ymax


def supports_matrix(obj):
    return str(getattr(obj, 'kind', '')).lower() in ('gerber', 'excellon', 'geometry')


def object_state(obj):
    """
    The state of an object as project save makes it (the ser_attrs), but the dicts and lists are copied and the
    Shapely geometries are shared (they are immutable): a later change of the object does not change the state.
    """
    from camlib import deepcopy_keep_geometry

    state = deepcopy_keep_geometry({attr: getattr(obj, attr) for attr in obj.ser_attrs if hasattr(obj, attr)})
    state['kind'] = obj.kind
    state['history_uid'] = obj.history_uid
    return state


def _geometries(item, out):
    stack = [item]
    seen = set()
    while stack:
        cur = stack.pop()
        if isinstance(cur, BaseGeometry):
            out.append(cur)
        elif isinstance(cur, (dict, list, tuple)) and id(cur) not in seen:
            seen.add(id(cur))
            stack.extend(cur.values() if isinstance(cur, dict) else cur)
    return out


def state_size(*states):
    """Estimated bytes that the states keep alive: the coordinates of their geometries."""
    geoms = []
    for state in states:
        _geometries(state, geoms)
    if not geoms:
        return 0
    return int(shapely.get_num_coordinates(np.asarray(geoms, dtype=object)).sum()) * COORD_BYTES


# ##################################################################################################################
# Steps
# ##################################################################################################################

class HistoryStep:
    """One undoable action. undo() / redo() raise HistoryError if they can not run."""

    label = ''
    size = 0

    def uids(self):
        return set()

    def undo(self, history):
        raise NotImplementedError

    def redo(self, history):
        raise NotImplementedError


class MatrixStep(HistoryStep):
    """An affine matrix applied to objects. Undo applies the inverse matrices in reverse order."""

    def __init__(self, label, items):
        self.label = label
        self.items = [(uid, tuple(float(v) for v in m)) for uid, m in items]

    def uids(self):
        return {uid for uid, _m in self.items}

    def _run(self, history, inverse):
        items = list(reversed(self.items)) if inverse else self.items
        objs = [history.find_or_fail(uid) for uid, _m in items]
        for obj, (_uid, matrix) in zip(objs, items):
            m = invert_matrix(matrix) if inverse else matrix
            apply_matrix_to_object(obj, m)
            history.after_change(obj, m)

    def undo(self, history):
        self._run(history, True)

    def redo(self, history):
        self._run(history, False)


class SnapshotStep(HistoryStep):
    """The state of objects before and after an action that is not affine."""

    def __init__(self, label, items):
        self.label = label
        self.items = items      # [(uid, before, after)]
        self.size = state_size(*[s for _uid, before, after in items for s in (before, after)])

    def uids(self):
        return {uid for uid, _b, _a in self.items}

    def _run(self, history, use_before):
        objs = [history.find_or_fail(uid) for uid, _b, _a in self.items]
        for obj, (_uid, before, after) in zip(objs, self.items):
            history.restore_state(obj, before if use_before else after)

    def undo(self, history):
        self._run(history, True)

    def redo(self, history):
        self._run(history, False)


class CreateStep(HistoryStep):
    """New objects. Undo deletes them and keeps their state; Redo rebuilds them with the same history_uid."""

    def __init__(self, label, uids):
        self.label = label
        self._uids = list(uids)
        self.states = {}

    def uids(self):
        return set(self._uids)

    def undo(self, history):
        objs = [history.find_or_fail(uid) for uid in self._uids]
        self.states = {obj.history_uid: object_state(obj) for obj in objs}
        self.size = state_size(*self.states.values())
        history.delete_objects(objs)

    def redo(self, history):
        for uid in self._uids:
            history.rebuild(self.states[uid])
        self.states = {}
        self.size = 0


class DeleteStep(HistoryStep):
    """Deleted objects. Undo rebuilds them with the same history_uid; Redo deletes them again."""

    def __init__(self, label, states):
        self.label = label
        self.states = list(states)
        self.size = state_size(*self.states)

    def uids(self):
        return {s['history_uid'] for s in self.states}

    def undo(self, history):
        for state in self.states:
            history.rebuild(state)

    def redo(self, history):
        history.delete_objects([history.find_or_fail(s['history_uid']) for s in self.states])


class RenameStep(HistoryStep):
    def __init__(self, label, items):
        self.label = label
        self.items = items      # [(uid, old, new)]

    def uids(self):
        return {uid for uid, _o, _n in self.items}

    def undo(self, history):
        for uid, old, _new in self.items:
            history.rename(history.find_or_fail(uid), old)

    def redo(self, history):
        for uid, _old, new in self.items:
            history.rename(history.find_or_fail(uid), new)


class GroupStep(HistoryStep):
    """More steps as 1 history entry."""

    def __init__(self, label, steps):
        self.label = label
        self.steps = list(steps)

    @property
    def size(self):
        return sum(s.size for s in self.steps)

    def uids(self):
        out = set()
        for s in self.steps:
            out |= s.uids()
        return out

    def undo(self, history):
        for s in reversed(self.steps):
            s.undo(history)

    def redo(self, history):
        for s in self.steps:
            s.redo(history)


# ##################################################################################################################
# Manager
# ##################################################################################################################

class HistoryManager:
    """
    The Undo / Redo stacks of 1 project. push() is thread safe; undo() / redo() run on the GUI thread.
    app.history is the manager of the active project; only that one emits app.history_changed.
    """

    def __init__(self, app, collection):
        self.app = app
        self.collection = collection
        self.undo_stack = []
        self.redo_stack = []
        self._lock = threading.RLock()
        self._suspend = 0
        # [label, steps, depth] while a group() is open
        self._group = None

    # ---------------------------------------------------------------------------------------------------------
    # Limits and state
    # ---------------------------------------------------------------------------------------------------------
    def _option(self, key, default):
        try:
            return int(self.app.options.get(key, default))
        except (AttributeError, TypeError, ValueError):
            return default

    def limits(self):
        steps = max(1, self._option('global_history_steps', DEFAULT_STEPS))
        mem = max(1, self._option('global_history_memory_mb', DEFAULT_MEMORY_MB)) * 1024 * 1024
        return steps, mem

    def _headless(self):
        return getattr(self.app, 'headless', False) and not RECORD_IN_HEADLESS

    def is_recording(self):
        return not self._headless() and self._suspend == 0

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def undo_label(self):
        return self.undo_stack[-1].label if self.undo_stack else ''

    def redo_label(self):
        return self.redo_stack[-1].label if self.redo_stack else ''

    def total_size(self):
        return sum(s.size for s in self.undo_stack) + sum(s.size for s in self.redo_stack)

    def _enforce(self):
        max_steps, max_bytes = self.limits()
        del self.undo_stack[:-max_steps]
        while self.redo_stack and self.total_size() > max_bytes:
            # the redo step that is farthest away goes first
            del self.redo_stack[0]
        while len(self.undo_stack) > 1 and self.total_size() > max_bytes:
            del self.undo_stack[0]

    def notify(self):
        if getattr(self.app, 'history', None) is not self:
            return
        try:
            self.app.history_changed.emit(self.undo_label(), self.redo_label())
        except Exception as e:
            log.debug("HistoryManager.notify() --> %s" % str(e))

    # ---------------------------------------------------------------------------------------------------------
    # Record
    # ---------------------------------------------------------------------------------------------------------
    def push(self, step):
        if step is None or not self.is_recording():
            return
        with self._lock:
            if self._group is not None:
                self._group[1].append(step)
                return
            self.undo_stack.append(step)
            self.redo_stack.clear()
            self._enforce()
        self.notify()

    @contextmanager
    def group(self, label):
        """The steps pushed inside become 1 GroupStep. Nested groups join the outer one."""
        with self._lock:
            outer = self._group is None
            if outer:
                self._group = [label, [], 0]
            self._group[2] += 1
        try:
            yield
        finally:
            with self._lock:
                self._group[2] -= 1
                done = self._group if self._group[2] == 0 else None
                if done is not None:
                    self._group = None
            if done is not None and done[1]:
                self.push(done[1][0] if len(done[1]) == 1 and done[1][0].label == done[0]
                          else GroupStep(done[0], done[1]))

    @contextmanager
    def suspended(self):
        """push() does nothing inside (project load, the rebuild of an object, a Tcl command)."""
        with self._lock:
            self._suspend += 1
        try:
            yield
        finally:
            with self._lock:
                self._suspend -= 1

    def record_matrix(self, label, pairs):
        """pairs: [(obj, matrix)] after the matrices were applied. Objects without a matrix path are skipped."""
        items = [(obj.history_uid, m) for obj, m in pairs if supports_matrix(obj)]
        if items:
            self.push(MatrixStep(label, items))

    @contextmanager
    def snapshot(self, label, objects):
        """The state of the objects before the body and after it, as 1 SnapshotStep."""
        if not self.is_recording():
            yield
            return
        objects = list(objects)
        before = [object_state(o) for o in objects]
        yield
        items = [(o.history_uid, b, object_state(o)) for o, b in zip(objects, before)]
        if items:
            self.push(SnapshotStep(label, items))

    def record_create(self, label, objects):
        uids = [o.history_uid for o in objects]
        if uids:
            self.push(CreateStep(label, uids))

    def record_delete(self, label, objects):
        """Call it BEFORE the objects are deleted."""
        if not self.is_recording():
            return
        states = [object_state(o) for o in objects]
        if states:
            self.push(DeleteStep(label, states))

    def record_rename(self, obj, old, new):
        if old != new:
            self.push(RenameStep('%s: %s' % (_("Rename"), new), [(obj.history_uid, old, new)]))

    # ---------------------------------------------------------------------------------------------------------
    # Undo / Redo
    # ---------------------------------------------------------------------------------------------------------
    def blocked_reason(self):
        if self._headless():
            return _("Undo / Redo is not available in headless mode.")
        if getattr(self.app, 'call_source', 'app') != 'app':
            return _("Close the editor first. The editor has its own Undo / Redo.")
        projects = getattr(self.app, 'projects', None)
        if projects is not None and projects.is_busy():
            return _("Wait for the running task to finish.")
        return None

    def undo(self):
        return self._run(self.undo_stack, self.redo_stack, True)

    def redo(self):
        return self._run(self.redo_stack, self.undo_stack, False)

    def _run(self, source, target, undo):
        reason = self.blocked_reason()
        if reason:
            self.app.inform.emit('[WARNING_NOTCL] %s' % reason)
            return False
        with self._lock:
            if not source:
                return False
            step = source.pop()

        name = _("Undo") if undo else _("Redo")
        try:
            with self.suspended():
                step.undo(self) if undo else step.redo(self)
        except HistoryError as e:
            self.app.inform.emit('[ERROR_NOTCL] %s %s: %s' % (name, step.label, str(e)))
            self.notify()
            return False
        except Exception as e:
            log.error("HistoryManager._run() %s --> %s" % (step.label, str(e)))
            self.app.inform.emit('[ERROR_NOTCL] %s %s: %s' % (name, step.label, str(e)))
            self.notify()
            return False

        with self._lock:
            target.append(step)
            self._enforce()
        self.notify()
        self.app.inform.emit('[success] %s: %s' % (name, step.label))
        return True

    def clear(self):
        with self._lock:
            self.undo_stack.clear()
            self.redo_stack.clear()
        self.notify()

    def forget(self, uid):
        """Drop every step that touches the object (its steps can not give a correct result anymore)."""
        with self._lock:
            self.undo_stack[:] = [s for s in self.undo_stack if uid not in s.uids()]
            self.redo_stack[:] = [s for s in self.redo_stack if uid not in s.uids()]
        self.notify()

    # ---------------------------------------------------------------------------------------------------------
    # Object access for the steps (the GUI thread)
    # ---------------------------------------------------------------------------------------------------------
    def find(self, uid):
        for obj in self.collection.get_list():
            if getattr(obj, 'history_uid', None) == uid:
                return obj
        return None

    def find_or_fail(self, uid):
        obj = self.find(uid)
        if obj is None:
            raise HistoryError(_("The object of this step does not exist anymore."))
        return obj

    def after_change(self, obj, matrix=None):
        """Bounds, the Properties offset, object_changed and the plot after a geometry change."""
        try:
            obj.set_offset_values(bounds=obj.bounds())
        except Exception as e:
            log.debug("HistoryManager.after_change() set_offset_values --> %s" % str(e))
        try:
            self.app.app_obj.object_changed.emit(obj)
        except Exception as e:
            log.debug("HistoryManager.after_change() object_changed --> %s" % str(e))
        if matrix is not None and hasattr(obj, 'plot_transformed'):
            obj.plot_transformed(matrix)
        else:
            obj.plot()

    def restore_state(self, obj, state):
        from camlib import deepcopy_keep_geometry

        uid = obj.history_uid
        obj.from_dict(deepcopy_keep_geometry(state))
        obj.history_uid = uid
        try:
            xmin, ymin, xmax, ymax = obj.bounds()
            obj.obj_options['xmin'], obj.obj_options['ymin'] = xmin, ymin
            obj.obj_options['xmax'], obj.obj_options['ymax'] = xmax, ymax
        except Exception as e:
            log.debug("HistoryManager.restore_state() bounds --> %s" % str(e))
        self.after_change(obj, None)

    def delete_objects(self, objects):
        """Delete without a confirmation and without a DeleteStep (see AppObjectOps.delete_objects_now)."""
        self.app.object_ops.delete_objects_now(objects)

    def rebuild(self, state):
        """Make the object again from its state, with the same history_uid (the same path as project open)."""
        from camlib import deepcopy_keep_geometry
        from appCommon.Common import LoudDict

        def obj_init(new_obj, app_obj):
            new_obj.from_dict(deepcopy_keep_geometry(state))
            options = LoudDict()
            options.update(new_obj.obj_options)
            options.set_change_callback(new_obj.on_options_change)
            new_obj.obj_options = options
            new_obj.history_uid = state['history_uid']

        name = state.get('obj_options', {}).get('name', state['kind'])
        ret = self.app.app_obj.new_object(state['kind'], name, obj_init, plot=True, autoselected=False,
                                          record_history=False)
        if ret == 'fail' or self.find(state['history_uid']) is None:
            raise HistoryError(_("The object could not be made again."))

    def rename(self, obj, name):
        self.collection.rename_object(obj, name)
```

- [ ] **Step 4: Check 2 names that the module uses**

The class above calls 2 app functions that Task 3 adds: `app.object_ops.delete_objects_now(objects)` and `collection.rename_object(obj, name)`. The manager tests do not call them.

Check the attribute name of the `AppObjectOps` instance on the App: `& .\.venv\Scripts\python.exe -c "import re;print(set(re.findall(r'self\.(\w+) = AppObjectOps', open('appMain.py',encoding='utf-8').read())))"`. If it is not `object_ops`, use the real name here and in Task 3.

Check the import path of `LoudDict`: `& .\.venv\Scripts\python.exe -c "import re;print(re.findall(r'^from .* import .*LoudDict.*$', open('appHandlers/appIO.py',encoding='utf-8').read(), re.M))"`. Use the same import line in `rebuild`.

- [ ] **Step 5: Run the tests; they must pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_app_history.py -q`
Expected: `12 passed`.

- [ ] **Step 6: Lint**

Run: `& .\.venv\Scripts\python.exe -m pyflakes appHandlers/appHistory.py tests/test_app_history.py`
Expected: no output.

---

### Task 2: Object identity and the history of each project

**Files:**
- Modify: `appObjects/AppObjectTemplate.py` (`FlatCAMObj.__init__`, `from_dict` at line ~250)
- Modify: `appObjects/ProjectContext.py` (`ProjectContext.__init__`)
- Modify: `appHandlers/appProjects.py` (`ProjectManager.__init__`, `_load`)
- Modify: `appMain.py` (the App signals; `self.history`)
- Test: `tests/test_app_history.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_app_history.py`, before `if __name__`)

```python
class TestIdentityAndProjects(unittest.TestCase):

    def test_uid_unique_and_kept_by_from_dict(self):
        from test_unify_characterization import make_app, make_gerber
        app = make_app()
        g1, g2 = make_gerber(app, name='a'), make_gerber(app, name='b')
        self.assertNotEqual(g1.history_uid, g2.history_uid)
        d = g1.to_dict()
        d['history_uid'] = g1.history_uid
        g2.from_dict(d)
        self.assertEqual(g2.history_uid, g1.history_uid)

    def test_each_project_has_its_history(self):
        from appHandlers.appProjects import ProjectManager
        from appObjects.ProjectContext import ProjectContext
        ctx1 = ProjectContext('p1', SimpleNamespace(get_list=lambda: [], view=None))
        ctx2 = ProjectContext('p2', SimpleNamespace(get_list=lambda: [], view=None))
        app = fake_app()
        pm = SimpleNamespace(app=app)
        for ctx in (ctx1, ctx2):
            ProjectManager._ensure_history(pm, ctx)
        self.assertIsNot(ctx1.history, ctx2.history)
        self.assertIs(ctx1.history.collection, ctx1.collection)
```

`from_dict` must also keep the uid when `history_uid` is in the dict, and keep the old one when it is not (an old project): the first test covers the first case.

- [ ] **Step 2: Run; must fail** (`AttributeError: ... history_uid` and `_ensure_history`).

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_app_history.py -q -k "Identity"`

- [ ] **Step 3: Implement**

In `appObjects/AppObjectTemplate.py`, `FlatCAMObj.__init__`, next to the other plain attributes (for example after `self.treeWidget = None`):

```python
        # a stable id for the Undo / Redo history: an object that Undo makes again (after a delete) keeps it
        self.history_uid = uuid.uuid4().hex
```

Add `import uuid` to the imports of the file. In `FlatCAMObj.from_dict(self, d)`, at the start of the method body:

```python
        # the history id of a rebuilt object (an old project has none: the object keeps its new id)
        if d.get('history_uid'):
            self.history_uid = d['history_uid']
```

`to_dict()` is not changed: `object_state()` in `appHistory` adds the uid, and the project file stays as it is.

In `appObjects/ProjectContext.py`, `ProjectContext.__init__`, at the end:

```python
        # the Undo / Redo history (appHandlers.appHistory.HistoryManager); made by ProjectManager
        self.history = None
```

In `appHandlers/appProjects.py`, add the method to `ProjectManager` (after `_make_collection`):

```python
    def _ensure_history(self, ctx):
        """Every project has its own Undo / Redo history."""
        if ctx.history is None:
            from appHandlers.appHistory import HistoryManager
            ctx.history = HistoryManager(self.app, ctx.collection)
        return ctx.history
```

At the end of `ProjectManager.__init__`:

```python
        app.history = self._ensure_history(first)
```

At the end of `_load(self, ctx)`:

```python
        self.app.history = self._ensure_history(ctx)
        self.app.history.notify()
```

In `appMain.py`, next to the other `QtCore.pyqtSignal` class attributes of `App`:

```python
    # the Undo / Redo labels of the active project changed: (undo label, redo label), '' for nothing
    history_changed = QtCore.pyqtSignal(str, str)
```

and next to `self.collection = None` (line ~495):

```python
        # the Undo / Redo history of the active project (set by ProjectManager)
        self.history = None
```

- [ ] **Step 4: Run; must pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_app_history.py tests/test_tcl_projects.py tests/test_unify_stage0c.py -q -m "not slow"`
Expected: all pass.

---

### Task 3: Real objects: delete, rebuild, rename, create

**Files:**
- Modify: `appHandlers/appObjectOps.py` (`on_delete` at line ~849; new `delete_objects_now`)
- Modify: `appObjects/ObjectCollection.py` (`setData` at line ~568; new `rename_object`)
- Modify: `appObjects/AppObject.py` (`new_object` at line 226, `on_object_created` at line 406)
- Modify: `appHandlers/appIO.py` (`open_project` at line ~3058, the `new_object` call)
- Test: `tests/test_app_history_app.py` (new, a real headless App)

- [ ] **Step 1: Split the object cleanup out of `on_delete`**

In `AppObjectOps.on_delete`, the code under `if response == bt_ok:` cleans up each selected object (mark shapes, CNCJob annotations, tool shapes) and then deletes it. Move that part, without a change of behaviour, into a new method of the same class that takes the objects as a parameter:

```python
    def delete_objects_now(self, objects):
        """
        Delete the objects without a confirmation and without a history step: the cleanup of the visuals of each
        object, then the removal from the collection. on_delete() and the Undo / Redo history use it.
        """
        # <the moved cleanup + deletion code, with `selected` replaced by `list(objects)`>
```

Then `on_delete` does, in place of the moved code:

```python
                    selected = list(self.app.collection.get_selected())
                    self.app.history.record_delete(
                        '%s: %s' % (_("Delete"), ", ".join(o.obj_options['name'] for o in selected)), selected)
                    self.delete_objects_now(selected)
```

The moved code must select the objects to delete from the parameter, not from the selection of the collection. If the old code calls `collection.delete_active()` in a loop that depends on the selection, use `collection.delete_objects(objects)` (line ~807) for the removal from the tree.

- [ ] **Step 2: Rename through 1 function**

In `appObjects/ObjectCollection.py`, add:

```python
    def rename_object(self, obj, new_name):
        """Rename as the Project tree does (the keyword list, the status signal), without a history step."""
        old_name = obj.obj_options['name']
        if old_name == new_name or new_name == '':
            return
        obj.obj_options['name'] = new_name
        self.app.object_status_changed.emit(obj, 'rename', old_name)
        try:
            self.app.regFK.remove_keyword(old_name, update=False)
            self.app.regFK.prepend_keyword(new_name)
        except Exception as e:
            self.app.log.error("rename_object() --> could not update the auto-completer: %s" % str(e))
        self.update_view()
```

Check that `self.update_view()` exists in `ObjectCollection`; if the class refreshes the tree another way in `setData`, use that call. In `setData`, where the name changes (line ~576), add the history record before the rename:

```python
                    self.app.history.record_rename(obj, old_name, new_name)
```

In `AppObjectOps.on_rename_object` (line 797), replace `named_obj.obj_options['name'] = text` with:

```python
                self.app.history.record_rename(named_obj, named_obj.obj_options['name'], text)
                self.app.collection.rename_object(named_obj, text)
```

- [ ] **Step 3: Record object creation**

In `AppObject.new_object`, add the keyword parameter `record_history=True` at the end of the signature and document it:

```python
        :param record_history:  record a Create step in the Undo / Redo history (False: project open, the rebuild
                                of an object by Undo / Redo, Tcl commands)
```

Before the `object_created.emit(...)` calls (lines ~391 and ~399), mark the object; the suspension is read here because the history can be suspended only while new_object runs:

```python
            history = getattr(self.app, 'history', None)
            obj._record_history = bool(record_history and history is not None and history.is_recording())
```

In `on_object_created`, after `self.app.collection.append(obj)` (line 427):

```python
        if getattr(obj, '_record_history', False):
            self.app.history.record_create('%s: %s' % (_("New"), obj.obj_options['name']), [obj])
```

In `appHandlers/appIO.py` `open_project`, the `new_object(...)` call that uses the `obj_init` at line ~3058 gets `record_history=False`. Also wrap the whole project load in no history: at the start of `worker_task()` the code runs in a worker; the flag on each `new_object` call is enough. After the load ends (the `finished` callback), call `self.app.history.clear()`.

- [ ] **Step 4: Write the real-object tests**

`tests/test_app_history_app.py`:

```python
"""App Undo / Redo history on real objects in a headless App: matrix, snapshot, delete + rebuild, create, rename."""

import os
import sys

import numpy as np
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

FIX = os.path.join(os.path.dirname(__file__), 'fixtures', 'unify')

pytestmark = pytest.mark.slow


@pytest.fixture(scope='module')
def fc():
    from PyQt6 import QtWidgets
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    from appMain import App
    import appHandlers.appHistory as appHistory
    app = App(qapp=qapp, headless=True)
    # the history records nothing in headless mode; these tests need it
    appHistory.RECORD_IN_HEADLESS = True
    yield app
    appHistory.RECORD_IN_HEADLESS = False


def _load(fc, kind, filename, name):
    def init(obj, _app):
        obj.parse_file(os.path.join(FIX, filename))
        if kind == 'excellon':
            obj.create_geometry()
    return fc.app_obj.new_object(kind, name, init, plot=False)


def _bounds(obj):
    return np.array(obj.bounds())
```

Then the tests (stub the plot of the objects as the headless canvas can not draw: `monkeypatch.setattr(FlatCAMObj, 'plot', lambda *a, **k: None)` and the same for `plot_transformed` and `ExcellonObject.plot_transformed`):

```python
def test_matrix_undo_redo(fc, no_plot):
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_matrix')
    from appHandlers.appHistory import apply_matrix_to_object
    b0 = _bounds(grb)
    m = (0.0, -1.0, 1.0, 0.0, 10.0, 0.0)
    apply_matrix_to_object(grb, m)
    fc.history.record_matrix('rot', [(grb, m)])
    b1 = _bounds(grb)
    assert fc.history.undo() and np.allclose(_bounds(grb), b0)
    assert fc.history.redo() and np.allclose(_bounds(grb), b1)


def test_delete_undo_rebuilds_same_uid_and_later_steps_work(fc, no_plot):
    exc = _load(fc, 'excellon', 'unify_mixed.drl', 'e_del')
    uid, b0 = exc.history_uid, _bounds(exc)
    from appHandlers.appHistory import apply_matrix_to_object
    m = (1.0, 0.0, 0.0, 1.0, 5.0, 5.0)
    apply_matrix_to_object(exc, m)
    fc.history.record_matrix('move', [(exc, m)])
    fc.history.record_delete('del', [exc])
    fc.object_ops.delete_objects_now([exc])
    assert fc.history.find(uid) is None
    assert fc.history.undo()                    # rebuild
    rebuilt = fc.history.find(uid)
    assert rebuilt is not None and rebuilt is not exc
    assert fc.history.undo()                    # the move, on the rebuilt object
    assert np.allclose(_bounds(rebuilt), b0)


def test_create_undo_redo(fc, no_plot):
    geo_count = len(fc.collection.get_list())
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_create')
    assert fc.history.undo_label().endswith('g_create')
    uid = grb.history_uid
    assert fc.history.undo() and fc.history.find(uid) is None
    assert len(fc.collection.get_list()) == geo_count
    assert fc.history.redo() and fc.history.find(uid) is not None


def test_snapshot_buffer(fc, no_plot):
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_snap')
    area0 = grb.solid_geometry.area if hasattr(grb.solid_geometry, 'area') else None
    b0 = _bounds(grb)
    with fc.history.snapshot('buffer', [grb]):
        grb.buffer(0.5, join=1, factor=None)
    assert not np.allclose(_bounds(grb), b0)
    assert fc.history.undo() and np.allclose(_bounds(grb), b0)


def test_rename(fc, no_plot):
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_old')
    fc.history.record_rename(grb, 'g_old', 'g_new')
    fc.collection.rename_object(grb, 'g_new')
    assert fc.history.undo() and grb.obj_options['name'] == 'g_old'
    assert fc.history.redo() and grb.obj_options['name'] == 'g_new'
```

with the fixture:

```python
@pytest.fixture
def no_plot(monkeypatch):
    from appObjects.AppObjectTemplate import FlatCAMObj
    from appObjects.ExcellonObject import ExcellonObject
    monkeypatch.setattr(FlatCAMObj, 'plot', lambda *a, **k: None)
    monkeypatch.setattr(FlatCAMObj, 'plot_transformed', lambda *a, **k: True)
    monkeypatch.setattr(ExcellonObject, 'plot_transformed', lambda *a, **k: True)
    for _ in range(20):
        from PyQt6 import QtWidgets
        QtWidgets.QApplication.processEvents()
```

Check the signature of `Gerber.buffer` before the snapshot test (`grep -n "def buffer" appParsers/ParseGerber.py`) and call it as the Transform plugin does in `appPlugins/ToolTransform.py`.

- [ ] **Step 5: Run; fix until all pass**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_app_history.py tests/test_app_history_app.py -q`
Expected: all pass. The App start takes a few seconds; the file is marked `slow`.

- [ ] **Step 6: Run the delete and rename tests that exist**

Run: `& .\.venv\Scripts\python.exe -m pytest tests -q -m "not slow" -k "delete or rename or project or collection"`
Expected: no new failure.

---

### Task 4: Menu, toolbar and keys

**Files:**
- Modify: `appGUI/MainGUI.py` (Edit menu at line ~413; the Edit toolbar at line ~1114; `keyPressEvent`, the `if self.app.call_source == 'app':` branch at line ~3052)
- Modify: `appMain.py` (connect the signals where the other menu actions are connected; check `appHandlers/appSignalConnector.py` first, the connections are there)
- Test: `tests/test_app_history_keys.py` (new)

- [ ] **Step 1: Menu items** — at the top of the Edit menu, before the first `addSeparator()` of `self.menuedit`:

```python
        self.menuedit_undo = self.menuedit.addAction(
            QtGui.QIcon(self.app.resource_location + '/undo16.png'),
            '%s\t%s' % (_('Undo'), _('Ctrl+Z')))
        self.menuedit_redo = self.menuedit.addAction(
            QtGui.QIcon(self.app.resource_location + '/redo16.png'),
            '%s\t%s' % (_('Redo'), _('Ctrl+Shift+Z')))
        self.menuedit_undo.setEnabled(False)
        self.menuedit_redo.setEnabled(False)
```

Check that `assets/resources/redo16.png` (and a 32 px pair for the toolbar) exist: `ls assets/resources | grep -i -E "undo|redo"`. If `redo16.png` is missing, use the undo icon mirrored with `QtGui.QTransform().scale(-1, 1)` on its pixmap.

- [ ] **Step 2: Toolbar** — in the Edit toolbar (where `self.editor_start_btn = self.toolbaredit.addAction(` is, line ~1114), add before it:

```python
        self.undo_btn = self.toolbaredit.addAction(
            QtGui.QIcon(self.app.resource_location + '/undo32.png'), _("Undo"))
        self.redo_btn = self.toolbaredit.addAction(
            QtGui.QIcon(self.app.resource_location + '/redo32.png'), _("Redo"))
        self.undo_btn.setEnabled(False)
        self.redo_btn.setEnabled(False)
        self.toolbaredit.addSeparator()
```

The toolbars are rebuilt in more than 1 place (search `self.toolbaredit.addAction(` and `editor_start_btn =`): add the 2 actions in each place.

- [ ] **Step 3: One function that updates the menu and the toolbar** — in `MainGUI`:

```python
    def on_history_changed(self, undo_label, redo_label):
        """The Edit menu items and the toolbar buttons show the next Undo / Redo step."""
        for action, label, name, keys in (
                (self.menuedit_undo, undo_label, _('Undo'), _('Ctrl+Z')),
                (self.menuedit_redo, redo_label, _('Redo'), _('Ctrl+Shift+Z'))):
            text = '%s %s' % (name, label) if label else name
            action.setText('%s\t%s' % (text, keys))
            action.setEnabled(bool(label))
        for button, label, name in ((self.undo_btn, undo_label, _('Undo')), (self.redo_btn, redo_label, _('Redo'))):
            button.setToolTip('%s %s' % (name, label) if label else name)
            button.setEnabled(bool(label))
```

Connect (in `appSignalConnector.py` or where `menueditedit.triggered` is connected):

```python
        self.app.history_changed.connect(self.app.ui.on_history_changed)
        self.app.ui.menuedit_undo.triggered.connect(lambda: self.app.history.undo())
        self.app.ui.menuedit_redo.triggered.connect(lambda: self.app.history.redo())
        self.app.ui.undo_btn.triggered.connect(lambda: self.app.history.undo())
        self.app.ui.redo_btn.triggered.connect(lambda: self.app.history.redo())
```

If the toolbar is rebuilt later (a layout change), reconnect the 2 buttons where the other toolbar buttons are reconnected (search `editor_start_btn.triggered.connect`).

While an editor is open, disable the 4 actions: where the app enters an editor (`menueditedit.setDisabled(True)` style code in `on_editing_start` / `object2editor`) and enables them again on exit, call `self.app.ui.on_history_changed('', '')` on enter and `self.app.history.notify()` on exit.

- [ ] **Step 4: Keys** — in `keyPressEvent`, inside `if self.app.call_source == 'app':`, as the FIRST block (before `# CTRL + ALT`):

```python
            ctrl = QtCore.Qt.KeyboardModifier.ControlModifier
            shift = QtCore.Qt.KeyboardModifier.ShiftModifier
            if (modifiers == ctrl and key in (QtCore.Qt.Key.Key_Z, QtCore.Qt.Key.Key_Y)) or \
                    (modifiers == ctrl | shift and key == QtCore.Qt.Key.Key_Z):
                if not self.app_focus_in_text():
                    if key == QtCore.Qt.Key.Key_Y or modifiers == ctrl | shift:
                        self.app.history.redo()
                    else:
                        self.app.history.undo()
                return
```

and the helper in `MainGUI` (the same test as the Geometry Editor branch at line ~3543, which can then call it too):

```python
    @staticmethod
    def app_focus_in_text():
        """True if the keyboard focus is in a text or number field (Ctrl+Z belongs to the field then)."""
        focus = QtWidgets.QApplication.focusWidget()
        while focus is not None:
            if isinstance(focus, (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit,
                                  QtWidgets.QAbstractSpinBox)):
                return True
            focus = focus.parentWidget()
        return False
```

`key` can be a Qt key or a str (VisPy events); the Geometry Editor branch compares both (`key == QtCore.Qt.Key.Key_Z or key == 'Z'`). Do the same here.

- [ ] **Step 5: Key test** — `tests/test_app_history_keys.py`: call the unbound `MainGUI.keyPressEvent` with a fake `self` (`MagicMock()` with `app.call_source = 'app'`, `app.history = Mock()`, `app_focus_in_text = lambda: False`) and a fake event (`key()` returns `Qt.Key.Key_Z`, `modifiers()` returns `ControlModifier`). Check the existing tests for this pattern first: `grep -rln "MainGUI.keyPressEvent" tests`. Assert:
  - Ctrl+Z → `history.undo` called once.
  - Ctrl+Shift+Z → `history.redo` called once.
  - Ctrl+Y → `history.redo` called once.
  - `app_focus_in_text = lambda: True` → neither is called.
  - `call_source = 'geo_editor'` → the app history is not called.

- [ ] **Step 6: Run**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_app_history_keys.py tests/test_geo_editor_history.py -q`
Expected: all pass.

---

### Task 5: Record the core operations

**Files:**
- Modify: `appPlugins/ToolTransform.py` (`_transform_selected` at line 355)
- Modify: `appHandlers/appObjectOps.py` (`on_flipy` 65, `on_flipx` 111, `on_rotate` 157, `on_skewx` 215, `on_skewy` 261, `on_set_origin` 307, `on_move2origin` 425)
- Modify: `appHandlers/appEdit.py` (`on_custom_origin` 645)
- Modify: `appObjects/AppObjectTemplate.py` (`on_offset_button_click` 601, `on_scale_button_click` 617, `on_skew_button_click` 648)
- Modify: `appPlugins/ToolAlignObjects/Align.py`, `AlignUI.py`
- Modify: `appMain.py` (`on_editing_finished` at line 2325)
- Test: `tests/test_app_history_app.py` (append)

The rule (spec, "Recording rules for the tools"):
- an affine change of a Gerber / Excellon / Geometry object → `app.history.record_matrix(label, [(obj, matrix)])` after the change;
- anything else (a CNCJob object, a buffer) → `with app.history.snapshot(label, [obj]):` around the change;
- 1 user action on more objects → `with app.history.group(label):` around the loop.

- [ ] **Step 1: Transform plugin** — in `_transform_selected`, wrap the `for sel_obj in obj_list:` loop in `with self.app.history.group(title):`. After `ToolTransform._after_change(self, sel_obj, matrix, set_offset)` add:

```python
                    if matrix is not None:
                        self.app.history.record_matrix(title, [(sel_obj, matrix)])
```

For the buffer action (matrix is None), the body calls `apply_fn(sel_obj)`; record it with a snapshot. Change the line `if apply_fn(sel_obj) == 'fail':` to:

```python
                    if matrix is None:
                        with self.app.history.snapshot(title, [sel_obj]):
                            result = apply_fn(sel_obj)
                    else:
                        result = apply_fn(sel_obj)
                    if result == 'fail':
```

A 'fail' result leaves the object unchanged, so a snapshot step with before == after is harmless; it is acceptable.

- [ ] **Step 2: Edit menu transforms** — each of these handlers loops over `obj_list` and calls an object method. Use the matrix functions of camlib (`affine_mirror_matrix`, `affine_rotate_matrix`, `affine_skew_matrix`, `affine_translate_matrix`, imported from `camlib`) to describe the same change, and record it. Example for `on_flipy`:

```python
                with self.app.history.group(_("Flip on Y axis")):
                    for obj in obj_list:
                        obj.mirror('X', [px, py])
                        self.app.history.record_matrix(_("Flip on Y axis"), [(obj, affine_mirror_matrix('X', (px, py)))])
                        obj.plot()
                        self.app.app_obj.object_changed.emit(obj)
```

Check the argument convention of `affine_mirror_matrix(axis, origin)` against `Geometry.mirror` in `camlib.py:2676` (`matrix = affine_mirror_matrix(axis, (px, py))`): use exactly the matrix that the object method uses. Do the same for:
  - `on_flipx` (axis 'Y'),
  - `on_rotate` (`affine_rotate_matrix(angle, (px, py))`, with the angle sign that `Geometry.rotate` uses at `camlib.py:2704`),
  - `on_skewx` / `on_skewy` (`affine_skew_matrix(ax, ay, (px, py))` as `camlib.py:2733`),
  - `on_set_origin`, `on_move2origin`, `appEdit.on_custom_origin` (`affine_translate_matrix(dx, dy)` with the offset vector each handler passes to `obj.offset(...)`).

A CNCJob object in these loops: wrap its call in `with self.app.history.snapshot(label, [obj]):` in place of `record_matrix` (`record_matrix` skips the kinds without a matrix path, so without the snapshot a CNCJob change is not undoable).

- [ ] **Step 3: Properties buttons** — in `on_offset_button_click`, `on_scale_button_click`, `on_skew_button_click` of `FlatCAMObj`: after the object method call, record the matrix that the method used (`affine_translate_matrix(*vector_val)`, `affine_scale_matrix(factor, factor, point)` with the point the method uses, `affine_skew_matrix(...)`). Read each method first: the scale point and the skew origin come from the object bounds inside `scale()` / `skew()` when `point is None`; compute the same point before the call.

- [ ] **Step 4: Align plugin** — in `appPlugins/ToolAlignObjects/Align.py`:
  - delete the module function `apply_matrix_to_object` and `from appHandlers.appHistory import apply_matrix_to_object` in its place; remove the now unused imports of `Excellon`, `Gerber`, `Geometry`;
  - delete `HISTORY_SIZE`, `self.undo_stack`, `self.redo_stack`, `record_alignment`, `update_history_state`, `_history_step`, `on_undo`, `on_redo` and the 2 button connections;
  - where `self.record_alignment(aligned_obj, matrix)` is called (in `finish` and `apply_auto`), call `self.app.history.record_matrix(_("Align Objects"), [(aligned_obj, matrix)])`;
  - in `AlignUI.py`, delete `undo_redo_box`, `undo_button`, `redo_button`;
  - in `tests/test_align_apply.py`, delete `_history_tool` and `test_undo_redo_history` (the app history tests cover it), and import `apply_matrix_to_object` from `appHandlers.appHistory`.

- [ ] **Step 5: Editor save** — in `appMain.py` `on_editing_finished`, where the edited object is written back (the branch that is not `force_cancel`), after the write-back:

```python
            try:
                self.history.forget(edited_obj.history_uid)
            except AttributeError:
                pass
```

Use the real name of the edited object variable in that method.

- [ ] **Step 6: Tests** — append to `tests/test_app_history_app.py`:
  - select 2 Gerber objects (`fc.collection.set_active` / the selection API used in the other tests), call `fc.object_ops.on_flipy()`, check 1 history step, undo, both bounds back;
  - Align: `fc.align_objects_tool` with `apply_matrix_to_object` + `record_matrix` gives 1 step labelled "Align Objects";
  - after `fc.history.forget(uid)` no step touches the uid.

- [ ] **Step 7: Run**

Run: `& .\.venv\Scripts\python.exe -m pytest tests/test_app_history.py tests/test_app_history_app.py tests/test_align_apply.py tests/test_align_objects.py tests/test_align_auto.py tests/test_tool_transform.py -q`
Expected: all pass.

---

### Task 6: Tcl commands and preferences

**Files:**
- Modify: `tclCommands/TclCommand.py` (the 2 `execute_wrapper`, lines 346 and 405)
- Modify: `defaults.py`
- Modify: the General preferences group that holds the app settings (find it: `grep -rn "global_delete_confirmation" appGUI/preferences`)

- [ ] **Step 1: Tcl** — in both `execute_wrapper`, run the body inside:

```python
        history = getattr(self.app, 'history', None)
        with history.suspended() if history is not None else contextlib.nullcontext():
            <the existing body>
```

Add `import contextlib` to the file. A `TclCommandSignaled` runs its work in a worker and waits: the suspension covers that time because the wrapper waits for the signal.

- [ ] **Step 2: Preferences** — `defaults.py`, next to `global_delete_confirmation`:

```python
        "global_history_steps": 100,
        "global_history_memory_mb": 256,
```

In the preferences group that holds `global_delete_confirmation`, add 2 `FCSpinner` fields with the labels "Undo steps" (range 1..1000, tooltip: "The number of actions that Undo can go back, for each project.") and "Undo memory (MB)" (range 16..4096, tooltip: "The memory that the Undo history can keep for each project. The oldest steps are dropped first."). Register them in the form-field dict of that group exactly as the neighbor fields are registered (same pattern, same key names).

- [ ] **Step 3: Run**

Run: `& .\.venv\Scripts\python.exe -m pytest tests -q -m "not slow" -k "tcl or pref or default or option"`
Expected: no new failure.

---

### Task 7: Changelog, full check

- [ ] **Step 1:** Add a "Undo / Redo" section at the top of the `21.10.2026` block of `CHANGELOG.md`: what is recorded, the keys, the limits (100 steps / 256 MB per project, in Preferences), what is not recorded (Tcl, headless, editors), and that the Align plugin uses it. Replace the Align line "Undo and Redo of the last 50 alignments ..." with "the alignments are in the app Undo / Redo history".
- [ ] **Step 2:** Run the milestone suite: `& .\.venv\Scripts\python.exe -m pytest tests -q -m "not slow"` (about 5.5 min). Then the slow history tests: `& .\.venv\Scripts\python.exe -m pytest tests/test_app_history_app.py -q`.
- [ ] **Step 3:** Start the app (`& .\.venv\Scripts\python.exe flatcam.py`), open a Gerber, rotate it from the Edit menu, Ctrl+Z, Ctrl+Y, delete it, Ctrl+Z. This is a manual check for the user; list it in the report.
