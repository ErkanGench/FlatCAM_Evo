# Multiple Projects in the Project Tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Project tab holds more than 1 project. A combobox above the object tree selects the active project. Inactive projects keep their geometry and their Properties UI but release their plot shapes. A switch is refused while an editor is open or a task is queued or runs.

**Architecture:** A new `ProjectContext` holds the state of 1 project. A new `ProjectManager` holds the list of contexts and puts the state of the active context into the existing `App` attributes (`app.collection`, `app.options`, `app.project_filename`, `app.should_we_save`, `app.all_objects_list`). Because all existing code reads `app.collection` when it runs, the 817 existing call sites do not change. A new `ProjectSelector` widget shows the combobox and its right-click menu.

**Tech Stack:** Python 3.11, PyQt6, VisPy, `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-18-multiple-projects-design.md`

---

## Rules for the agent (read first)

1. Work on the local branch `1.0`. Do not make a new branch. Do not push.
2. Run Python with the project venv: `.venv/Scripts/python.exe`. Run a test file from the repository root with unittest discovery: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_manager.py"`. Do not run a test file as a script (`python tests/x.py`): then `tests/` is first on `sys.path` and `import appObjects` fails with `ModuleNotFoundError`.
3. Run only the test files that the task names. Do not run the full test suite. The full suite takes about 4 minutes and runs only once, in Task 13.
4. Do not add a `Co-Authored-By` line or any Claude attribution to a commit message.
5. Commit only the files that the task names. The folder `docs/mach3/` is not part of this work. Do not add it.
6. The line numbers in this plan are approximate. Find each place by the quoted code text, not by the line number.
7. Match the style of the code around the change: 4-space indent, `_()` for user-visible strings, the same comment style.
8. If a test fails and the fix is not clear in 2 tries, stop and report the error text. Do not change a test to make it pass.
9. WARNING: Never run `taskkill /IM python.exe`. It stops every Python process, including a FlatCAM that the user runs with unsaved work. If a test run hangs, stop only the process that you started, by its PID. Never run Python with a heredoc or with `python -` (stdin): it hangs.

## Files

| File | Status | Responsibility |
|---|---|---|
| `appObjects/ProjectContext.py` | Create | `ProjectContext` class and 3 helper functions for names and paths. No Qt. |
| `appHandlers/appProjects.py` | Create | `ProjectManager`: the list of projects, switch, new, rename, close, save rules, dialogs. |
| `appGUI/ProjectSelector.py` | Create | `ProjectSelector` widget: label, combobox, right-click menu. |
| `tclCommands/TclCommandListProjects.py` | Create | Tcl `list_projects`. |
| `tclCommands/TclCommandSelectProject.py` | Create | Tcl `select_project`. |
| `tclCommands/TclCommandCloseProject.py` | Create | Tcl `close_project`. |
| `tclCommands/__init__.py` | Modify | Import the 3 new Tcl modules. |
| `appHandlers/appPlotManager.py` | Modify | `collection` becomes a property that reads `app.collection`. |
| `appHandlers/appEdit.py` | Modify | `collection` becomes a property that reads `app.collection`. |
| `appMain.py` | Modify | Create the `ProjectManager` and the `ProjectSelector`. |
| `appGUI/MainGUI.py` | Modify | `set_ui_title` shows the active project name. |
| `appHandlers/appIO.py` | Modify | File > New, Open, Save and Save As follow the new rules. |
| `appHandlers/appLifecycle.py` | Modify | Exit asks about each project with unsaved changes. |
| `tests/test_project_context.py` | Create | Tests for Task 2. |
| `tests/test_projects_manager.py` | Create | Tests for Tasks 3 to 7. |
| `tests/test_project_selector.py` | Create | Tests for Task 8. |
| `tests/test_projects_appio.py` | Create | Tests for Tasks 9 and 10. |
| `tests/test_tcl_projects.py` | Create | Tests for Task 12. |
| `CHANGELOG.md` | Modify | 1 entry, Task 13. |

## Order of the tasks

Do the tasks in order. Each task ends with a commit. Each task depends only on the tasks before it.

---

### Task 1: The plot manager and the edit handler read the live collection

`AppPlotManager` and `appEditor` copy `app.collection` once in `__init__`. After a project switch, the copy points to the old collection. A property fixes this.

**Files:**
- Modify: `appHandlers/appPlotManager.py` (about line 29)
- Modify: `appHandlers/appEdit.py` (about line 35)
- Test: `tests/test_projects_manager.py` (create the file in this task)

- [ ] **Step 1: Write the failing test**

Create `tests/test_projects_manager.py` with this content:

```python
"""Tests for the multiple projects feature: ProjectManager and the handlers that read app.collection."""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6 import QtWidgets


class FakeCollection:
    def __init__(self, objects=None):
        self.view = QtWidgets.QWidget()
        self.objects = list(objects or [])

    def get_list(self):
        return list(self.objects)

    def has_promises(self):
        return False

    def has_plot_promises(self):
        return False


class TestHandlersReadLiveCollection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_plot_manager_reads_app_collection(self):
        from appHandlers.appPlotManager import AppPlotManager
        app = SimpleNamespace(log=Mock(), inform=Mock(), options={}, collection=FakeCollection(),
                              worker_task=Mock(), plotcanvas=Mock(), clear_pool=Mock(), app_obj=Mock(),
                              defaults={}, proc_container=Mock())
        manager = AppPlotManager(app)
        second = FakeCollection()
        app.collection = second
        self.assertIs(manager.collection, second)

    def test_edit_handler_reads_app_collection(self):
        from appHandlers.appEdit import appEditor
        app = SimpleNamespace(log=Mock(), inform=Mock(), splash=Mock(), worker_task=Mock(), options={},
                              app_units='MM', defaults={}, collection=FakeCollection(), app_obj=Mock(),
                              decimals=4)
        handler = appEditor(app)
        second = FakeCollection()
        app.collection = second
        self.assertIs(handler.collection, second)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run the test and see it fail**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_manager.py"`
Expected: 2 failures, `AssertionError: <...FakeCollection...> is not <...FakeCollection...>`.

- [ ] **Step 3: Change `appHandlers/appPlotManager.py`**

Remove this line from `AppPlotManager.__init__`:

```python
        self.collection = app.collection
```

Add this property to the class `AppPlotManager`, directly after the end of `__init__` (before `def _get_gerber_color_list`):

```python
    @property
    def collection(self):
        # the active project can change, so always read the live collection
        return self.app.collection
```

- [ ] **Step 4: Change `appHandlers/appEdit.py`**

Remove this line from `appEditor.__init__`:

```python
        self.collection = self.app.collection
```

Add this property to the class `appEditor`, directly after the end of `__init__` (before `def build_geometry_tool_table`):

```python
    @property
    def collection(self):
        # the active project can change, so always read the live collection
        return self.app.collection
```

- [ ] **Step 5: Run the test and see it pass**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_manager.py"`
Expected: `OK` (2 tests).

Also run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_plot_visibility_toggle.py"`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
rtk git add appHandlers/appPlotManager.py appHandlers/appEdit.py tests/test_projects_manager.py
rtk git commit -m "refactor(projects): the plot manager and the edit handler read the live app.collection"
```

---

### Task 2: `ProjectContext` and the name and path helpers

**Files:**
- Create: `appObjects/ProjectContext.py`
- Test: `tests/test_project_context.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_project_context.py`:

```python
"""Tests for ProjectContext and its helper functions."""

import os
import unittest

from appObjects.ProjectContext import ProjectContext, unique_name, same_path, name_from_filename, \
    is_valid_name


class TestProjectContext(unittest.TestCase):
    def test_defaults(self):
        collection = object()
        ctx = ProjectContext(name='Board_A', collection=collection)
        self.assertEqual(ctx.name, 'Board_A')
        self.assertIs(ctx.collection, collection)
        self.assertIsNone(ctx.filename)
        self.assertIsNone(ctx.options)
        self.assertFalse(ctx.should_we_save)
        self.assertIsNone(ctx.view_rect)

    def test_unique_name_free(self):
        self.assertEqual(unique_name('Board', ['Other']), 'Board')

    def test_unique_name_adds_number(self):
        self.assertEqual(unique_name('Board', ['Board']), 'Board_1')

    def test_unique_name_increments_number(self):
        self.assertEqual(unique_name('Project_1', ['Project_1', 'Project_2']), 'Project_3')

    def test_same_path(self):
        self.assertTrue(same_path('a/b/../c.FlatPrj', 'a/c.FlatPrj'))
        self.assertFalse(same_path('a/c.FlatPrj', 'a/d.FlatPrj'))
        self.assertFalse(same_path(None, 'a/d.FlatPrj'))

    def test_same_path_ignores_case_on_windows(self):
        if os.name == 'nt':
            self.assertTrue(same_path('C:/X/Board.FlatPrj', 'c:/x/board.flatprj'))

    def test_name_from_filename(self):
        self.assertEqual(name_from_filename(os.path.join('x', 'Board_A.FlatPrj')), 'Board_A')

    def test_is_valid_name(self):
        self.assertTrue(is_valid_name('Board A'))
        self.assertFalse(is_valid_name(''))
        self.assertFalse(is_valid_name('   '))
        for char in '\\/:*?"<>|':
            self.assertFalse(is_valid_name('Bo%sard' % char))


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run the test and see it fail**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_project_context.py"`
Expected: `ModuleNotFoundError: No module named 'appObjects.ProjectContext'`.

- [ ] **Step 3: Write `appObjects/ProjectContext.py`**

```python
import os
import re

PROJECT_EXT = '.FlatPrj'

# characters that a file name on Windows can not hold
_INVALID_NAME_CHARS = '\\/:*?"<>|'


class ProjectContext:
    """
    The state of 1 project in the Project tab.

    While the project is active, its live state is in the App attributes (app.collection, app.options,
    app.project_filename, app.should_we_save). ProjectManager.capture() writes that state back here.
    """

    def __init__(self, name, collection, filename=None):
        self.name = name
        self.collection = collection
        self.filename = filename
        # only the project keys (see defaults.project_options); the application settings are not per project
        # None means: copy the project keys from the application defaults when the project becomes active
        self.options = None
        self.should_we_save = False
        # the canvas view rectangle when the project was last active
        self.view_rect = None


def unique_name(base, used):
    """
    Return base, or base with a number added or incremented, so that the result is not in used.
    The rule is the same as in ObjectCollection.append() for object names.

    :param base:    the wanted name
    :param used:    the names that are already taken
    :return:        a name that is not in used
    """
    name = base
    while name in used:
        match = re.search(r'(.*[^\d])?(\d+)$', name)
        if match:
            name = (match.group(1) or '') + str(int(match.group(2)) + 1)
        else:
            name += '_1'
    return name


def same_path(first, second):
    """
    True if the 2 paths point to the same file. An empty path is never the same.
    """
    if not first or not second:
        return False
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def name_from_filename(filename):
    """
    The project name for a project file: the file name without the folder and the extension.
    """
    return os.path.splitext(os.path.basename(filename))[0]


def is_valid_name(name):
    """
    True if the name is not empty and can be used as a file name.
    """
    if not name or not name.strip():
        return False
    return not any(char in name for char in _INVALID_NAME_CHARS)
```

- [ ] **Step 4: Run the test and see it pass**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_project_context.py"`
Expected: `OK` (8 tests).

- [ ] **Step 5: Commit**

```bash
rtk git add appObjects/ProjectContext.py tests/test_project_context.py
rtk git commit -m "feat(projects): add ProjectContext and the project name helpers"
```

---

### Task 3: `ProjectManager` core: list, capture, load and switch

This task makes the manager without dialogs. The visual steps of a switch (`before_switch`, `deactivate`, `activate`) are empty in this task. Task 5 fills them.

A switch is refused while the app is busy. "Busy" also covers a task that is queued in the worker stack but not started yet, and an open editor. A switch with an open editor would lose the editor changes.

**Files:**
- Create: `appHandlers/appProjects.py`
- Modify: `appWorkerStack.py` (add the method `pending_count`)
- Test: `tests/test_projects_manager.py` (add tests)

- [ ] **Step 1: Write the failing tests**

In `tests/test_projects_manager.py`, add this code after the class `TestHandlersReadLiveCollection` and before `if __name__ == '__main__':`:

```python
def make_app(collection=None):
    from defaults import AppOptions
    # a merged AppOptions, as in the App: it stores the project keys and sends the other keys to "defaults"
    defaults = {'units': 'MM', 'global_gridx': 1.0}
    return SimpleNamespace(
        collection=collection or FakeCollection(), defaults=defaults,
        options=AppOptions(version='test', baseline=defaults, defaults=defaults), project_filename=None,
        should_we_save=False, all_objects_list=[], inform=Mock(), log=Mock(),
        ui=SimpleNamespace(set_ui_title=Mock()),
        proc_container=SimpleNamespace(get_procs_count=Mock(return_value=0)),
        workers=SimpleNamespace(pending_count=Mock(return_value=0)), call_source='app',
        save_in_progress=False, app_obj=SimpleNamespace(load_batches=set()), plotcanvas=None)


def make_manager(app=None):
    from appHandlers.appProjects import ProjectManager
    app = app or make_app()
    manager = ProjectManager(app, collection_factory=FakeCollection)
    manager.before_switch = Mock()
    manager.deactivate = Mock()
    manager.activate = Mock()
    manager.reset_options = Mock()
    return app, manager


class TestProjectManagerCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_first_project_wraps_the_existing_collection(self):
        app, manager = make_manager()
        self.assertEqual(manager.names(), ['Project_1'])
        self.assertIs(manager.active.collection, app.collection)
        self.assertIs(manager.stack.currentWidget(), app.collection.view)

    def test_get_by_name(self):
        app, manager = make_manager()
        self.assertIs(manager.get_by_name('Project_1'), manager.active)
        self.assertIsNone(manager.get_by_name('Missing'))

    def test_switch_swaps_the_app_state(self):
        app, manager = make_manager()
        first = manager.active
        second = manager.add_context('Board_B')
        second.options = {'units': 'IN'}
        second.filename = 'b.FlatPrj'
        second.should_we_save = True
        app.project_filename = 'a.FlatPrj'
        app.should_we_save = False

        self.assertTrue(manager.switch(second))

        self.assertIs(manager.active, second)
        self.assertIs(app.collection, second.collection)
        self.assertEqual(app.options['units'], 'IN')
        self.assertEqual(app.project_filename, 'b.FlatPrj')
        self.assertTrue(app.should_we_save)
        self.assertEqual(app.all_objects_list, [])
        self.assertIs(manager.stack.currentWidget(), second.collection.view)
        # the old state is written back to the old context; only the project keys are kept
        self.assertEqual(first.options, {'units': 'MM'})
        self.assertEqual(first.filename, 'a.FlatPrj')
        self.assertFalse(first.should_we_save)
        manager.deactivate.assert_called_once_with(first)
        manager.activate.assert_called_once_with(second)
        app.ui.set_ui_title.assert_called_with(name='Board_B')

    def test_switch_back_restores_the_first_state(self):
        app, manager = make_manager()
        first = manager.active
        second = manager.add_context('Board_B')
        manager.switch(second)
        app.options['units'] = 'IN'
        manager.switch(first)
        self.assertEqual(app.options['units'], 'MM')
        self.assertIs(app.collection, first.collection)

    def test_switch_does_not_change_the_application_settings(self):
        app, manager = make_manager()
        first = manager.active
        second = manager.add_context('Board_B')
        second.options = {'units': 'IN', 'global_gridx': 9.0}
        manager.switch(second)
        app.options['global_gridx'] = 2.0
        manager.switch(first)
        # an application key is not part of a project: it keeps the last value and is not saved in the context
        self.assertEqual(app.options['global_gridx'], 2.0)
        self.assertEqual(app.defaults['global_gridx'], 2.0)
        self.assertNotIn('global_gridx', second.options)

    def test_switch_without_options_resets_options(self):
        app, manager = make_manager()
        second = manager.add_context('Board_B')
        manager.switch(second)
        manager.reset_options.assert_called_once_with()

    def test_switch_without_visuals(self):
        app, manager = make_manager()
        second = manager.add_context('Board_B')
        manager.switch(second, visuals=False)
        manager.before_switch.assert_not_called()
        manager.deactivate.assert_not_called()
        manager.activate.assert_not_called()
        self.assertIs(app.collection, second.collection)

    def test_switch_without_visuals_keeps_the_saved_views(self):
        # on exit the app saves inactive projects with visuals=False; the canvas keeps the view of the first project
        app, manager = make_manager()
        first = manager.active
        second = manager.add_context('Board_B')
        second.view_rect = 'view-B'
        manager._get_view_rect = Mock(return_value='view-A')
        manager.switch(second, visuals=False)
        manager.switch(first, visuals=False)
        self.assertEqual(second.view_rect, 'view-B')
        self.assertEqual(first.view_rect, 'view-A')
        self.assertIs(manager.displayed, first)

    def test_visual_switch_releases_the_displayed_project(self):
        app, manager = make_manager()
        first = manager.active
        second = manager.add_context('Board_B')
        third = manager.add_context('Board_C')
        manager.switch(second, visuals=False)
        manager.switch(third)
        # the canvas showed the first project, so its shapes are released, not the ones of the second project
        manager.deactivate.assert_called_once_with(first)
        self.assertIs(manager.displayed, third)

    def test_switch_to_active_does_nothing(self):
        app, manager = make_manager()
        self.assertTrue(manager.switch(manager.active))
        manager.deactivate.assert_not_called()

    def test_switch_is_refused_while_busy(self):
        app, manager = make_manager()
        second = manager.add_context('Board_B')
        app.proc_container.get_procs_count.return_value = 1
        self.assertFalse(manager.switch(second))
        self.assertIsNot(manager.active, second)
        app.inform.emit.assert_called()

    def test_is_busy_sources(self):
        app, manager = make_manager()
        self.assertFalse(manager.is_busy())
        app.save_in_progress = True
        self.assertTrue(manager.is_busy())
        app.save_in_progress = False
        # a File -> Save that the GUI has not completed yet (Task 10)
        app.project_save_pending = True
        self.assertTrue(manager.is_busy())
        app.project_save_pending = False
        app.app_obj.load_batches.add(object())
        self.assertTrue(manager.is_busy())
        app.app_obj.load_batches.clear()
        # a task that is queued but not started yet (for example the parse of a project or a plot)
        app.workers.pending_count.return_value = 1
        self.assertTrue(manager.is_busy())

    def test_switch_is_refused_while_an_editor_is_open(self):
        app, manager = make_manager()
        second = manager.add_context('Board_B')
        app.call_source = 'geo_editor'
        self.assertTrue(manager.is_busy())
        self.assertFalse(manager.switch(second))
        self.assertIsNot(manager.active, second)
        self.assertIn('Close the editor first', app.inform.emit.call_args[0][0])

    def test_worker_stack_pending_count(self):
        from appWorkerStack import WorkerStack
        stack = WorkerStack(workers_number=1)
        try:
            self.assertEqual(stack.pending_count(), 0)
            stack._deferred_tasks.append(object())
            self.assertEqual(stack.pending_count(), 1)
        finally:
            stack._deferred_tasks.clear()
            stack.quit()

    def test_projects_changed_is_emitted_on_switch(self):
        app, manager = make_manager()
        second = manager.add_context('Board_B')
        listener = Mock()
        manager.projects_changed.connect(listener)
        manager.switch(second)
        listener.assert_called()
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_manager.py"`
Expected: errors with `ModuleNotFoundError: No module named 'appHandlers.appProjects'`.

- [ ] **Step 3a: Add `pending_count` to the worker stack**

In `appWorkerStack.py`, in the class `WorkerStack`, add this method after the method `on_task_completed`:

```python
    def pending_count(self):
        """
        Return the number of tasks that are queued or run now, including the deferred low priority tasks.
        """
        return self._pending_count + len(self._deferred_tasks)
```

- [ ] **Step 3: Write `appHandlers/appProjects.py`**

```python
from copy import deepcopy
import os

from PyQt6 import QtCore, QtWidgets

from appObjects.ProjectContext import ProjectContext, unique_name, same_path, name_from_filename, \
    is_valid_name, PROJECT_EXT
from defaults import project_options

# App Translation
import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class ProjectManager(QtCore.QObject):
    """
    Holds the projects of the Project tab. Only 1 project is active. The state of the active project is in the
    App attributes, so the existing code that reads app.collection works on the active project.
    """

    # emitted when the list of projects, a name or the active project changes
    projects_changed = QtCore.pyqtSignal()

    def __init__(self, app, collection_factory=None):
        super().__init__()
        self.app = app
        self.collection_factory = collection_factory if collection_factory is not None else self._make_collection

        # 1 tree view for each project; a switch shows the view of the active project
        self.stack = QtWidgets.QStackedWidget()

        first = ProjectContext(name=self.default_name(), collection=app.collection)
        self.contexts = [first]
        self.active = first
        # the project that the canvas shows. It is not always the active project: a switch with visuals=False
        # (used on exit) changes the active project but not the canvas.
        self.displayed = first
        self.stack.addWidget(first.collection.view)
        self.stack.setCurrentWidget(first.collection.view)

    def _make_collection(self):
        from appObjects.ObjectCollection import ObjectCollection

        collection = ObjectCollection(app=self.app)
        collection.view.setMinimumWidth(290)
        return collection

    # ------------------------------------------------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------------------------------------------------
    def names(self):
        return [ctx.name for ctx in self.contexts]

    def default_name(self):
        used = [ctx.name for ctx in getattr(self, 'contexts', [])]
        return unique_name('%s_1' % _("Project"), used)

    def get_by_name(self, name):
        for ctx in self.contexts:
            if ctx.name == name:
                return ctx
        return None

    def filename_of(self, ctx):
        # the live filename of the active project is in the App
        return self.app.project_filename if ctx is self.active else ctx.filename

    def find_by_filename(self, filename):
        for ctx in self.contexts:
            if same_path(self.filename_of(ctx), filename):
                return ctx
        return None

    def is_editing(self):
        """
        True if an editor is open. A switch then would lose the changes of the editor.
        """
        return getattr(self.app, 'call_source', 'app') != 'app'

    def is_busy(self):
        """
        True if a switch is not allowed now: an editor is open, or a task is queued or runs. A task that ends after
        a switch can add its result to the wrong project.
        """
        app = self.app
        if self.is_editing():
            return True
        # a task counts from the moment it is queued, before its worker starts. A worker that hands its result to
        # the GUI thread (for example the parse of a project, which then starts the restore of the objects) posts
        # that signal before its "task completed" signal, so the next stage is registered before this count is 0.
        workers = getattr(app, 'workers', None)
        if workers is not None and workers.pending_count() > 0:
            return True
        try:
            if app.proc_container.get_procs_count() > 0:
                return True
        except AttributeError:
            pass
        if getattr(app, 'save_in_progress', False) or getattr(app, 'project_save_pending', False):
            return True
        collection = app.collection
        if collection.has_promises() or collection.has_plot_promises():
            return True
        return bool(getattr(getattr(app, 'app_obj', None), 'load_batches', None))

    def inform_busy(self):
        if self.is_editing():
            msg = _("Close the editor first.")
        else:
            msg = _("A task is running. Wait until it ends.")
        self.app.inform.emit('[WARNING_NOTCL] %s' % msg)

    # ------------------------------------------------------------------------------------------------------------
    # Switch
    # ------------------------------------------------------------------------------------------------------------
    def add_context(self, name):
        """
        Add an empty project to the list. It does not become active.
        """
        ctx = ProjectContext(name=unique_name(name, self.names()), collection=self.collection_factory())
        self.contexts.append(ctx)
        self.stack.addWidget(ctx.collection.view)
        self.projects_changed.emit()
        return ctx

    def capture(self):
        """
        Write the live state of the active project from the App back into its context.
        """
        ctx = self.active
        # only the project keys; the application settings stay in app.defaults for all projects
        ctx.options = deepcopy(project_options(self.app.options))
        ctx.filename = self.app.project_filename
        ctx.should_we_save = self.app.should_we_save
        # the canvas shows the view of the displayed project; after a switch with visuals=False that is another
        # project, and its view must not go into this context
        if ctx is self.displayed:
            ctx.view_rect = self._get_view_rect()

    def _load(self, ctx):
        """
        Put the state of the context into the App.
        """
        self.app.collection = ctx.collection
        if ctx.options is not None:
            # copies the project keys from the defaults, then puts the saved project keys over them
            self.app.options.load_project(deepcopy(ctx.options))
        else:
            self.reset_options()
        self.app.project_filename = ctx.filename
        self.app.should_we_save = ctx.should_we_save
        self.app.all_objects_list = ctx.collection.get_list()
        self.stack.setCurrentWidget(ctx.collection.view)

    def switch(self, ctx, visuals=True):
        """
        Make ctx the active project.

        :param ctx:     the ProjectContext to activate
        :param visuals: if False, the plots and the plugins are not changed (used on exit)
        :return:        True if ctx is now the active project
        """
        if ctx is self.active:
            return True
        if ctx not in self.contexts:
            return False
        if self.is_busy():
            self.inform_busy()
            return False

        self.capture()
        if visuals:
            self.before_switch()
            # release the project that the canvas shows; after a switch with visuals=False it is not the active one
            if self.displayed is not None:
                self.deactivate(self.displayed)

        self.active = ctx
        self._load(ctx)

        if visuals:
            self.activate(ctx)
            self.displayed = ctx

        self.projects_changed.emit()
        self.update_title()
        return True

    def update_title(self):
        self.app.ui.set_ui_title(name=self.active.name)

    # ------------------------------------------------------------------------------------------------------------
    # Steps that change the GUI. Task 5 fills them.
    # ------------------------------------------------------------------------------------------------------------
    def reset_options(self):
        pass

    def before_switch(self):
        pass

    def deactivate(self, ctx):
        pass

    def activate(self, ctx):
        pass

    def _get_view_rect(self):
        return None
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_manager.py"`
Expected: `OK` (17 tests).

- [ ] **Step 5: Commit**

```bash
rtk git add appHandlers/appProjects.py appWorkerStack.py tests/test_projects_manager.py
rtk git commit -m "feat(projects): add the ProjectManager with switch, capture and load"
```

---

### Task 4: `ProjectManager`: new, rename, close and the file name rules

**Files:**
- Modify: `appHandlers/appProjects.py`
- Test: `tests/test_projects_manager.py` (add tests)

- [ ] **Step 1: Write the failing tests**

In `tests/test_projects_manager.py`, add this class after `TestProjectManagerCore` and before `if __name__ == '__main__':`:

```python
class TestProjectManagerLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_new_adds_a_unique_project_and_activates_it(self):
        app, manager = make_manager()
        ctx = manager.new()
        self.assertEqual(manager.names(), ['Project_1', 'Project_2'])
        self.assertIs(manager.active, ctx)
        self.assertIs(app.collection, ctx.collection)

    def test_new_is_refused_while_busy(self):
        app, manager = make_manager()
        app.save_in_progress = True
        self.assertIsNone(manager.new())
        self.assertEqual(manager.names(), ['Project_1'])

    def test_rename(self):
        app, manager = make_manager()
        manager.new()
        self.assertTrue(manager.rename(manager.active, ' Board_B '))
        self.assertEqual(manager.active.name, 'Board_B')
        app.ui.set_ui_title.assert_called_with(name='Board_B')

    def test_rename_refuses_a_used_name(self):
        app, manager = make_manager()
        manager.new()
        self.assertFalse(manager.rename(manager.active, 'Project_1'))
        self.assertEqual(manager.active.name, 'Project_2')

    def test_rename_refuses_a_name_that_is_not_valid(self):
        app, manager = make_manager()
        self.assertFalse(manager.rename(manager.active, 'a/b'))
        self.assertFalse(manager.rename(manager.active, ''))

    def test_is_dirty_needs_changes_and_objects(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        self.assertFalse(manager.is_dirty(manager.active))
        app.should_we_save = True
        self.assertTrue(manager.is_dirty(manager.active))
        self.assertEqual(manager.dirty_contexts(), [manager.active])

    def test_saved_project_with_all_objects_deleted_is_dirty(self):
        # the deletion of all the objects of a saved project is a change that must be saved
        app, manager = make_manager()
        app.should_we_save = True
        self.assertFalse(manager.is_dirty(manager.active))
        app.project_filename = os.path.join('folder', 'Project_1.FlatPrj')
        self.assertTrue(manager.is_dirty(manager.active))
        # so the GUI close asks and the Tcl close needs -force
        self.assertFalse(manager.close(manager.active))
        self.assertTrue(manager.close(manager.active, force=True))

    def test_close_inactive_project(self):
        app, manager = make_manager()
        first = manager.active
        second = manager.new()
        self.assertTrue(manager.close(first))
        self.assertEqual(manager.names(), ['Project_2'])
        self.assertIs(manager.active, second)
        self.assertEqual(manager.stack.count(), 1)

    def test_close_active_project_activates_the_previous_one(self):
        app, manager = make_manager()
        first = manager.active
        second = manager.new()
        self.assertTrue(manager.close(second))
        self.assertIs(manager.active, first)
        self.assertEqual(manager.names(), ['Project_1'])

    def test_close_last_project_leaves_one_empty_project(self):
        app, manager = make_manager()
        first = manager.active
        self.assertTrue(manager.close(first))
        self.assertEqual(len(manager.contexts), 1)
        self.assertIsNot(manager.active, first)
        self.assertEqual(manager.active.name, 'Project_2')

    def test_close_refuses_a_dirty_project_without_force(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        app.should_we_save = True
        self.assertFalse(manager.close(manager.active))
        self.assertTrue(manager.close(manager.active, force=True))

    def test_save_target_without_file(self):
        app, manager = make_manager()
        self.assertIsNone(manager.save_target())

    def test_save_target_same_name(self):
        app, manager = make_manager()
        path = os.path.join('folder', 'Project_1.FlatPrj')
        app.project_filename = path
        self.assertEqual(manager.save_target(), path)

    def test_save_target_after_rename(self):
        app, manager = make_manager()
        app.project_filename = os.path.join('folder', 'Project_1.FlatPrj')
        manager.rename(manager.active, 'Board_B')
        self.assertEqual(manager.save_target(), os.path.join('folder', 'Board_B.FlatPrj'))

    def test_adopt_filename_renames_the_active_project(self):
        app, manager = make_manager()
        manager.new()
        manager.rename(manager.active, 'Board')
        manager.switch(manager.contexts[0])
        manager.adopt_filename(os.path.join('folder', 'Board.FlatPrj'))
        self.assertEqual(manager.active.name, 'Board_1')
        self.assertEqual(manager.active.filename, os.path.join('folder', 'Board.FlatPrj'))

    def test_find_by_filename_uses_the_live_filename(self):
        app, manager = make_manager()
        app.project_filename = os.path.join('folder', 'Board.FlatPrj')
        self.assertIs(manager.find_by_filename(os.path.join('folder', '.', 'Board.FlatPrj')), manager.active)
        self.assertIsNone(manager.find_by_filename(os.path.join('folder', 'Other.FlatPrj')))
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_manager.py"`
Expected: errors such as `AttributeError: 'ProjectManager' object has no attribute 'new'`.

- [ ] **Step 3: Add the methods to `appHandlers/appProjects.py`**

Add this block to the class `ProjectManager`, directly after the method `update_title` and before the comment block `# Steps that change the GUI. Task 5 fills them.`:

```python
    # ------------------------------------------------------------------------------------------------------------
    # New, rename, close
    # ------------------------------------------------------------------------------------------------------------
    def new(self, visuals=True):
        """
        Add an empty project and make it active.

        :return:    the new ProjectContext, or None if a task runs
        """
        if self.is_busy():
            self.inform_busy()
            return None

        ctx = self.add_context(self.default_name())
        if not self.switch(ctx, visuals=visuals):
            self._dispose(ctx)
            return None
        return ctx

    def rename(self, ctx, name):
        """
        :return:    True if the name changed. False if the name is not valid or another project uses it.
        """
        name = name.strip() if name else ''
        if not is_valid_name(name):
            return False
        if name in [other.name for other in self.contexts if other is not ctx]:
            return False

        ctx.name = name
        self.projects_changed.emit()
        if ctx is self.active:
            self.update_title()
        return True

    def is_dirty(self, ctx):
        """
        True if the project has unsaved changes. A project with a file is dirty when its flag is set, also when it
        is empty: the deletion of all its objects is a change. A project without a file and without objects has
        nothing to save, the same rule as the exit of the app with 1 project (AppLifecycle.final_save).
        """
        flag = self.app.should_we_save if ctx is self.active else ctx.should_we_save
        if not flag:
            return False
        return bool(ctx.collection.get_list()) or self.filename_of(ctx) is not None

    def dirty_contexts(self):
        return [ctx for ctx in self.contexts if self.is_dirty(ctx)]

    def close(self, ctx, force=False, visuals=True):
        """
        Close and remove a project. There is no dialog.

        :param ctx:     the project to close
        :param force:   if True, a project with unsaved changes is closed and the changes are lost
        :param visuals: passed to switch()
        :return:        True if the project is removed
        """
        if ctx not in self.contexts:
            return False
        if self.is_dirty(ctx) and not force:
            return False
        if self.is_busy():
            self.inform_busy()
            return False

        if ctx is self.active:
            if len(self.contexts) > 1:
                idx = self.contexts.index(ctx)
                target = self.contexts[idx - 1] if idx > 0 else self.contexts[idx + 1]
                if not self.switch(target, visuals=visuals):
                    return False
            elif self.new(visuals=visuals) is None:
                return False

        self._dispose(ctx)
        return True

    def _dispose(self, ctx):
        """
        Remove an inactive project from the list and release its objects.
        """
        if ctx in self.contexts:
            self.contexts.remove(ctx)
        if self.displayed is ctx:
            self.displayed = None

        for obj in ctx.collection.get_list():
            try:
                obj.clear(update=False)
            except Exception as err:
                self.app.log.error("ProjectManager._dispose() --> %s" % str(err))
            try:
                obj.mark_shapes.clear(update=False)
                obj.mark_shapes.parent = None
            except AttributeError:
                pass

        self.stack.removeWidget(ctx.collection.view)
        ctx.collection.view.deleteLater()
        try:
            ctx.collection.deleteLater()
        except AttributeError:
            pass
        ctx.collection = None
        self.projects_changed.emit()

    # ------------------------------------------------------------------------------------------------------------
    # File name rules
    # ------------------------------------------------------------------------------------------------------------
    def save_target(self, ctx=None):
        """
        The file that a Save of the project writes.

        :return:    None if the project has no file (then Save As is needed). The current file if the project name
                    is the file name. Else, '<name>.FlatPrj' in the folder of the current file.
        """
        ctx = ctx if ctx is not None else self.active
        filename = self.filename_of(ctx)
        if not filename:
            return None
        if name_from_filename(filename) == ctx.name:
            return filename
        return os.path.join(os.path.dirname(filename), ctx.name + PROJECT_EXT)

    def adopt_filename(self, filename):
        """
        The active project now uses this file: its name becomes the file name.
        Called after an open and after a Save As.
        """
        ctx = self.active
        ctx.filename = filename
        used = [other.name for other in self.contexts if other is not ctx]
        ctx.name = unique_name(name_from_filename(filename), used)
        self.projects_changed.emit()
        self.update_title()
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_manager.py"`
Expected: `OK` (33 tests).

- [ ] **Step 5: Commit**

```bash
rtk git add appHandlers/appProjects.py tests/test_projects_manager.py
rtk git commit -m "feat(projects): add new, rename, close and the save file rules to the ProjectManager"
```

---

### Task 5: `ProjectManager`: release and restore the plots

This task fills the 5 empty methods of Task 3. These methods change the canvas, the Properties tab and the plugins.

An inactive project releases only the plot shapes of its objects. The Properties UI of each object stays. Do NOT delete it and do NOT call `set_ui()` again on activate:
- `CNCJobObject.set_ui()` sets the units from `app.app_units` and generates the G-code and `source_file` again (`appObjects/CNCJobObject.py:481` and `:588-597`). An edited G-code source would be lost.
- `set_ui()` of the Gerber, Excellon, Geometry and CNCJob objects connects object signals (for example `calculations_finished`) each time it runs. A second call makes the handlers run 2 times.

**Files:**
- Modify: `appHandlers/appProjects.py`
- Test: `tests/test_projects_manager.py` (add tests)

- [ ] **Step 1: Write the failing tests**

In `tests/test_projects_manager.py`, add this code after `TestProjectManagerLifecycle` and before `if __name__ == '__main__':`:

```python
def make_object(kind='gerber', with_ui=True):
    obj = SimpleNamespace(kind=kind, clear=Mock(), mark_shapes=Mock(), _full_plot_sig=(1, 2, 3),
                          ui=QtWidgets.QWidget() if with_ui else None, ui_type=Mock(return_value='new-ui'),
                          set_ui=Mock(), build_ui=Mock())
    return obj


class TestProjectManagerVisuals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make(self, objects):
        from appHandlers.appProjects import ProjectManager
        app = make_app(FakeCollection(objects))
        app.setup_default_properties_tab = Mock()
        app.init_tools = Mock()
        app.plot_all = Mock()
        app.plotcanvas = SimpleNamespace(redraw=Mock(), view=SimpleNamespace(camera=SimpleNamespace(rect=None)))
        app.preferencesUiManager = Mock()
        app.on_defaults2options = Mock()
        manager = ProjectManager(app, collection_factory=FakeCollection)
        return app, manager

    def test_reset_options_copies_the_project_keys_from_the_defaults(self):
        app, manager = self.make([])
        manager.reset_options()
        app.on_defaults2options.assert_called_once_with()

    def test_deactivate_releases_shapes_and_keeps_the_ui(self):
        gerber = make_object('gerber')
        script = make_object('script')
        app, manager = self.make([gerber, script])
        gerber_ui = gerber.ui

        manager.deactivate(manager.active)

        gerber.clear.assert_called_once_with(update=False)
        gerber.mark_shapes.clear.assert_called_once_with(update=False)
        self.assertIsNone(gerber._full_plot_sig)
        # the Properties UI stays; set_ui() is not safe to run again
        self.assertIs(gerber.ui, gerber_ui)
        # Script and Document objects have no shapes
        script.clear.assert_not_called()
        self.assertIsNotNone(script.ui)
        app.setup_default_properties_tab.assert_called_once_with()
        app.plotcanvas.redraw.assert_called_once_with()

    def test_activate_plots_and_does_not_rebuild_the_ui(self):
        gerber = make_object('gerber')
        app, manager = self.make([gerber])
        manager.active.view_rect = 'saved-rect'

        manager.activate(manager.active)

        gerber.ui_type.assert_not_called()
        gerber.set_ui.assert_not_called()
        gerber.build_ui.assert_not_called()
        app.init_tools.assert_called_once_with(init_tcl=False)
        app.plot_all.assert_called_once_with(fit_view=False)
        self.assertEqual(app.plotcanvas.view.camera.rect, 'saved-rect')
        # the Preferences form shows the project keys of the new active project
        app.preferencesUiManager.defaults_write_form.assert_called_once_with()

    def test_activate_of_an_empty_project_does_not_plot(self):
        app, manager = self.make([])
        manager.activate(manager.active)
        app.plot_all.assert_not_called()
        app.init_tools.assert_called_once_with(init_tcl=False)

    def test_activate_does_not_build_a_missing_ui(self):
        # an object without a UI is left as it is; set_ui() runs only when the object is made
        gerber = make_object('gerber', with_ui=False)
        app, manager = self.make([gerber])
        manager.activate(manager.active)
        gerber.set_ui.assert_not_called()

    def test_before_switch_clears_the_canvas_helpers(self):
        app, manager = self.make([])
        app.call_source = 'app'
        app.tool_shapes = Mock()
        app.hover_shapes = Mock()
        app.exc_areas = Mock()
        app.delete_selection_shape = Mock()

        manager.before_switch()

        app.tool_shapes.clear.assert_called_once_with(update=True)
        app.hover_shapes.clear.assert_called_once_with(update=True)
        app.exc_areas.clear_shapes.assert_called_once_with()
        app.delete_selection_shape.assert_called_once_with()

    def test_before_switch_never_closes_an_editor(self):
        # a switch is refused while an editor is open (is_busy); before_switch must not drop editor changes
        app, manager = self.make([])
        app.call_source = 'app'
        app.on_editing_finished = Mock()
        app.tool_shapes = None
        app.hover_shapes = None
        app.exc_areas = None
        app.delete_selection_shape = Mock()
        manager.before_switch()
        app.on_editing_finished.assert_not_called()
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_manager.py"`
Expected: 5 failures in `TestProjectManagerVisuals` (the methods are still empty). `test_activate_does_not_build_a_missing_ui` and `test_before_switch_never_closes_an_editor` pass already.

- [ ] **Step 3: Replace the empty methods in `appHandlers/appProjects.py`**

Replace this whole block (from the comment to the end of `_get_view_rect`):

```python
    # ------------------------------------------------------------------------------------------------------------
    # Steps that change the GUI. Task 5 fills them.
    # ------------------------------------------------------------------------------------------------------------
    def reset_options(self):
        pass

    def before_switch(self):
        pass

    def deactivate(self, ctx):
        pass

    def activate(self, ctx):
        pass

    def _get_view_rect(self):
        return None
```

with this block:

```python
    # ------------------------------------------------------------------------------------------------------------
    # Steps that change the GUI
    # ------------------------------------------------------------------------------------------------------------
    # these object kinds have no shapes on the canvas
    NO_SHAPES_KINDS = ('script', 'document')

    def reset_options(self):
        """
        A new project copies the project keys from the application defaults. The application settings are the
        same for all projects, so they do not change.
        """
        self.app.on_defaults2options()

    def before_switch(self):
        """
        Remove the canvas helpers of the current project. A switch never runs while an editor is open (is_busy),
        so this method does not close an editor.
        """
        app = self.app
        for attr in ('tool_shapes', 'hover_shapes'):
            shapes = getattr(app, attr, None)
            if shapes is not None:
                try:
                    shapes.clear(update=True)
                except Exception as err:
                    app.log.error("ProjectManager.before_switch() %s --> %s" % (attr, str(err)))

        try:
            app.levelling_tool.probing_shapes.clear(update=True)
        except AttributeError:
            pass

        if getattr(app, 'exc_areas', None) is not None:
            app.exc_areas.clear_shapes()

        app.delete_selection_shape()

    def deactivate(self, ctx):
        """
        Release the plot shapes of the objects of a project. The geometry and the Properties UI stay.
        """
        # the Properties tab can show the UI of an object of this project; replace it first
        self.app.setup_default_properties_tab()

        for obj in ctx.collection.get_list():
            if obj.kind in self.NO_SHAPES_KINDS:
                continue
            try:
                obj.clear(update=False)
            except Exception as err:
                self.app.log.error("ProjectManager.deactivate() --> %s" % str(err))
            try:
                obj.mark_shapes.clear(update=False)
            except AttributeError:
                pass
            # forces a full plot when the project is active again
            obj._full_plot_sig = None

        self.app.plotcanvas.redraw()

    def activate(self, ctx):
        """
        Re-create the plugins for the new collection and plot. The Properties UI of the objects is not built again:
        set_ui() changes the data of a CNCJob and connects the object signals again.
        """
        app = self.app
        app.setup_default_properties_tab()

        # show the project keys of this project in the Preferences form
        app.preferencesUiManager.defaults_write_form()

        # the plugin comboboxes hold the model of the old collection; File -> New Project also does this
        app.init_tools(init_tcl=False)

        if ctx.collection.get_list():
            app.plot_all(fit_view=False)
        self._set_view_rect(ctx.view_rect)

    def _get_view_rect(self):
        try:
            from vispy.geometry import Rect
            return Rect(self.app.plotcanvas.view.camera.rect)
        except Exception:
            return None

    def _set_view_rect(self, rect):
        if rect is None:
            return
        try:
            self.app.plotcanvas.view.camera.rect = rect
        except Exception as err:
            self.app.log.error("ProjectManager._set_view_rect() --> %s" % str(err))
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_manager.py"`
Expected: `OK` (40 tests). The tests of Tasks 3 and 4 still pass because they replace these methods with `Mock`.

- [ ] **Step 5: Commit**

```bash
rtk git add appHandlers/appProjects.py tests/test_projects_manager.py
rtk git commit -m "feat(projects): release the plot shapes of an inactive project"
```

---

### Task 6: `ProjectManager`: dialogs, open, close request and save

This task adds the methods that show dialogs. Each dialog is 1 method, so a test can replace it with a `Mock`.

It also makes `appIO.save_project()` return `True` after a confirmed save and `False` after a failed save. Today it returns `None` in both cases. A close or an exit must not continue after a failed save.

**Files:**
- Modify: `appHandlers/appProjects.py`
- Modify: `appHandlers/appIO.py`, method `save_project`
- Test: `tests/test_projects_manager.py` (add tests)
- Test: `tests/test_unify_characterization.py` (add 1 test)

- [ ] **Step 0a: Write the failing test of `save_project`**

In `tests/test_unify_characterization.py`, add this test after the function `test_saved_project_has_only_project_options`:

```python


def test_save_project_reports_success_and_failure(tmp_path):
    app = make_app()
    io = appIO(app)
    app.collection.get_list.return_value = []
    app.collection.get_active.return_value = None
    # a real failure: the folder does not exist, so open() fails
    assert io.save_project(str(tmp_path / 'missing' / 'bad.FlatPrj'), silent=True) is False
    assert app.save_in_progress is False
    assert io.save_project(str(tmp_path / 'good.FlatPrj'), silent=True) is True


def test_save_project_object_serialization_error_is_a_failure(tmp_path):
    app = make_app()
    io = appIO(app)
    app.collection.get_list.return_value = [SimpleNamespace(to_dict=Mock(side_effect=ValueError('bad object')))]
    app.collection.get_active.return_value = None
    path = tmp_path / 'bad_object.FlatPrj'
    assert io.save_project(str(path), silent=True) is False
    assert app.save_in_progress is False
    assert not path.exists()


def test_save_project_close_error_is_a_failure(tmp_path):
    import io as stdio

    class FailingClose(stdio.StringIO):
        def close(self):
            raise OSError('disk full')

    app = make_app()
    io = appIO(app)
    app.collection.get_list.return_value = []
    app.collection.get_active.return_value = None
    with patch('appHandlers.appIO.open', create=True, return_value=FailingClose()):
        assert io.save_project(str(tmp_path / 'full.FlatPrj'), silent=True) is False
    assert app.save_in_progress is False


def test_save_project_checked_never_raises(tmp_path):
    app = make_app()
    io = appIO(app)
    app.save_in_progress = True
    with patch.object(appIO, 'save_project', side_effect=RuntimeError('boom')):
        assert io.save_project_checked(str(tmp_path / 'x.FlatPrj'), silent=True) is False
    assert app.save_in_progress is False
    with patch.object(appIO, 'save_project', return_value=True):
        assert io.save_project_checked(str(tmp_path / 'x.FlatPrj'), silent=True) is True
```

`tests/test_unify_characterization.py` already imports `SimpleNamespace`, `Mock` and `patch`. If one of them is missing, add it to the existing import line.

Run: `.venv/Scripts/python.exe -m pytest tests/test_unify_characterization.py -q -k "reports_success or serialization_error or close_error or checked_never_raises"`
Expected: 4 failures. The first shows `assert None is False`. The serialization and close tests show an exception that escapes (`ValueError: bad object`, `OSError: disk full`). The last shows `AttributeError: 'appIO' object has no attribute 'save_project_checked'`.

- [ ] **Step 0b: Make `save_project` return the result**

In `appHandlers/appIO.py`, in `save_project`:

1. In the 2 blocks that end with these lines (the serialize failure and the compression failure of the compressed branch):

```python
                        self.app.save_in_progress = False
                        return
```

and

```python
                    self.app.save_in_progress = False
                    return
```

   change each `return` to `return False`. Do this for each `return` in the method that comes after `self.app.save_in_progress = False`.

2. Replace the whole part from the line `                if project_zipped != b'':` to the line `            self.app.start_delayed_quit(delay=500, filename=filename, should_quit=quit_action)` (the end of the method) with:

```python
                if project_zipped == b'':
                    self.log.error("Failed to save file: %s. Empty binary file.", str(filename))
                    self.inform.emit('[ERROR_NOTCL] %s' % _("Failed."))
                    self.app.save_in_progress = False
                    return False
                try:
                    with open(filename, "wb") as f_to_write:
                        f_to_write.write(project_zipped)
                except IOError:
                    self.log.error("Failed to open file for saving: %s", str(filename))
                    self.inform.emit('[ERROR_NOTCL] %s' % _("The object is used by another application."))
                    self.app.save_in_progress = False
                    return False

                self.inform.emit('[success] %s: %s' % (_("Project saved to"), str(filename)))
            else:
                # Open file
                try:
                    f = open(filename, 'w')
                except IOError:
                    self.log.error("Failed to open file for saving: %s", str(filename))
                    self.inform.emit('[ERROR_NOTCL] %s' % _("The object is used by another application."))
                    self.app.save_in_progress = False
                    return False

                # Write
                try:
                    json.dump(d, f, default=to_dict, indent=2, sort_keys=True)
                except Exception as e:
                    self.log.error(
                        "Failed to serialize file: %s because: %s" % (str(filename), str(e)))
                    self.inform.emit('[ERROR_NOTCL] %s' % _("Failed."))
                    f.close()
                    self.app.save_in_progress = False
                    return False
                # a buffered write can fail only when it is flushed, in close()
                try:
                    f.close()
                except Exception as e:
                    self.log.error("Failed to write file: %s because: %s" % (str(filename), str(e)))
                    self.inform.emit('[ERROR_NOTCL] %s' % _("Failed."))
                    self.app.save_in_progress = False
                    return False

                # verification of the saved project: open and parse it
                try:
                    with open(filename, 'r') as saved_f:
                        saved_d = json.load(saved_f, object_hook=dict2obj)
                except Exception:
                    saved_d = None
                if not saved_d or 'version' not in saved_d:
                    if silent is False:
                        self.inform.emit('[ERROR_NOTCL] %s: %s %s' %
                                         (_("Failed to parse saved project file"),
                                          str(filename),
                                          _("Retry to save it.")))  # noqa
                    self.app.save_in_progress = False
                    return False

                if silent is False:
                    self.inform.emit('[success] %s: %s' % (_("Project saved to"), str(filename)))

            # if quit:
            # t = threading.Thread(target=lambda: self.check_project_file_size(1, filename=filename))
            # t.start()
            self.app.start_delayed_quit(delay=500, filename=filename, should_quit=quit_action)
            return True
```

3. Change the docstring line `:return:                None` of `save_project` to `:return:                True if the file is written and verified, else False`.

4. An object that can not be serialized must not raise out of `save_project`. Find:

```python
            d = {
                "objs":             [obj.to_dict() for obj in self.app.collection.get_list()],
                "options":          app_options,
                "version":          self.app.version
            }
```

Replace it with:

```python
            try:
                objs = [obj.to_dict() for obj in self.app.collection.get_list()]
            except Exception as e:
                self.log.error("Failed to serialize the objects for: %s because: %s" % (str(filename), str(e)))
                self.inform.emit('[ERROR_NOTCL] %s' % _("Failed."))
                self.app.save_in_progress = False
                return False
            d = {
                "objs":             objs,
                "options":          app_options,
                "version":          self.app.version
            }
```

5. After the method `save_project`, add this method. Every save of a project that needs the result uses it (`ProjectManager.save_context` in this task, File > Save and Save As in Task 10):

```python
    def save_project_checked(self, filename, quit_action=False, silent=False):
        """
        Run save_project() and return True only after a written and verified file. It never raises: an
        unexpected error is logged, the save state is reset and the result is False.
        """
        try:
            return self.save_project(filename, quit_action=quit_action, silent=silent) is True
        except Exception as err:
            self.log.error("appIO.save_project_checked() --> %s" % str(err))
            self.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Failed to save the project"), str(filename)))
            self.app.save_in_progress = False
            return False
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_unify_characterization.py -q`
Expected: all pass.

- [ ] **Step 1: Write the failing tests**

In `tests/test_projects_manager.py`, add this class after `TestProjectManagerVisuals` and before `if __name__ == '__main__':`:

```python
class TestProjectManagerDialogs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def path(self, name):
        return os.path.join(self.directory.name, name)

    def test_prepare_open_reuses_an_empty_active_project(self):
        app, manager = make_manager()
        self.assertTrue(manager.prepare_open(self.path('Board.FlatPrj')))
        self.assertEqual(len(manager.contexts), 1)

    def test_prepare_open_adds_a_project(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        self.assertTrue(manager.prepare_open(self.path('Board.FlatPrj')))
        self.assertEqual(len(manager.contexts), 2)
        self.assertIs(manager.active, manager.contexts[1])

    def test_prepare_open_of_an_open_file_yes_reloads(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        first = manager.active
        app.project_filename = self.path('Board.FlatPrj')
        manager.new()
        manager.ask_yes_no = Mock(return_value=True)
        self.assertTrue(manager.prepare_open(self.path('Board.FlatPrj')))
        self.assertIs(manager.active, first)
        manager.ask_yes_no.assert_called_once()

    def test_prepare_open_of_an_open_file_no_only_switches(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        first = manager.active
        app.project_filename = self.path('Board.FlatPrj')
        manager.new()
        manager.ask_yes_no = Mock(return_value=False)
        self.assertFalse(manager.prepare_open(self.path('Board.FlatPrj')))
        self.assertIs(manager.active, first)

    def test_prepare_open_is_refused_while_busy(self):
        app, manager = make_manager()
        app.save_in_progress = True
        self.assertFalse(manager.prepare_open(self.path('Board.FlatPrj')))

    def test_request_close_cancel(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        app.should_we_save = True
        manager.ask_save = Mock(return_value='cancel')
        self.assertFalse(manager.request_close(manager.active))
        self.assertEqual(len(manager.contexts), 1)
        self.assertEqual(manager.active.name, 'Project_1')

    def test_request_close_no_discards(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        first = manager.active
        app.should_we_save = True
        manager.ask_save = Mock(return_value='no')
        self.assertTrue(manager.request_close(first))
        self.assertNotIn(first, manager.contexts)

    def test_request_close_yes_saves_first(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        first = manager.active
        app.should_we_save = True
        manager.ask_save = Mock(return_value='yes')
        manager.save_context = Mock(return_value=True)
        self.assertTrue(manager.request_close(first))
        manager.save_context.assert_called_once_with(first)

    def test_save_context_writes_the_target_file(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        app.project_filename = self.path('Project_1.FlatPrj')
        app.should_we_save = True
        app.f_handlers = SimpleNamespace(save_project_checked=Mock(return_value=True))
        manager.rename(manager.active, 'Board_B')

        self.assertTrue(manager.save_context(manager.active))

        target = self.path('Board_B.FlatPrj')
        app.f_handlers.save_project_checked.assert_called_once_with(target, silent=True)
        self.assertEqual(app.project_filename, target)
        self.assertFalse(app.should_we_save)
        self.assertFalse(app.save_in_progress)

    def test_save_context_asks_before_it_overwrites(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        app.project_filename = self.path('Project_1.FlatPrj')
        app.f_handlers = SimpleNamespace(save_project_checked=Mock(return_value=True))
        manager.rename(manager.active, 'Board_B')
        with open(self.path('Board_B.FlatPrj'), 'w') as stream:
            stream.write('x')
        manager.ask_yes_no = Mock(return_value=False)

        self.assertFalse(manager.save_context(manager.active))
        app.f_handlers.save_project_checked.assert_not_called()

    def test_save_context_without_file_asks_for_a_path(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        app.f_handlers = SimpleNamespace(save_project_checked=Mock(return_value=True))
        manager.ask_save_path = Mock(return_value=self.path('Chosen.FlatPrj'))

        self.assertTrue(manager.save_context(manager.active))

        app.f_handlers.save_project_checked.assert_called_once_with(self.path('Chosen.FlatPrj'), silent=True)
        self.assertEqual(manager.active.name, 'Chosen')

    def test_save_context_without_file_cancelled(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        app.f_handlers = SimpleNamespace(save_project_checked=Mock(return_value=True))
        manager.ask_save_path = Mock(return_value='')
        self.assertFalse(manager.save_context(manager.active))
        app.f_handlers.save_project_checked.assert_not_called()

    def test_save_context_failure_keeps_the_project_dirty(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        app.project_filename = self.path('Project_1.FlatPrj')
        app.should_we_save = True
        app.f_handlers = SimpleNamespace(save_project_checked=Mock(return_value=False))
        manager.rename(manager.active, 'Board_B')

        self.assertFalse(manager.save_context(manager.active))

        self.assertTrue(app.should_we_save)
        self.assertEqual(app.project_filename, self.path('Project_1.FlatPrj'))
        self.assertFalse(app.save_in_progress)

    def test_request_close_stops_when_the_save_fails(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        first = manager.active
        app.project_filename = self.path('Project_1.FlatPrj')
        app.should_we_save = True
        app.f_handlers = SimpleNamespace(save_project_checked=Mock(return_value=False))
        manager.ask_save = Mock(return_value='yes')

        self.assertFalse(manager.request_close(first))

        self.assertIn(first, manager.contexts)
        self.assertTrue(app.should_we_save)

    def test_save_context_of_the_active_project_waits_for_a_pending_save(self):
        # switch() returns at once for the active project, so save_context() must check the pending save itself
        app, manager = make_manager(make_app(FakeCollection([object()])))
        app.project_filename = self.path('Project_1.FlatPrj')
        app.should_we_save = True
        app.project_save_pending = True
        app.f_handlers = SimpleNamespace(save_project_checked=Mock(return_value=True))

        self.assertFalse(manager.save_context(manager.active))

        app.f_handlers.save_project_checked.assert_not_called()
        self.assertTrue(app.should_we_save)
        app.inform.emit.assert_called_once()

    def test_request_close_blocks_the_autosave_during_the_dialogs(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        app.should_we_save = True
        app.block_autosave = False
        seen = []

        def answer(ctx):
            # the dialog runs a nested event loop; the autosave timer can fire there
            seen.append(app.block_autosave)
            return 'cancel'

        manager.ask_save = Mock(side_effect=answer)

        self.assertFalse(manager.request_close(manager.active))

        self.assertEqual(seen, [True])
        # the cancel restores the old state of the autosave
        self.assertFalse(app.block_autosave)

    def test_return_to_restores_the_live_state_also_when_busy(self):
        app, manager = make_manager()
        first = manager.active
        second = manager.add_context('Board_B')
        self.assertTrue(manager.switch(second, visuals=False))
        app.workers.pending_count.return_value = 1

        manager.return_to(first)

        self.assertIs(manager.active, first)
        self.assertIs(app.collection, first.collection)
        self.assertIs(manager.stack.currentWidget(), first.collection.view)
        self.assertIs(manager.displayed, first)
        # the canvas did not change: no visual step runs
        manager.activate.assert_not_called()
        manager.deactivate.assert_not_called()
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_manager.py"`
Expected: errors such as `AttributeError: 'ProjectManager' object has no attribute 'prepare_open'`.

- [ ] **Step 3: Add the methods to `appHandlers/appProjects.py`**

Add this block at the end of the class `ProjectManager` (after `_set_view_rect`):

```python
    # ------------------------------------------------------------------------------------------------------------
    # Dialogs. Each dialog is 1 method so a test can replace it.
    # ------------------------------------------------------------------------------------------------------------
    def ask_yes_no(self, title, text):
        from PyQt6 import QtGui
        from appGUI.GUIElements import FCMessageBox

        msgbox = FCMessageBox(parent=self.app.ui)
        msgbox.setWindowTitle(title)
        msgbox.setWindowIcon(QtGui.QIcon(self.app.resource_location + '/app128.png'))
        msgbox.setText('<b>%s</b>' % title)
        msgbox.setInformativeText(text)
        msgbox.setIcon(QtWidgets.QMessageBox.Icon.Question)
        bt_yes = msgbox.addButton(_('Yes'), QtWidgets.QMessageBox.ButtonRole.YesRole)
        msgbox.addButton(_('No'), QtWidgets.QMessageBox.ButtonRole.NoRole)
        msgbox.setDefaultButton(bt_yes)
        msgbox.exec()
        return msgbox.clickedButton() == bt_yes

    def ask_save(self, ctx):
        """
        :return:    'yes', 'no' or 'cancel'
        """
        from PyQt6 import QtGui
        from appGUI.GUIElements import FCMessageBox

        title = _("Save changes")
        msgbox = FCMessageBox(parent=self.app.ui)
        msgbox.setWindowTitle(title)
        msgbox.setWindowIcon(QtGui.QIcon(self.app.resource_location + '/app128.png'))
        msgbox.setText('<b>%s</b>' % title)
        msgbox.setInformativeText('%s: %s\n%s' % (_("The project has changes"), ctx.name,
                                                  _("Do you want to Save the project?")))
        msgbox.setIconPixmap(QtGui.QPixmap(self.app.resource_location + '/save_as.png'))
        bt_yes = msgbox.addButton(_('Yes'), QtWidgets.QMessageBox.ButtonRole.YesRole)
        bt_no = msgbox.addButton(_('No'), QtWidgets.QMessageBox.ButtonRole.NoRole)
        msgbox.addButton(_('Cancel'), QtWidgets.QMessageBox.ButtonRole.RejectRole)
        msgbox.setDefaultButton(bt_yes)
        msgbox.exec()
        response = msgbox.clickedButton()
        if response == bt_yes:
            return 'yes'
        if response == bt_no:
            return 'no'
        return 'cancel'

    def ask_save_path(self, ctx):
        """
        :return:    the chosen path, or '' if the user cancels
        """
        from appGUI.GUIElements import FCFileSaveDialog

        filename, _f = FCFileSaveDialog.get_saved_filename(
            caption=_("Save Project As ..."),
            directory='%s/%s' % (str(self.app.get_last_save_folder()), ctx.name),
            ext_filter="FlatCAM Project .FlatPrj (*.FlatPrj);; All Files (*.*)")
        return str(filename)

    def hold_autosave(self):
        """
        Stop the autosave until release_autosave(). A dialog runs a nested event loop: the autosave timer can fire
        in it and start a second save.

        :return:    the old state, for release_autosave()
        """
        previous = getattr(self.app, 'block_autosave', False)
        self.app.block_autosave = True
        return previous

    def release_autosave(self, previous):
        self.app.block_autosave = previous

    def return_to(self, ctx):
        """
        Make ctx the active project again after an exit that stops. The save of an inactive project during the exit
        makes it active with switch(visuals=False), so the canvas and the plugins still show ctx. This method puts
        the live state back to ctx, the same as switch(ctx, visuals=False). It does not check is_busy(): the exit
        stops in all cases, and the live collection must be the one that the canvas shows.
        """
        if ctx is self.active or ctx not in self.contexts:
            return
        self.capture()
        self.active = ctx
        self._load(ctx)
        self.projects_changed.emit()
        self.update_title()

    # ------------------------------------------------------------------------------------------------------------
    # Open, close request, save
    # ------------------------------------------------------------------------------------------------------------
    def prepare_open(self, filename):
        """
        Called before a project file is loaded from the GUI. It selects the project that receives the file.

        :return:    True if the load must continue. False if the load must stop.
        """
        if self.is_busy():
            self.inform_busy()
            return False

        existing = self.find_by_filename(filename)
        if existing is not None:
            reload_file = self.ask_yes_no(
                _("Project already open"),
                '%s: %s\n%s' % (_("This project is already open"), existing.name,
                                _("Do you want to overwrite it with the version from the file?")))
            if not self.switch(existing):
                return False
            return reload_file

        # an empty project that was never saved receives the file; no new entry is needed
        active = self.active
        if not active.collection.get_list() and not self.app.project_filename and not self.app.should_we_save:
            return True

        return self.new() is not None

    def request_close(self, ctx):
        """
        Close a project from the GUI. If it has unsaved changes, ask the user first.

        :return:    True if the project is removed
        """
        if self.is_busy():
            self.inform_busy()
            return False
        if self.is_dirty(ctx):
            # the dialogs run a nested event loop; the autosave timer must not start a save during them
            autosave_state = self.hold_autosave()
            try:
                answer = self.ask_save(ctx)
                if answer == 'cancel':
                    return False
                if answer == 'yes' and not self.save_context(ctx):
                    return False
            finally:
                self.release_autosave(autosave_state)
        return self.close(ctx, force=True)

    def save_context(self, ctx, visuals=True):
        """
        Save a project now, in this thread. If the project is not active, it becomes active first.

        :return:    True if the file is written
        """
        # switch() returns at once for the active project and skips its busy check; a pending save (for example an
        # autosave) must end first, else 2 saves overlap
        if self.is_busy():
            self.inform_busy()
            return False
        if not self.switch(ctx, visuals=visuals):
            return False

        path = self.save_target(ctx)
        if path is None:
            path = self.ask_save_path(ctx)
            if not path:
                return False
        elif os.path.exists(path) and not same_path(path, self.app.project_filename):
            if not self.ask_yes_no(_("Overwrite"),
                                   '%s: %s\n%s' % (_("The file already exists"), path,
                                                   _("Do you want to overwrite it?"))):
                return False

        if not self.app.f_handlers.save_project_checked(path, silent=True):
            # the save failed: the project keeps its file name and its unsaved changes
            self.app.save_in_progress = False
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("The project was not saved"), path))
            return False
        # save_project() starts a timer that resets this flag later; the save is already done here
        self.app.save_in_progress = False
        timer = getattr(self.app, 'save_timer', None)
        if timer is not None:
            timer.stop()

        self.app.project_filename = path
        self.adopt_filename(path)
        self.app.should_we_save = False
        return True
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_manager.py"`
Expected: `OK` (57 tests).

- [ ] **Step 5: Commit**

```bash
rtk git add appHandlers/appProjects.py appHandlers/appIO.py tests/test_projects_manager.py tests/test_unify_characterization.py
rtk git commit -m "feat(projects): add the open, close and save dialogs of the ProjectManager"
```

---

### Task 7: The title bar shows the active project name

**Files:**
- Modify: `appGUI/MainGUI.py`, method `set_ui_title` (about line 2276)
- Test: `tests/test_projects_manager.py` (add tests)

- [ ] **Step 1: Write the failing test**

In `tests/test_projects_manager.py`, add this class before `if __name__ == '__main__':`:

```python
class TestTitleShowsProjectName(unittest.TestCase):
    def make_window(self, filename=None):
        return SimpleNamespace(
            title_bar=SimpleNamespace(project_title=None, update_title=Mock()), setWindowTitle=Mock(),
            app=SimpleNamespace(projects=SimpleNamespace(active=SimpleNamespace(name='Board_A')),
                                project_filename=filename, version='9.0', beta=False))

    def test_filename_is_replaced_by_the_project_name(self):
        from appGUI.MainGUI import MainGUI
        window = self.make_window(filename='C:/x/Board_A.FlatPrj')
        MainGUI.set_ui_title(window, name='C:/x/Board_A.FlatPrj')
        self.assertEqual(window.title_bar.project_title, 'Board_A')

    def test_empty_name_is_replaced_by_the_project_name(self):
        from appGUI.MainGUI import MainGUI
        window = self.make_window()
        MainGUI.set_ui_title(window, name=None)
        self.assertEqual(window.title_bar.project_title, 'Board_A')

    def test_other_text_is_kept(self):
        from appGUI.MainGUI import MainGUI
        window = self.make_window()
        MainGUI.set_ui_title(window, name='Loading Project ... Please Wait ...')
        self.assertEqual(window.title_bar.project_title, 'Loading Project ... Please Wait ...')
```

- [ ] **Step 2: Run the test and see it fail**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_manager.py"`
Expected: 2 failures: `'C:/x/Board_A.FlatPrj' != 'Board_A'` and `'Untitled' != 'Board_A'`.

- [ ] **Step 3: Change `MainGUI.set_ui_title`**

In `appGUI/MainGUI.py`, find this code in `set_ui_title`:

```python
        :param name: String that store the project path and project name
        :return: None
        """
        if self.title_bar is None:
```

Replace it with:

```python
        :param name: String that store the project path and project name
        :return: None
        """
        # the title shows the name of the active project instead of its file path
        projects = getattr(self.app, 'projects', None)
        if projects is not None and (not name or name == self.app.project_filename or
                                     name == _("New Project - Not saved")):
            name = projects.active.name

        if self.title_bar is None:
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_manager.py"`
Expected: `OK` (60 tests).

Also run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_titlebar.py"`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
rtk git add appGUI/MainGUI.py tests/test_projects_manager.py
rtk git commit -m "feat(projects): the title bar shows the name of the active project"
```

---

### Task 8: `ProjectSelector` widget and the App wiring

**Files:**
- Create: `appGUI/ProjectSelector.py`
- Modify: `appMain.py` (about line 1129, block `SETUP OBJECT COLLECTION`)
- Test: `tests/test_project_selector.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_project_selector.py`:

```python
"""Tests for the Project combobox above the Project tab tree."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6 import QtCore, QtWidgets


class FakeManager(QtCore.QObject):
    projects_changed = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.contexts = [SimpleNamespace(name='Board_A'), SimpleNamespace(name='Board_B')]
        self.active = self.contexts[0]
        self.app = SimpleNamespace(inform=Mock(), f_handlers=SimpleNamespace(on_file_open_project=Mock()))
        self.busy = False
        self.switch = Mock(side_effect=self._switch)
        self.new = Mock()
        self.rename = Mock(return_value=True)
        self.request_close = Mock()

    def _switch(self, ctx):
        self.active = ctx
        return True

    def names(self):
        return [ctx.name for ctx in self.contexts]

    def is_busy(self):
        return self.busy

    def inform_busy(self):
        self.app.inform.emit('busy')


class TestProjectSelector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make(self):
        from appGUI.ProjectSelector import ProjectSelector
        manager = FakeManager()
        return manager, ProjectSelector(manager)

    def test_combobox_lists_the_projects(self):
        manager, selector = self.make()
        self.assertEqual([selector.combo.itemText(i) for i in range(selector.combo.count())],
                         ['Board_A', 'Board_B'])
        self.assertEqual(selector.combo.currentIndex(), 0)

    def test_refresh_follows_the_manager(self):
        manager, selector = self.make()
        manager.active = manager.contexts[1]
        manager.projects_changed.emit()
        self.assertEqual(selector.combo.currentIndex(), 1)

    def test_activated_switches(self):
        manager, selector = self.make()
        selector.on_activated(1)
        manager.switch.assert_called_once_with(manager.contexts[1])
        self.assertEqual(selector.combo.currentIndex(), 1)

    def test_menu_has_the_4_commands(self):
        manager, selector = self.make()
        menu = selector.build_menu()
        self.assertEqual([action.text() for action in menu.actions()],
                         ['New Project', 'Open Project...', 'Rename Project...', 'Close Project'])

    def test_menu_actions_call_the_manager(self):
        manager, selector = self.make()
        menu = selector.build_menu()
        actions = menu.actions()
        actions[0].trigger()
        manager.new.assert_called_once_with()
        actions[1].trigger()
        manager.app.f_handlers.on_file_open_project.assert_called_once_with()
        actions[3].trigger()
        manager.request_close.assert_called_once_with(manager.active)

    def test_rename_uses_the_input_dialog(self):
        manager, selector = self.make()
        with patch.object(QtWidgets.QInputDialog, 'getText', return_value=('Board_C', True)):
            selector.on_rename()
        manager.rename.assert_called_once_with(manager.active, 'Board_C')

    def test_rename_refused_shows_a_message(self):
        manager, selector = self.make()
        manager.rename.return_value = False
        with patch.object(QtWidgets.QInputDialog, 'getText', return_value=('Board_B', True)):
            selector.on_rename()
        manager.app.inform.emit.assert_called()

    def test_menu_is_not_shown_while_busy(self):
        manager, selector = self.make()
        manager.busy = True
        selector.build_menu = Mock()
        selector.on_menu_request(QtCore.QPoint(0, 0))
        selector.build_menu.assert_not_called()
        manager.app.inform.emit.assert_called_once_with('busy')


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run the test and see it fail**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_project_selector.py"`
Expected: `ModuleNotFoundError: No module named 'appGUI.ProjectSelector'`.

- [ ] **Step 3: Write `appGUI/ProjectSelector.py`**

```python
from PyQt6 import QtCore, QtWidgets

# App Translation
import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class ProjectCombo(QtWidgets.QComboBox):
    """
    A combobox that does not open while a background task runs.
    """

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager

    def showPopup(self):
        if self.manager.is_busy():
            self.manager.inform_busy()
            return
        super().showPopup()


class ProjectSelector(QtWidgets.QWidget):
    """
    The 'Project:' label and combobox above the Project tab tree. A right-click on the combobox opens the
    project commands.
    """

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QtWidgets.QLabel('%s:' % _("Project"))
        self.combo = ProjectCombo(manager)
        self.combo.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.combo.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)

        layout.addWidget(self.label)
        layout.addWidget(self.combo, stretch=1)

        self.combo.activated.connect(self.on_activated)
        self.combo.customContextMenuRequested.connect(self.on_menu_request)
        self.manager.projects_changed.connect(self.refresh)

        self.refresh()

    def refresh(self):
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(self.manager.names())
        self.combo.setCurrentIndex(self.manager.contexts.index(self.manager.active))
        self.combo.blockSignals(False)

    def on_activated(self, index):
        if 0 <= index < len(self.manager.contexts):
            self.manager.switch(self.manager.contexts[index])
        # if the switch is refused, show the active project again
        self.refresh()

    def build_menu(self):
        menu = QtWidgets.QMenu(self)
        new_action = menu.addAction(_("New Project"))
        open_action = menu.addAction(_("Open Project..."))
        rename_action = menu.addAction(_("Rename Project..."))
        close_action = menu.addAction(_("Close Project"))

        new_action.triggered.connect(lambda: self.manager.new())
        open_action.triggered.connect(lambda: self.manager.app.f_handlers.on_file_open_project())
        rename_action.triggered.connect(self.on_rename)
        close_action.triggered.connect(lambda: self.manager.request_close(self.manager.active))
        return menu

    def on_menu_request(self, pos):
        if self.manager.is_busy():
            self.manager.inform_busy()
            return
        menu = self.build_menu()
        menu.exec(self.combo.mapToGlobal(pos))

    def on_rename(self):
        ctx = self.manager.active
        name, ok = QtWidgets.QInputDialog.getText(self, _("Rename Project"), _("New name:"), text=ctx.name)
        if not ok:
            return
        if not self.manager.rename(ctx, name):
            self.manager.app.inform.emit('[ERROR_NOTCL] %s' %
                                         _("The name is empty, not valid or used by another project."))
```

- [ ] **Step 4: Run the test and see it pass**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_project_selector.py"`
Expected: `OK` (8 tests).

- [ ] **Step 5: Wire the manager and the selector into `appMain.py`**

Find this block in `App.__init__` (about line 1129):

```python
        # #################################### SETUP OBJECT COLLECTION ##############################################
        self.collection = ObjectCollection(app=self)
        self.ui.project_tab_layout.addWidget(self.collection.view)

        self.app_obj = AppObject(app=self)

        # ### Adjust tabs width ## ##
        # self.collection.view.setMinimumWidth(self.ui.options_scroll_area.widget().sizeHint().width() +
        #     self.ui.options_scroll_area.verticalScrollBar().sizeHint().width())
        self.collection.view.setMinimumWidth(290)
        self.log.debug("Finished creating Object Collection.")
```

Replace it with:

```python
        # #################################### SETUP OBJECT COLLECTION ##############################################
        self.collection = ObjectCollection(app=self)
        # ### Adjust tabs width ## ##
        self.collection.view.setMinimumWidth(290)

        # the Project tab can hold more than 1 project; the manager keeps app.collection on the active one
        self.projects = ProjectManager(app=self)
        self.project_selector = ProjectSelector(self.projects)
        self.ui.project_tab_layout.addWidget(self.project_selector)
        self.ui.project_tab_layout.addWidget(self.projects.stack)

        self.app_obj = AppObject(app=self)

        self.log.debug("Finished creating Object Collection.")
```

At the top of `appMain.py`, find the import line of `ObjectCollection` (search for `import ObjectCollection` or `from appObjects.ObjectCollection import`). Directly after that line, add:

```python
from appHandlers.appProjects import ProjectManager
from appGUI.ProjectSelector import ProjectSelector
```

- [ ] **Step 6: Check that the app starts**

Run: `.venv/Scripts/python.exe -c "import appMain"`
Expected: no output, no error.

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_app_refactor_integration.py"`
Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
rtk git add appGUI/ProjectSelector.py appMain.py tests/test_project_selector.py
rtk git commit -m "feat(projects): add the Project combobox above the Project tab tree"
```

---

### Task 9: File > New Project and File > Open Project add a project

**Files:**
- Modify: `appHandlers/appIO.py`: `on_file_new_click` (about line 1066), `_open_project` (about line 2839), `_restore_project_handler` (about line 2933)
- Test: `tests/test_projects_appio.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_projects_appio.py`:

```python
"""appIO follows the multiple projects rules: New, Open, Save and Save As."""

import os
import tempfile
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6 import QtCore, QtWidgets

from appHandlers.appIO import appIO
from defaults import AppOptions


class ProjectSignals(QtCore.QObject):
    new_project = QtCore.pyqtSignal()
    restore = QtCore.pyqtSignal(object, str, bool, bool, bool, bool)
    objects = QtCore.pyqtSignal(object, str, bool, bool)


class Defaults(dict):
    # on_file_save_project_as() reads app.defaults.factory_defaults
    factory_defaults = {}


class AppIOTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.window = QtWidgets.QWidget()
        self.addCleanup(self.window.close)
        self.window.set_ui_title = Mock()
        self.signals = ProjectSignals()
        self.tasks = []
        self.projects = Mock()
        defaults = Defaults()
        self.app = SimpleNamespace(
            log=Mock(), inform=Mock(), splash=Mock(), defaults=defaults, app_units='MM',
            options=AppOptions(version='test', baseline={}, defaults=defaults), preferencesUiManager=Mock(),
            ui=self.window, new_project_signal=self.signals.new_project,
            restore_project=self.signals.restore, restore_project_objects_sig=self.signals.objects,
            worker_task=SimpleNamespace(emit=self.tasks.append),
            proc_container=SimpleNamespace(new=lambda text: nullcontext()),
            block_autosave=False, project_filename=None, resource_location='assets/resources',
            app_obj=SimpleNamespace(load_batches=set()), projects=self.projects,
            file_opened=Mock(), file_saved=Mock(), should_we_save=True,
            get_last_save_folder=Mock(return_value=self.directory.name))
        self.io = appIO(self.app)

    def path(self, name):
        return os.path.join(self.directory.name, name)


class TestNewAndOpen(AppIOTestBase):
    def test_file_new_adds_a_project(self):
        self.io.on_file_new_project = Mock()
        self.io.on_file_new_click()
        self.projects.new.assert_called_once_with()
        self.io.on_file_new_project.assert_not_called()

    def test_gui_open_stops_when_prepare_open_refuses(self):
        filename = self.path('Board.FlatPrj')
        with open(filename, 'w') as stream:
            stream.write('{}')
        self.projects.prepare_open.return_value = False

        self.io._open_project(filename, False, True, False, False)

        self.projects.prepare_open.assert_called_once_with(filename)
        self.assertFalse(self.app.block_autosave)
        self.assertEqual(self.tasks, [])

    def test_tcl_open_does_not_call_prepare_open(self):
        filename = self.path('Board.FlatPrj')
        with open(filename, 'w') as stream:
            stream.write('{}')
        self.io._open_project(filename, False, False, True, True)
        self.projects.prepare_open.assert_not_called()

    def test_restore_adopts_the_filename(self):
        self.io.on_file_new_project = Mock()
        proj_dict = {'objs': [], 'options': {}}
        self.io._restore_project_handler(proj_dict, self.path('Board.FlatPrj'), True, True, True, True)
        self.projects.adopt_filename.assert_called_once_with(self.path('Board.FlatPrj'))


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run the test and see it fail**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_appio.py"`
Expected: 4 failures (for example `Expected 'new' to be called once. Called 0 times.`).

- [ ] **Step 3: Change `on_file_new_click`**

In `appHandlers/appIO.py`, replace the whole body of `on_file_new_click` after its docstring. The old body starts with `self.log.debug("on_file_new_click()")` and ends with the last `self.on_file_new_project(use_thread=True)`. The new body is:

```python
        self.log.debug("on_file_new_click()")

        # the current project stays open in the Project tab, so there is nothing to save here
        self.app.projects.new()
```

- [ ] **Step 4: Add the hook to `_open_project`**

In `_open_project`, find:

```python
        if not os.path.exists(project_filename):
            self.inform.emit('[ERROR_NOTCL] %s' % _("File no longer available."))
            return

        # block auto-saving while a project is loaded
```

Replace it with:

```python
        if not os.path.exists(project_filename):
            self.inform.emit('[ERROR_NOTCL] %s' % _("File no longer available."))
            return

        # an open from the GUI adds a project to the Project tab; Tcl and the command line replace the active one
        projects = getattr(self.app, 'projects', None)
        if projects is not None and not run_from_arg and not cli and not from_tcl:
            if not projects.prepare_open(project_filename):
                return

        # block auto-saving while a project is loaded
```

- [ ] **Step 5: Add the hook to `_restore_project_handler`**

In `_restore_project_handler`, find:

```python
        self.app.project_filename = filename
```

(It is directly before the comment `# for some reason, setting ui_title does not work when this method is called from Tcl Shell`.) Replace it with:

```python
        self.app.project_filename = filename
        projects = getattr(self.app, 'projects', None)
        if projects is not None:
            projects.adopt_filename(filename)
```

- [ ] **Step 6: Run the tests and see them pass**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_appio.py"`
Expected: `OK` (4 tests).

Also run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_project_load_cleanup.py"`
Expected: `OK`. This test uses an app without `projects`, so the `getattr` guard must work.

- [ ] **Step 7: Commit**

```bash
rtk git add appHandlers/appIO.py tests/test_projects_appio.py
rtk git commit -m "feat(projects): File New and File Open add a project to the Project tab"
```

---

### Task 10: Save and Save As use the project name and change the state only after a good save

Today `on_file_save_project` and `on_file_save_project_as` (`appHandlers/appIO.py:1406-1476`) queue the save in a worker and then, at once, clear `should_we_save`, emit `file_saved` and set `project_filename`. If the write fails, the project looks saved. A later close then does not ask to save.

After this task, both callbacks call `_queue_project_save`, which queues `_save_project_task`. That task runs `save_project_checked()` (Task 6: it returns `True` or `False` and never raises) and always emits `project_save_done`. Only the handler of that signal changes the state, on the GUI thread, and only after a good save: the file name, the project name (`adopt_filename`), `file_opened`, `file_saved` and the title. A failed save keeps the old state.

The dirty flag is cleared when the save is queued, before the worker reads the objects. A change during the save (for example a delete) sets the flag again, and a good save does not clear it. A failed save sets the flag back. `save_in_progress` is set when the save is queued, so the exit waits for it.

A project switch can not happen between the queue of the save and its end: `is_busy()` counts the queued worker task (Task 3).

**Files:**
- Modify: `appHandlers/appIO.py`: the signals at the top of the class `appIO` (about line 69-73), `__init__` (about line 96), `on_file_save_project` (about line 1406), `on_file_save_project_as` (about line 1429)
- Test: `tests/test_projects_appio.py` (add tests)

- [ ] **Step 1: Write the failing tests**

In `tests/test_projects_appio.py`, add this class before `if __name__ == '__main__':`:

```python
class TestSave(AppIOTestBase):
    def run_queued_save(self, ok):
        """Run the queued save task with a save_project() that returns ok."""
        from unittest.mock import patch
        task = self.tasks[-1]
        with patch.object(appIO, 'save_project', return_value=ok):
            task['fcn'](*task['params'])

    def test_save_after_rename_writes_the_new_file(self):
        self.app.project_filename = self.path('Board_A.FlatPrj')
        self.projects.save_target.return_value = self.path('Board_B.FlatPrj')

        self.io.on_file_save_project()

        self.assertEqual(self.tasks[-1]['params'][0], self.path('Board_B.FlatPrj'))
        # the file name does not change before the save ends; the save blocks the exit
        self.assertEqual(self.app.project_filename, self.path('Board_A.FlatPrj'))
        self.assertTrue(self.app.save_in_progress)
        self.projects.adopt_filename.assert_not_called()
        self.app.file_saved.emit.assert_not_called()

        self.run_queued_save(True)

        self.assertEqual(self.app.project_filename, self.path('Board_B.FlatPrj'))
        self.projects.adopt_filename.assert_called_once_with(self.path('Board_B.FlatPrj'))
        self.assertFalse(self.app.should_we_save)
        self.app.file_saved.emit.assert_called_once_with('project', self.path('Board_B.FlatPrj'))

    def test_failed_save_keeps_the_old_state(self):
        self.app.project_filename = self.path('Board_A.FlatPrj')
        self.projects.save_target.return_value = self.path('Board_B.FlatPrj')

        self.io.on_file_save_project()
        self.run_queued_save(False)

        self.assertEqual(self.app.project_filename, self.path('Board_A.FlatPrj'))
        self.projects.adopt_filename.assert_not_called()
        self.assertTrue(self.app.should_we_save)
        self.app.file_saved.emit.assert_not_called()

    def test_change_during_the_save_keeps_the_project_dirty(self):
        self.app.project_filename = self.path('Board_A.FlatPrj')
        self.projects.save_target.return_value = self.path('Board_A.FlatPrj')
        self.io.on_file_save_project()
        # the user deletes an object while the worker writes the earlier state
        self.app.should_we_save = True

        self.run_queued_save(True)

        self.assertTrue(self.app.should_we_save)
        self.app.file_saved.emit.assert_called_once_with('project', self.path('Board_A.FlatPrj'))

    def test_second_save_is_refused_while_the_first_is_running(self):
        self.app.project_filename = self.path('Board_A.FlatPrj')
        self.projects.save_target.return_value = self.path('Board_A.FlatPrj')
        self.io.on_file_save_project()
        self.io.on_file_save_project()
        self.assertEqual(len(self.tasks), 1)
        self.assertTrue(self.app.project_save_pending)

        self.run_queued_save(True)

        self.assertFalse(self.app.project_save_pending)
        self.io.on_file_save_project()
        self.assertEqual(len(self.tasks), 2)

    def test_save_stays_pending_until_the_gui_completion(self):
        self.app.project_filename = self.path('Board_A.FlatPrj')
        self.projects.save_target.return_value = self.path('Board_A.FlatPrj')
        self.io.on_file_save_project()
        # the worker ends with a failure, but its completion signal is not delivered yet
        self.io.project_save_done.disconnect(self.io._on_project_save_done)
        self.run_queued_save(False)
        self.assertTrue(self.app.project_save_pending)
        self.assertFalse(self.app.should_we_save)

        # the completion arrives on the GUI thread
        self.io._on_project_save_done(self.path('Board_A.FlatPrj'), False, False, True)

        self.assertFalse(self.app.project_save_pending)
        self.assertTrue(self.app.should_we_save)

    def test_save_that_raises_reports_a_failure(self):
        from unittest.mock import patch
        self.app.project_filename = self.path('Board_A.FlatPrj')
        self.projects.save_target.return_value = self.path('Board_A.FlatPrj')
        self.io.on_file_save_project()
        task = self.tasks[-1]
        with patch.object(appIO, 'save_project', side_effect=RuntimeError('boom')):
            task['fcn'](*task['params'])

        self.assertTrue(self.app.should_we_save)
        self.assertFalse(self.app.save_in_progress)
        self.app.file_saved.emit.assert_not_called()

    def test_save_after_rename_asks_before_overwrite(self):
        self.app.project_filename = self.path('Board_A.FlatPrj')
        with open(self.path('Board_B.FlatPrj'), 'w') as stream:
            stream.write('x')
        self.projects.save_target.return_value = self.path('Board_B.FlatPrj')
        self.projects.ask_yes_no.return_value = False

        self.io.on_file_save_project()

        self.assertEqual(self.tasks, [])
        self.assertEqual(self.app.project_filename, self.path('Board_A.FlatPrj'))

    def test_save_with_same_name_writes_the_same_file(self):
        self.app.project_filename = self.path('Board_A.FlatPrj')
        self.projects.save_target.return_value = self.path('Board_A.FlatPrj')
        self.io.on_file_save_project()
        self.assertEqual(self.tasks[-1]['params'][0], self.path('Board_A.FlatPrj'))
        self.projects.ask_yes_no.assert_not_called()

    def test_save_as_suggests_the_project_name(self):
        from unittest.mock import patch
        self.projects.active = SimpleNamespace(name='Board_A')
        chosen = self.path('Chosen.FlatPrj')
        with patch('appHandlers.appIO.FCFileSaveDialog.get_saved_filename',
                   return_value=(chosen, '')) as dialog:
            self.io.on_file_save_project_as()
        self.assertEqual(dialog.call_args.kwargs['directory'], '%s/%s' % (self.directory.name, 'Board_A'))
        self.assertIsNone(self.app.project_filename)

        self.run_queued_save(True)

        self.assertEqual(self.app.project_filename, chosen)
        self.projects.adopt_filename.assert_called_once_with(chosen)
        self.assertFalse(self.app.should_we_save)

    def test_failed_save_as_keeps_the_old_state(self):
        from unittest.mock import patch
        self.projects.active = SimpleNamespace(name='Board_A')
        with patch('appHandlers.appIO.FCFileSaveDialog.get_saved_filename',
                   return_value=(self.path('Chosen.FlatPrj'), '')):
            self.io.on_file_save_project_as()

        self.run_queued_save(False)

        self.assertIsNone(self.app.project_filename)
        self.projects.adopt_filename.assert_not_called()
        self.assertTrue(self.app.should_we_save)
        self.app.file_saved.emit.assert_not_called()
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_appio.py"`
Expected: failures in `TestSave`.

- [ ] **Step 3: Add the save task and its result signal**

In `appHandlers/appIO.py`:

1. After the line `    project_objects_requested = QtCore.pyqtSignal(object, str, object, bool)` (in the class `appIO`), add:

```python
    # emitted by the save task of File -> Save and Save As: filename, success, make_copy, was_dirty
    project_save_done = QtCore.pyqtSignal(str, bool, bool, bool)
```

2. In `__init__`, after the line `        self.project_objects_requested.connect(self.restore_project_objects)`, add:

```python
        self.project_save_done.connect(self._on_project_save_done)
```

3. At the top of the file, after the line `from appGUI.GUIElements import FCFileSaveDialog, FCMessageBox, add_case_variants`, add:

```python
from appObjects.ProjectContext import same_path
```

4. Before the method `on_file_save_project`, add these 3 methods:

```python
    def _queue_project_save(self, filename, quit_action=False, silent=False, make_copy=False, use_thread=True):
        """
        Start a save of File -> Save or File -> Save As, on the GUI thread.

        The dirty flag is cleared now, before the worker reads the objects. A change while the save runs sets the
        flag again, so a good save does not hide it. A failed save sets the flag back. save_in_progress is set now,
        so the exit waits for a save that is queued but not started.

        Only 1 save runs at a time. project_save_pending is set here and cleared only in _on_project_save_done(),
        both on the GUI thread. While it is set, a new save is refused (a second save could end first; the older
        one would then set an old file name, clear the dirty flag or overwrite a newer file), and the exit and a
        project switch wait (the worker clears save_in_progress before the GUI restores the dirty flag).

        :return:    True if the save is queued
        """
        if getattr(self.app, 'project_save_pending', False):
            self.inform.emit('[WARNING_NOTCL] %s' % _("A save of the project is running. Wait until it ends."))
            return False
        self.app.project_save_pending = True

        was_dirty = bool(self.app.should_we_save)
        self.app.should_we_save = False
        self.app.save_in_progress = True
        params = [filename, quit_action, silent, make_copy, was_dirty]
        if use_thread is True:
            self.worker_task.emit({'fcn': self._save_project_task, 'params': params})
        else:
            self._save_project_task(*params)
        return True

    def _save_project_task(self, filename, quit_action=False, silent=False, make_copy=False, was_dirty=True):
        """
        The worker task of File -> Save and File -> Save As. It always emits project_save_done, also after an
        error. The state of the project changes only in _on_project_save_done(), on the GUI thread.
        """
        ok = self.save_project_checked(filename, quit_action=quit_action, silent=silent)
        self.project_save_done.emit(str(filename), ok, bool(make_copy), bool(was_dirty))

    def _on_project_save_done(self, filename, ok, make_copy, was_dirty):
        """
        Change the state of the project after a save. After a failed save, the project keeps its file name,
        its name and its unsaved changes.
        """
        # the save is complete for the GUI; a new save, the exit and a switch are allowed again after this method
        self.app.project_save_pending = False
        if not ok:
            self.app.save_in_progress = False
            if was_dirty:
                self.app.should_we_save = True
            self.inform.emit('[ERROR_NOTCL] %s: %s' % (_("The project was not saved"), filename))
            return

        if self.app.options.get("global_open_style", self.app.defaults.get("global_open_style")) is False:
            self.app.file_opened.emit("project", filename)
        self.app.file_saved.emit("project", filename)

        if not make_copy:
            self.app.project_filename = filename
            projects = getattr(self.app, 'projects', None)
            if projects is not None:
                projects.adopt_filename(filename)

        self.app.ui.set_ui_title(name=self.app.project_filename)
        # do not clear should_we_save here: it was cleared when the save was queued, and if it is set now, the
        # project changed while the save ran and that change is not in the file
```

- [ ] **Step 4: Change `on_file_save_project`**

Replace the whole body of `on_file_save_project`, from the line `        self.log.debug("on_file_save_project()")` to the last line of the method `        self.app.should_we_save = False`, with:

```python
        self.log.debug("on_file_save_project()")

        target = self.app.project_filename
        # after a rename, the project is saved as '<new name>.FlatPrj' in the same folder; the old file stays
        projects = getattr(self.app, 'projects', None)
        if projects is not None and target is not None:
            new_target = projects.save_target()
            if new_target and not same_path(new_target, target):
                if os.path.exists(new_target) and not projects.ask_yes_no(
                        _("Overwrite"), '%s: %s\n%s' % (_("The file already exists"), new_target,
                                                        _("Do you want to overwrite it?"))):
                    self.inform.emit('[WARNING_NOTCL] %s' % _("Cancelled."))
                    return
                target = new_target

        if target is None:
            self.on_file_save_project_as()
            return

        # the file name and the title change in _on_project_save_done(), after a good save
        self._queue_project_save(target, quit_action=False, silent=silent)
```

Note: the old code passed `silent` as the second positional argument of `save_project`, which is `quit_action`. The new code passes `quit_action=False` and `silent` in the right places.

- [ ] **Step 5: Change `on_file_save_project_as`**

1. Find:

```python
        filter_ = "FlatCAM Project .FlatPrj (*.FlatPrj);; All Files (*.*)"
        try:
            filename, _f = FCFileSaveDialog.get_saved_filename(
                caption=_("Save Project As ..."),
                directory='{l_save}/{proj}_{date}'.format(l_save=str(self.app.get_last_save_folder()), date=date,
                                                          proj=_("Project")),
                ext_filter=filter_
            )
```

Replace it with:

```python
        filter_ = "FlatCAM Project .FlatPrj (*.FlatPrj);; All Files (*.*)"
        # the suggested file name is the project name
        projects = getattr(self.app, 'projects', None)
        if projects is not None:
            proj_name = projects.active.name
        else:
            proj_name = '%s_%s' % (_("Project"), date)
        try:
            filename, _f = FCFileSaveDialog.get_saved_filename(
                caption=_("Save Project As ..."),
                directory='{l_save}/{proj}'.format(l_save=str(self.app.get_last_save_folder()), proj=proj_name),
                ext_filter=filter_
            )
```

2. Replace the end of the method, from the line `        if use_thread is True:` to the last line `        self.app.should_we_save = False`, with:

```python
        # the file name and the title change in _on_project_save_done(), after a good save
        self._queue_project_save(filename, quit_action=quit_action, silent=False, make_copy=make_copy,
                                 use_thread=use_thread)
```

- [ ] **Step 6: Run the tests and see them pass**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_appio.py"`
Expected: `OK` (14 tests).

Also run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_project_load_cleanup.py"`
Expected: `OK`.

Also run: `.venv/Scripts/python.exe -m pytest tests/test_app_handler_characterization.py tests/test_app_refactor_characterization.py -q`
Expected: all pass. If a test there expects `should_we_save` to be `False` at once after `on_file_save_project`, report it. Do not change it without a report: that test checks the old behavior that this task removes.

- [ ] **Step 7: Commit**

```bash
rtk git add appHandlers/appIO.py tests/test_projects_appio.py
rtk git commit -m "feat(projects): Save and Save As use the project name for the file"
```

---

### Task 11: Exit asks about each project with unsaved changes

**Files:**
- Modify: `appHandlers/appLifecycle.py`, method `final_save` (about line 246)
- Test: `tests/test_projects_manager.py` (add tests)

- [ ] **Step 1: Write the failing tests**

In `tests/test_projects_manager.py`, add this class before `if __name__ == '__main__':`:

```python
class TestExitWithProjects(unittest.TestCase):
    def make_lifecycle(self, dirty):
        from appHandlers.appLifecycle import AppLifecycle
        start = SimpleNamespace(name='Board_A')
        projects = SimpleNamespace(active=start, dirty_contexts=Mock(return_value=dirty),
                                   ask_save=Mock(), save_context=Mock(return_value=True),
                                   switch=Mock(return_value=True), return_to=Mock(),
                                   hold_autosave=Mock(return_value=False), release_autosave=Mock())
        app = SimpleNamespace(save_in_progress=False, projects=projects, trayIcon=Mock(),
                              inform=Mock(), log=Mock(), block_autosave=False, should_we_save=False)
        lifecycle = AppLifecycle.__new__(AppLifecycle)
        lifecycle.app = app
        lifecycle.inform = app.inform
        lifecycle.quit_application = Mock(return_value=True)
        return lifecycle, projects, start

    def test_no_dirty_project_quits(self):
        lifecycle, projects, start = self.make_lifecycle([])
        lifecycle.final_save()
        lifecycle.quit_application.assert_called_once_with()

    def test_each_dirty_project_is_asked(self):
        first, second = SimpleNamespace(name='A'), SimpleNamespace(name='B')
        lifecycle, projects, start = self.make_lifecycle([first, second])
        projects.ask_save.side_effect = ['yes', 'no']
        lifecycle.final_save()
        self.assertEqual(projects.ask_save.call_count, 2)
        projects.save_context.assert_called_once_with(first, visuals=False)
        lifecycle.quit_application.assert_called_once_with()

    def test_cancel_stops_the_exit_and_restores_the_active_project(self):
        first = SimpleNamespace(name='A')
        lifecycle, projects, start = self.make_lifecycle([first])
        projects.ask_save.return_value = 'cancel'
        lifecycle.final_save()
        lifecycle.quit_application.assert_not_called()
        projects.return_to.assert_called_once_with(start)

    def test_failed_save_stops_the_exit(self):
        first = SimpleNamespace(name='A')
        lifecycle, projects, start = self.make_lifecycle([first])
        projects.ask_save.return_value = 'yes'
        projects.save_context.return_value = False
        lifecycle.final_save()
        lifecycle.quit_application.assert_not_called()

    def test_exit_waits_for_the_completion_of_a_save(self):
        # the worker of a failed save cleared save_in_progress, but the GUI did not restore the dirty flag yet
        lifecycle, projects, start = self.make_lifecycle([])
        lifecycle.app.project_save_pending = True
        lifecycle.final_save()
        lifecycle.quit_application.assert_not_called()
        projects.dirty_contexts.assert_not_called()
        lifecycle.inform.emit.assert_called_once()

    def use_real_autosave_hold(self, lifecycle, projects):
        from types import MethodType
        from appHandlers.appProjects import ProjectManager
        owner = SimpleNamespace(app=lifecycle.app)
        projects.hold_autosave = MethodType(ProjectManager.hold_autosave, owner)
        projects.release_autosave = MethodType(ProjectManager.release_autosave, owner)

    def test_autosave_in_the_exit_dialog_does_not_start_a_save(self):
        first = SimpleNamespace(name='A')
        lifecycle, projects, start = self.make_lifecycle([first])
        self.use_real_autosave_hold(lifecycle, projects)
        app = lifecycle.app
        app.should_we_save = True
        app.f_handlers = SimpleNamespace(on_file_save_project=Mock())

        def answer_after_autosave(ctx):
            # the autosave timer fires in the nested event loop of the dialog, then the user answers Yes
            lifecycle.save_project_auto()
            return 'yes'

        projects.ask_save.side_effect = answer_after_autosave

        lifecycle.final_save()

        app.f_handlers.on_file_save_project.assert_not_called()
        projects.save_context.assert_called_once_with(first, visuals=False)
        lifecycle.quit_application.assert_called_once_with()

    def test_cancel_restores_the_autosave(self):
        first = SimpleNamespace(name='A')
        lifecycle, projects, start = self.make_lifecycle([first])
        self.use_real_autosave_hold(lifecycle, projects)
        seen = []

        def answer(ctx):
            seen.append(lifecycle.app.block_autosave)
            return 'cancel'

        projects.ask_save.side_effect = answer

        lifecycle.final_save()

        self.assertEqual(seen, [True])
        self.assertFalse(lifecycle.app.block_autosave)
        lifecycle.quit_application.assert_not_called()

    def test_exit_does_not_quit_with_a_save_pending_after_the_dialogs(self):
        first = SimpleNamespace(name='A')
        lifecycle, projects, start = self.make_lifecycle([first])
        projects.ask_save.return_value = 'yes'

        def save_and_leave_pending(ctx, visuals=True):
            lifecycle.app.project_save_pending = True
            return True

        projects.save_context.side_effect = save_and_leave_pending

        lifecycle.final_save()

        lifecycle.quit_application.assert_not_called()
        lifecycle.inform.emit.assert_called_once()

    def test_cancel_of_the_tools_database_question_restores_the_autosave(self):
        from types import MethodType
        from appHandlers.appLifecycle import AppLifecycle
        lifecycle, projects, start = self.make_lifecycle([])
        self.use_real_autosave_hold(lifecycle, projects)
        app = lifecycle.app
        app.f_handlers = SimpleNamespace(on_file_save_project=Mock())
        # the real quit_application(); only the answer of the Tools Database question is mocked
        lifecycle.quit_application = MethodType(AppLifecycle.quit_application, lifecycle)
        lifecycle._confirm_tools_database = Mock(return_value=False)

        lifecycle.final_save()

        lifecycle._confirm_tools_database.assert_called_once_with()
        self.assertFalse(app.block_autosave)
        app.trayIcon.hide.assert_not_called()
        # the app stays open, so the next autosave must start a save
        app.should_we_save = True
        lifecycle.save_project_auto()
        app.f_handlers.on_file_save_project.assert_called_once_with()

    def test_refused_quit_after_the_save_of_an_inactive_project_returns_to_the_start_project(self):
        from types import MethodType
        from appHandlers.appLifecycle import AppLifecycle
        QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        # the real ProjectManager: Board_A is active and on the canvas, Board_B is not active and has changes
        app, manager = make_manager()
        first = manager.active
        second = manager.add_context('Board_B')
        second.filename = 'Board_B.FlatPrj'
        second.should_we_save = True
        app.block_autosave = False
        app.projects = manager
        app.trayIcon = Mock()
        app.f_handlers = SimpleNamespace(save_project_checked=Mock(return_value=True),
                                         on_file_save_project=Mock())
        manager.ask_save = Mock(return_value='yes')
        lifecycle = AppLifecycle.__new__(AppLifecycle)
        lifecycle.app = app
        lifecycle.inform = app.inform
        # the real quit_application(); only the answer of the Tools Database question is mocked
        lifecycle.quit_application = MethodType(AppLifecycle.quit_application, lifecycle)
        lifecycle._confirm_tools_database = Mock(return_value=False)

        lifecycle.final_save()

        # Board_B is saved, then the quit is refused
        app.f_handlers.save_project_checked.assert_called_once_with('Board_B.FlatPrj', silent=True)
        self.assertFalse(second.should_we_save)
        # the live state is Board_A again, the same project that the canvas shows
        self.assertIs(manager.active, first)
        self.assertIs(app.collection, first.collection)
        self.assertIs(manager.stack.currentWidget(), first.collection.view)
        self.assertIs(manager.displayed, first)
        app.trayIcon.hide.assert_not_called()
        # the autosave runs again
        self.assertFalse(app.block_autosave)
        app.should_we_save = True
        lifecycle.save_project_auto()
        app.f_handlers.on_file_save_project.assert_called_once_with()
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_manager.py"`
Expected: failures in `TestExitWithProjects`.

- [ ] **Step 3: Change `AppLifecycle.final_save`**

In `appHandlers/appLifecycle.py`, in `final_save`, find:

```python
        if self.app.save_in_progress:
            self.inform.emit('[WARNING_NOTCL] %s' % _("Application is saving the project. Please wait ..."))
            return

        if self.app.should_we_save and self.app.collection.get_list():
```

Replace it with:

```python
        # project_save_pending stays set until the GUI has the result of a File -> Save; before that, the dirty
        # flag of a failed save is not restored yet
        if self.app.save_in_progress or getattr(self.app, 'project_save_pending', False):
            self.inform.emit('[WARNING_NOTCL] %s' % _("Application is saving the project. Please wait ..."))
            return

        # with more than 1 project, ask about each project that has unsaved changes
        projects = getattr(self.app, 'projects', None)
        if projects is not None:
            start = projects.active
            # the dialogs below run a nested event loop; the autosave timer must not start a save during them.
            # quit_application() also asks a question (the Tools Database) and can refuse the quit. Only a quit
            # that returns True keeps the autosave blocked: quit_application() stops its timer.
            autosave_state = projects.hold_autosave()
            quitting = False
            try:
                for ctx in projects.dirty_contexts():
                    answer = projects.ask_save(ctx)
                    if answer == 'cancel' or (answer == 'yes' and not projects.save_context(ctx, visuals=False)):
                        return
                # check again: the app must not quit while a save is pending
                if self.app.save_in_progress or getattr(self.app, 'project_save_pending', False):
                    self.inform.emit('[WARNING_NOTCL] %s' % _("Application is saving the project. Please wait ..."))
                    return
                quitting = self.quit_application() is True
            finally:
                if not quitting:
                    # the exit stops (a cancel, a failed save, a pending save, a refused quit or an error). The save
                    # of an inactive project made it active, but the canvas still shows start: make start active
                    try:
                        projects.return_to(start)
                    finally:
                        projects.release_autosave(autosave_state)
            if quitting:
                # QApplication.quit() only posts the quit event, so the tray icon is hidden before the app ends
                try:
                    self.app.trayIcon.hide()
                except Exception:
                    pass
            return

        if self.app.should_we_save and self.app.collection.get_list():
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_manager.py"`
Expected: `OK` (70 tests).

Also run: `.venv/Scripts/python.exe -m pytest tests/test_shutdown_routing.py -q`
Expected: all tests pass, 0 failed.

- [ ] **Step 5: Commit**

```bash
rtk git add appHandlers/appLifecycle.py tests/test_projects_manager.py
rtk git commit -m "feat(projects): exit asks about each project with unsaved changes"
```

---

### Task 12: Tcl commands `list_projects`, `select_project` and `close_project`

**Files:**
- Create: `tclCommands/TclCommandListProjects.py`
- Create: `tclCommands/TclCommandSelectProject.py`
- Create: `tclCommands/TclCommandCloseProject.py`
- Modify: `tclCommands/__init__.py`
- Test: `tests/test_tcl_projects.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tcl_projects.py`:

```python
"""Tcl commands for the projects of the Project tab."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock


class TclError(Exception):
    pass


def make_app():
    first = SimpleNamespace(name='Board_A')
    second = SimpleNamespace(name='Board_B')
    contexts = [first, second]
    projects = SimpleNamespace(
        active=first, names=Mock(return_value=['Board_A', 'Board_B']),
        get_by_name=Mock(side_effect=lambda name: next((c for c in contexts if c.name == name), None)),
        switch=Mock(return_value=True), close=Mock(return_value=True), is_dirty=Mock(return_value=False))

    def raise_tcl_error(text):
        raise TclError(text)

    return SimpleNamespace(log=Mock(), projects=projects, shell=SimpleNamespace(raise_tcl_error=raise_tcl_error))


class TestListProjects(unittest.TestCase):
    def test_lists_the_names(self):
        from tclCommands.TclCommandListProjects import TclCommandListProjects
        app = make_app()
        self.assertEqual(TclCommandListProjects(app).execute({}, []), 'Board_A\nBoard_B')

    def test_alias(self):
        from tclCommands.TclCommandListProjects import TclCommandListProjects
        self.assertEqual(TclCommandListProjects.aliases, ['list_projects'])


class TestSelectProject(unittest.TestCase):
    def test_switches_by_name(self):
        from tclCommands.TclCommandSelectProject import TclCommandSelectProject
        app = make_app()
        TclCommandSelectProject(app).execute({'name': 'Board_B'}, [])
        app.projects.switch.assert_called_once_with(app.projects.get_by_name('Board_B'))

    def test_unknown_name_is_an_error(self):
        from tclCommands.TclCommandSelectProject import TclCommandSelectProject
        app = make_app()
        with self.assertRaises(TclError):
            TclCommandSelectProject(app).execute({'name': 'Missing'}, [])
        app.projects.switch.assert_not_called()

    def test_refused_switch_is_an_error(self):
        from tclCommands.TclCommandSelectProject import TclCommandSelectProject
        app = make_app()
        app.projects.switch.return_value = False
        with self.assertRaises(TclError):
            TclCommandSelectProject(app).execute({'name': 'Board_B'}, [])


class TestCloseProject(unittest.TestCase):
    def test_closes_the_active_project_by_default(self):
        from tclCommands.TclCommandCloseProject import TclCommandCloseProject
        app = make_app()
        TclCommandCloseProject(app).execute({}, [])
        app.projects.close.assert_called_once_with(app.projects.active, force=True)

    def test_closes_by_name(self):
        from tclCommands.TclCommandCloseProject import TclCommandCloseProject
        app = make_app()
        TclCommandCloseProject(app).execute({'name': 'Board_B'}, [])
        app.projects.close.assert_called_once_with(app.projects.get_by_name('Board_B'), force=True)

    def test_dirty_project_without_force_is_an_error(self):
        from tclCommands.TclCommandCloseProject import TclCommandCloseProject
        app = make_app()
        app.projects.is_dirty.return_value = True
        with self.assertRaises(TclError):
            TclCommandCloseProject(app).execute({}, [])
        app.projects.close.assert_not_called()

    def test_dirty_project_with_force_closes(self):
        from tclCommands.TclCommandCloseProject import TclCommandCloseProject
        app = make_app()
        app.projects.is_dirty.return_value = True
        for value in ('1', 'True', 'true', None):
            app.projects.close.reset_mock()
            TclCommandCloseProject(app).execute({'force': value}, [])
            app.projects.close.assert_called_once_with(app.projects.active, force=True)

    def test_force_0_does_not_force(self):
        from tclCommands.TclCommandCloseProject import TclCommandCloseProject
        app = make_app()
        app.projects.is_dirty.return_value = True
        with self.assertRaises(TclError):
            TclCommandCloseProject(app).execute({'force': '0'}, [])

    def test_unknown_name_is_an_error(self):
        from tclCommands.TclCommandCloseProject import TclCommandCloseProject
        app = make_app()
        with self.assertRaises(TclError):
            TclCommandCloseProject(app).execute({'name': 'Missing'}, [])

    def test_refused_close_is_an_error(self):
        from tclCommands.TclCommandCloseProject import TclCommandCloseProject
        app = make_app()
        app.projects.close.return_value = False
        with self.assertRaises(TclError):
            TclCommandCloseProject(app).execute({}, [])


class TestRegistration(unittest.TestCase):
    def test_modules_are_imported(self):
        import sys
        import tclCommands  # noqa: F401
        for name in ('TclCommandListProjects', 'TclCommandSelectProject', 'TclCommandCloseProject'):
            self.assertIn('tclCommands.%s' % name, sys.modules)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run the test and see it fail**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_tcl_projects.py"`
Expected: errors with `ModuleNotFoundError: No module named 'tclCommands.TclCommandListProjects'`.

- [ ] **Step 3: Write `tclCommands/TclCommandListProjects.py`**

```python
from tclCommands.TclCommand import TclCommand

import collections


class TclCommandListProjects(TclCommand):
    """
    Tcl shell command that returns the names of the projects in the Project tab.

    example:
        list_projects
    """

    # List of all command aliases, to be able use old names for backward compatibility (add_poly, add_polygon)
    aliases = ['list_projects']

    description = '%s %s' % ("--", "Return to TCL the list of the project names "
                                   "as a string with names separated by the '\\n' char.")

    # Dictionary of types from Tcl command, needs to be ordered
    arg_names = collections.OrderedDict([

    ])

    # Dictionary of types from Tcl command, needs to be ordered , this  is  for options  like -optionname value
    option_types = collections.OrderedDict([

    ])

    # array of mandatory options for current Tcl command: required = {'name','outname'}
    required = []

    # structured help for current command, args needs to be ordered
    help = {
        'main': 'Lists the names of the projects in the Project tab, in the order of the Project combobox. '
                'It returns a string with names separated by "\\n" character',
        'args': collections.OrderedDict([

        ]),
        'examples': ['list_projects']
    }

    def execute(self, args, unnamed_args):
        """

        :param args:
        :param unnamed_args:
        :return:
        """

        return '\n'.join(self.app.projects.names())
```

- [ ] **Step 4: Write `tclCommands/TclCommandSelectProject.py`**

```python
from tclCommands.TclCommand import TclCommand

import collections


class TclCommandSelectProject(TclCommand):
    """
    Tcl shell command that makes a project of the Project tab active.

    example:
        select_project Board_B
    """

    # List of all command aliases, to be able use old names for backward compatibility (add_poly, add_polygon)
    aliases = ['select_project']

    description = '%s %s' % ("--", "Makes the project with the given name the active project.")

    # Dictionary of types from Tcl command, needs to be ordered
    arg_names = collections.OrderedDict([
        ('name', str),
    ])

    # Dictionary of types from Tcl command, needs to be ordered , this  is  for options  like -optionname value
    option_types = collections.OrderedDict([

    ])

    # array of mandatory options for current Tcl command: required = {'name','outname'}
    required = ['name']

    # structured help for current command, args needs to be ordered
    help = {
        'main': 'Makes the project with the given name the active project. '
                'The command fails if no project has that name or if a task is running.',
        'args': collections.OrderedDict([
            ('name', 'Name of the project. Required.'),
        ]),
        'examples': ['select_project Board_B']
    }

    def execute(self, args, unnamed_args):
        """

        :param args:
        :param unnamed_args:
        :return:
        """

        name = str(args['name'])
        ctx = self.app.projects.get_by_name(name)
        if ctx is None:
            self.raise_tcl_error('%s: %s' % ("Project not found", name))
            return 'fail'

        if not self.app.projects.switch(ctx):
            self.raise_tcl_error('%s: %s' % ("Could not select the project. A task is running", name))
            return 'fail'
```

- [ ] **Step 5: Write `tclCommands/TclCommandCloseProject.py`**

```python
from tclCommands.TclCommand import TclCommand

import collections


class TclCommandCloseProject(TclCommand):
    """
    Tcl shell command that closes and removes a project of the Project tab.

    example:
        close_project Board_B -force 1
    """

    # List of all command aliases, to be able use old names for backward compatibility (add_poly, add_polygon)
    aliases = ['close_project']

    description = '%s %s' % ("--", "Closes and removes a project. Without a name, it closes the active project.")

    # Dictionary of types from Tcl command, needs to be ordered
    arg_names = collections.OrderedDict([
        ('name', str),
    ])

    # Dictionary of types from Tcl command, needs to be ordered , this  is  for options  like -optionname value
    option_types = collections.OrderedDict([
        ('force', str),
    ])

    # array of mandatory options for current Tcl command: required = {'name','outname'}
    required = []

    # structured help for current command, args needs to be ordered
    help = {
        'main': 'Closes and removes a project. There is no dialog. '
                'If the project has unsaved changes, the command fails unless -force is True. '
                'If the last project is closed, 1 empty project replaces it.',
        'args': collections.OrderedDict([
            ('name', 'Name of the project. If not given, the active project is closed.'),
            ('force', 'Close a project with unsaved changes; the changes are lost.\n'
                      'Can be used without value which will be auto assumed to be True.\n'
                      'Or it can have a value: True (1) or False (0).'),
        ]),
        'examples': ['close_project\n'
                     'close_project Board_B\n'
                     'close_project Board_B -force 1']
    }

    def execute(self, args, unnamed_args):
        """

        :param args:
        :param unnamed_args:
        :return:
        """

        projects = self.app.projects

        if 'name' in args:
            name = str(args['name'])
            ctx = projects.get_by_name(name)
            if ctx is None:
                self.raise_tcl_error('%s: %s' % ("Project not found", name))
                return 'fail'
        else:
            ctx = projects.active

        is_forced = False
        if 'force' in args:
            value = args['force']
            is_forced = value is None or str(value).strip().lower() in ('1', 'true', 'yes')

        if projects.is_dirty(ctx) and not is_forced:
            self.raise_tcl_error('%s: %s. %s' % ("The project has unsaved changes", ctx.name,
                                                 "Use -force 1 to close it."))
            return 'fail'

        if not projects.close(ctx, force=True):
            self.raise_tcl_error('%s: %s' % ("Could not close the project. A task is running", ctx.name))
            return 'fail'
```

- [ ] **Step 6: Register the 3 commands**

In `tclCommands/__init__.py`, add 3 import lines in the list at the top:

After `import tclCommands.TclCommandClearShell` add:

```python
import tclCommands.TclCommandCloseProject
```

After `import tclCommands.TclCommandListPP` add:

```python
import tclCommands.TclCommandListProjects
```

After `import tclCommands.TclCommandScale` add:

```python
import tclCommands.TclCommandSelectProject
```

- [ ] **Step 7: Run the test and see it pass**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_tcl_projects.py"`
Expected: `OK` (13 tests).

- [ ] **Step 8: Commit**

```bash
rtk git add tclCommands/TclCommandListProjects.py tclCommands/TclCommandSelectProject.py tclCommands/TclCommandCloseProject.py tclCommands/__init__.py tests/test_tcl_projects.py
rtk git commit -m "feat(tcl): add the list_projects, select_project and close_project commands"
```

---

### Task 13: Changelog, full test run and manual check list

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the changelog entry**

In `CHANGELOG.md`, the newest date block is at the top, below the line that starts with `CHANGELOG for FlatCAM Evo`. If a block `18.10.2026` with a `GUI:` section exists, add this line at the end of the `GUI:` list. If no block for today exists, make a new date block with today's date in the same format, with a `GUI:` section.

```markdown
- the Project tab can hold more than 1 project: a Project combobox above the tree selects the active project; a right-click on the combobox has New Project, Open Project, Rename Project and Close Project; an inactive project keeps its geometry and its Properties UI but releases its plots; a switch is refused while an editor is open or a task runs; File New and File Open add a project; after a rename, Save writes '<new name>.FlatPrj' in the same folder and the title bar shows the project name; exit asks about each project with unsaved changes; new Tcl commands list_projects, select_project and close_project
```

- [ ] **Step 2: Run all the new test files**

Run each command. Each one must show `OK`:

```bash
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_project_context.py"
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_manager.py"
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_project_selector.py"
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_appio.py"
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_tcl_projects.py"
```

- [ ] **Step 3: Run the full test suite 1 time**

Run: `.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider`
Expected: 0 failed, except the tests that already failed before Task 1. On 2026-10-18 these 5 tests failed before this work: `test_appmain_refactored.py::TestSignalConnections::test_object_status_changed_connected`, `test_grbl_sender_audit_fixes.py::TestStaleHeightMesh::test_on_show_3d_failed_build_clears_mesh`, `test_levelling_audit.py::TestSignalsOnce::test_port_force_closes_on_app_quit` and 2 tests in `test_pcbdoc_isolation.py`. The run takes about 7 minutes. Use pytest here: some test files have pytest-style test functions that unittest discovery does not find. If a test fails, compare with the result on the commit before Task 1 (`rtk git stash` is not needed; use `rtk git log --oneline -15` to find that commit and report the failing test names). Report the failures. Do not fix tests that were already failing before Task 1.

- [ ] **Step 4: Commit**

```bash
rtk git add CHANGELOG.md
rtk git commit -m "docs(changelog): add the multiple projects in the Project tab"
```

- [ ] **Step 5: Give this manual check list to the user**

The agent can not do these checks. Copy the list into the final report:

1. Start the app. The Project tab shows `Project: [Project_1]` above the tree.
2. Open a Gerber. Right-click on the combobox. Select New Project. The tree is empty and the canvas is empty. The title bar shows `Project_2`.
3. Select `Project_1` in the combobox. The Gerber shows again on the canvas, with the same zoom as before.
4. Select the Gerber and open the Properties tab. The Properties UI shows.
5. Right-click on the combobox. Select Rename Project. Type `Board_A`. The combobox and the title bar show `Board_A`.
6. Save. Save As suggests `Board_A.FlatPrj`. Save it. Rename to `Board_B`. Save. A new file `Board_B.FlatPrj` is in the same folder. `Board_A.FlatPrj` is still there.
7. Open `Board_A.FlatPrj` while `Board_B` is open. It adds a project named `Board_A`. Open `Board_A.FlatPrj` again. The app asks to overwrite it.
8. Start an Isolation job on a big Gerber. While it runs, click the combobox. It does not open, and the status bar shows "A task is running. Wait until it ends."
9. Change a project option in Project A, for example the Isolation tool diameter in Preferences. Switch to Project B. Preferences shows the value of Project B. Change an application setting, for example the grid. It is the same in both projects.
10. In the Tcl shell: `list_projects`, `select_project Board_A`, `close_project Board_A` (with unsaved changes: error), `close_project Board_A -force 1`.
11. Make changes in 2 projects. Close the app. The app asks about each project by name.
12. Open the Geometry Editor on an object. Use File > New Project. The status bar shows "Close the editor first." and the editor stays open with its changes.
13. Open a CNCJob and edit its G-code in the CNC editor. Save the edit. Switch to another project and back. The edited G-code is still there.
14. Make the project folder read-only. Close the project and choose Save. The save fails, the project stays open and it still has unsaved changes.
15. With the folder still read-only, rename the project and use File > Save. The status bar shows "The project was not saved". The combobox and the title keep the old file. Close the project: the app asks to save.
16. Open a saved project. Delete all its objects. Close the project: the app asks to save. In Tcl, `close_project <name>` gives an error; `close_project <name> -force 1` closes it.
17. Make changes in 2 projects. Zoom project B to a different view, then show project A. Close the app, save B, and press Cancel at the question about A. Show project B: its zoom is the same as before.
18. Open a big project and use File > Save. While the status bar shows "Saving Project ...", delete an object. When the save ends, close the project: the app asks to save.
19. Check the RAM in Task Manager: open a big project, add a second project and switch to it. The RAM of the app goes down or stays the same. It does not double.
20. In Preferences, set the autosave on with the shortest interval. Save a project, then change it. Close the app and wait at the "Save changes" question for more than 1 interval. Answer Yes. The app saves 1 time and quits. Do it again and answer Cancel: the autosave runs again after 1 interval. Open the Tools Database, change a tool, then close the app. Answer the project question, then cancel the Tools Database question: the app stays open and the autosave runs again after 1 interval. Do it again with 2 projects: make `Board_A` active and change `Board_B`. At exit, answer Yes for `Board_B`, then cancel the Tools Database question. The combobox, the tree and the canvas all show `Board_A`.

---

## Known limits (do not fix in this plan)

- A switch re-creates all plugins (`init_tools`), the same as File > New Project. If the GRBL Sender has an open serial connection, a switch closes that connection.
- Autosave saves only the active project.
- The Code Editor tabs of Script and Document objects stay open after a switch.
- The Tcl commands `new` and `open_project` replace the active project. They do not add a project.
- An inactive project keeps the Properties UI of its objects, so it uses more RAM than a project that releases it. `set_ui()` must become safe to run 2 times before the UI can be released.
- The Tcl `save_project` command still calls `save_project()` directly (`tclCommands/TclCommandSaveProject.py:53`). It gets the error handling of Task 6, but not the completion of Task 10: it does not change the file name or the dirty flag, the same as today.
- The autosave calls `on_file_save_project()` (`appLifecycle.py:682`), so it uses the flow of Task 10. After a rename, the autosave writes `<new name>.FlatPrj`, and if that file exists it shows the overwrite question, the same as File > Save. An autosave while a save is pending is refused with the status bar message of Task 10. While the dialogs of a close or an exit are open, the autosave is blocked (`hold_autosave`, Task 6). This includes the Tools Database question of `quit_application()`. A cancel restores its old state.
