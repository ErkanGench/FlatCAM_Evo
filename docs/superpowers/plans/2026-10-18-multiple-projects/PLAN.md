# Multiple Projects in the Project Tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Project tab holds more than 1 project. A combobox above the object tree selects the active project. Inactive projects keep their geometry but release their plot shapes and their Properties UI.

**Architecture:** A new `ProjectContext` holds the state of 1 project. A new `ProjectManager` holds the list of contexts and puts the state of the active context into the existing `App` attributes (`app.collection`, `app.options`, `app.project_filename`, `app.should_we_save`, `app.all_objects_list`). Because all existing code reads `app.collection` when it runs, the 817 existing call sites do not change. A new `ProjectSelector` widget shows the combobox and its right-click menu.

**Tech Stack:** Python 3.11, PyQt6, VisPy, `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-18-multiple-projects-design.md`

---

## Rules for the agent (read first)

1. Work on the local branch `1.0`. Do not make a new branch. Do not push.
2. Run Python with the project venv: `.venv/Scripts/python.exe`. Run a test file as a script: `.venv/Scripts/python.exe tests/test_projects_manager.py`.
3. Run only the test files that the task names. Do not run the full test suite. The full suite takes about 4 minutes and runs only once, in Task 13.
4. Do not add a `Co-Authored-By` line or any Claude attribution to a commit message.
5. Commit only the files that the task names. The folder `docs/mach3/` is not part of this work. Do not add it.
6. The line numbers in this plan are approximate. Find each place by the quoted code text, not by the line number.
7. Match the style of the code around the change: 4-space indent, `_()` for user-visible strings, the same comment style.
8. If a test fails and the fix is not clear in 2 tries, stop and report the error text. Do not change a test to make it pass.
9. If a `python.exe` process stays alive after a test run, stop it: `taskkill /F /IM python.exe`.

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

Run: `.venv/Scripts/python.exe tests/test_projects_manager.py`
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

Run: `.venv/Scripts/python.exe tests/test_projects_manager.py`
Expected: `OK` (2 tests).

Also run: `.venv/Scripts/python.exe tests/test_plot_visibility_toggle.py`
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

Run: `.venv/Scripts/python.exe tests/test_project_context.py`
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
        # None means: load the application defaults when the project becomes active
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

Run: `.venv/Scripts/python.exe tests/test_project_context.py`
Expected: `OK` (8 tests).

- [ ] **Step 5: Commit**

```bash
rtk git add appObjects/ProjectContext.py tests/test_project_context.py
rtk git commit -m "feat(projects): add ProjectContext and the project name helpers"
```

---

### Task 3: `ProjectManager` core: list, capture, load and switch

This task makes the manager without dialogs. The visual steps of a switch (`before_switch`, `deactivate`, `activate`) are empty in this task. Task 5 fills them.

**Files:**
- Create: `appHandlers/appProjects.py`
- Test: `tests/test_projects_manager.py` (add tests)

- [ ] **Step 1: Write the failing tests**

In `tests/test_projects_manager.py`, add this code after the class `TestHandlersReadLiveCollection` and before `if __name__ == '__main__':`:

```python
def make_app(collection=None):
    return SimpleNamespace(
        collection=collection or FakeCollection(), options={'units': 'MM'}, project_filename=None,
        should_we_save=False, all_objects_list=[], inform=Mock(), log=Mock(),
        ui=SimpleNamespace(set_ui_title=Mock()),
        proc_container=SimpleNamespace(get_procs_count=Mock(return_value=0)),
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
        # the old state is written back to the old context
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
        app.app_obj.load_batches.add(object())
        self.assertTrue(manager.is_busy())

    def test_projects_changed_is_emitted_on_switch(self):
        app, manager = make_manager()
        second = manager.add_context('Board_B')
        listener = Mock()
        manager.projects_changed.connect(listener)
        manager.switch(second)
        listener.assert_called()
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/Scripts/python.exe tests/test_projects_manager.py`
Expected: errors with `ModuleNotFoundError: No module named 'appHandlers.appProjects'`.

- [ ] **Step 3: Write `appHandlers/appProjects.py`**

```python
from copy import deepcopy
import os

from PyQt6 import QtCore, QtWidgets

from appObjects.ProjectContext import ProjectContext, unique_name, same_path, name_from_filename, \
    is_valid_name, PROJECT_EXT

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

    def is_busy(self):
        """
        True if a background task runs. A switch is not allowed then, because the task can add its result to the
        wrong project.
        """
        app = self.app
        try:
            if app.proc_container.get_procs_count() > 0:
                return True
        except AttributeError:
            pass
        if getattr(app, 'save_in_progress', False):
            return True
        collection = app.collection
        if collection.has_promises() or collection.has_plot_promises():
            return True
        return bool(getattr(getattr(app, 'app_obj', None), 'load_batches', None))

    def inform_busy(self):
        self.app.inform.emit('[WARNING_NOTCL] %s' % _("A task is running. Wait until it ends."))

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
        ctx.options = deepcopy(dict(self.app.options.items()))
        ctx.filename = self.app.project_filename
        ctx.should_we_save = self.app.should_we_save
        ctx.view_rect = self._get_view_rect()

    def _load(self, ctx):
        """
        Put the state of the context into the App.
        """
        self.app.collection = ctx.collection
        if ctx.options:
            self.app.options.update(deepcopy(ctx.options))
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
        :param visuals: if False, the plots, the Properties UI and the plugins are not changed (used on exit)
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
        old = self.active
        if visuals:
            self.before_switch()
            self.deactivate(old)

        self.active = ctx
        self._load(ctx)

        if visuals:
            self.activate(ctx)

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

Run: `.venv/Scripts/python.exe tests/test_projects_manager.py`
Expected: `OK` (12 tests).

- [ ] **Step 5: Commit**

```bash
rtk git add appHandlers/appProjects.py tests/test_projects_manager.py
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

Run: `.venv/Scripts/python.exe tests/test_projects_manager.py`
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
        flag = self.app.should_we_save if ctx is self.active else ctx.should_we_save
        return bool(flag) and bool(ctx.collection.get_list())

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

Run: `.venv/Scripts/python.exe tests/test_projects_manager.py`
Expected: `OK` (27 tests).

- [ ] **Step 5: Commit**

```bash
rtk git add appHandlers/appProjects.py tests/test_projects_manager.py
rtk git commit -m "feat(projects): add new, rename, close and the save file rules to the ProjectManager"
```

---

### Task 5: `ProjectManager`: release and rebuild the plots and the Properties UI

This task fills the 5 empty methods of Task 3. These methods change the canvas, the Properties tab and the plugins.

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
        manager = ProjectManager(app, collection_factory=FakeCollection)
        return app, manager

    def test_deactivate_releases_shapes_and_ui(self):
        gerber = make_object('gerber')
        script = make_object('script')
        app, manager = self.make([gerber, script])

        manager.deactivate(manager.active)

        gerber.clear.assert_called_once_with(update=False)
        gerber.mark_shapes.clear.assert_called_once_with(update=False)
        self.assertIsNone(gerber._full_plot_sig)
        self.assertIsNone(gerber.ui)
        # Script and Document objects keep their UI and have no shapes
        script.clear.assert_not_called()
        self.assertIsNotNone(script.ui)
        app.setup_default_properties_tab.assert_called_once_with()
        app.plotcanvas.redraw.assert_called_once_with()

    def test_activate_rebuilds_ui_and_plots(self):
        gerber = make_object('gerber', with_ui=False)
        app, manager = self.make([gerber])
        manager.active.view_rect = 'saved-rect'

        manager.activate(manager.active)

        gerber.ui_type.assert_called_once_with(app=app)
        gerber.set_ui.assert_called_once_with('new-ui')
        gerber.build_ui.assert_called_once_with()
        app.init_tools.assert_called_once_with(init_tcl=False)
        app.plot_all.assert_called_once_with(fit_view=False)
        self.assertEqual(app.plotcanvas.view.camera.rect, 'saved-rect')

    def test_activate_of_an_empty_project_does_not_plot(self):
        app, manager = self.make([])
        manager.activate(manager.active)
        app.plot_all.assert_not_called()
        app.init_tools.assert_called_once_with(init_tcl=False)

    def test_activate_keeps_an_existing_ui(self):
        gerber = make_object('gerber', with_ui=True)
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

    def test_before_switch_closes_an_open_editor(self):
        app, manager = self.make([])
        app.call_source = 'geo_editor'
        app.on_editing_finished = Mock()
        app.tool_shapes = None
        app.hover_shapes = None
        app.exc_areas = None
        app.delete_selection_shape = Mock()
        manager.before_switch()
        app.on_editing_finished.assert_called_once_with(cleanup=True)
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/Scripts/python.exe tests/test_projects_manager.py`
Expected: 6 failures in `TestProjectManagerVisuals` (the methods are still empty).

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
    # these object kinds have no shapes on the canvas and a small UI, so they are not released
    KEEP_UI_KINDS = ('script', 'document')

    def reset_options(self):
        """
        A new project starts with the application defaults, the same as File -> New Project did before.
        """
        self.app.options.load(filename=self.app.defaults_path(), inform=self.app.inform)
        self.app.on_defaults2options()

    def before_switch(self):
        """
        Close the open editor and remove the canvas helpers of the current project.
        """
        app = self.app
        if getattr(app, 'call_source', 'app') != 'app':
            app.on_editing_finished(cleanup=True)

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
        Release the plot shapes and the Properties UI of the objects of a project. The geometry stays.
        """
        # the Properties tab can show the UI of an object of this project; replace it first
        self.app.setup_default_properties_tab()

        for obj in ctx.collection.get_list():
            if obj.kind in self.KEEP_UI_KINDS:
                continue
            try:
                obj.clear(update=False)
            except Exception as err:
                self.app.log.error("ProjectManager.deactivate() --> %s" % str(err))
            try:
                obj.mark_shapes.clear(update=False)
            except AttributeError:
                pass
            obj._full_plot_sig = None

            ui = obj.ui
            if ui is not None:
                obj.ui = None
                ui.deleteLater()

        self.app.plotcanvas.redraw()

    def activate(self, ctx):
        """
        Rebuild the Properties UI of the objects, re-create the plugins for the new collection and plot.
        """
        app = self.app
        for obj in ctx.collection.get_list():
            if obj.ui is not None:
                continue
            obj.set_ui(obj.ui_type(app=app))
            obj.build_ui()
        app.setup_default_properties_tab()

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

Run: `.venv/Scripts/python.exe tests/test_projects_manager.py`
Expected: `OK` (33 tests). The tests of Tasks 3 and 4 still pass because they replace these methods with `Mock`.

- [ ] **Step 5: Commit**

```bash
rtk git add appHandlers/appProjects.py tests/test_projects_manager.py
rtk git commit -m "feat(projects): release the shapes and the Properties UI of an inactive project"
```

---

### Task 6: `ProjectManager`: dialogs, open, close request and save

This task adds the methods that show dialogs. Each dialog is 1 method, so a test can replace it with a `Mock`.

**Files:**
- Modify: `appHandlers/appProjects.py`
- Test: `tests/test_projects_manager.py` (add tests)

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
        app.f_handlers = SimpleNamespace(save_project=Mock())
        manager.rename(manager.active, 'Board_B')

        self.assertTrue(manager.save_context(manager.active))

        target = self.path('Board_B.FlatPrj')
        app.f_handlers.save_project.assert_called_once_with(target, silent=True)
        self.assertEqual(app.project_filename, target)
        self.assertFalse(app.should_we_save)
        self.assertFalse(app.save_in_progress)

    def test_save_context_asks_before_it_overwrites(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        app.project_filename = self.path('Project_1.FlatPrj')
        app.f_handlers = SimpleNamespace(save_project=Mock())
        manager.rename(manager.active, 'Board_B')
        with open(self.path('Board_B.FlatPrj'), 'w') as stream:
            stream.write('x')
        manager.ask_yes_no = Mock(return_value=False)

        self.assertFalse(manager.save_context(manager.active))
        app.f_handlers.save_project.assert_not_called()

    def test_save_context_without_file_asks_for_a_path(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        app.f_handlers = SimpleNamespace(save_project=Mock())
        manager.ask_save_path = Mock(return_value=self.path('Chosen.FlatPrj'))

        self.assertTrue(manager.save_context(manager.active))

        app.f_handlers.save_project.assert_called_once_with(self.path('Chosen.FlatPrj'), silent=True)
        self.assertEqual(manager.active.name, 'Chosen')

    def test_save_context_without_file_cancelled(self):
        app, manager = make_manager(make_app(FakeCollection([object()])))
        app.f_handlers = SimpleNamespace(save_project=Mock())
        manager.ask_save_path = Mock(return_value='')
        self.assertFalse(manager.save_context(manager.active))
        app.f_handlers.save_project.assert_not_called()
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/Scripts/python.exe tests/test_projects_manager.py`
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
            answer = self.ask_save(ctx)
            if answer == 'cancel':
                return False
            if answer == 'yes' and not self.save_context(ctx):
                return False
        return self.close(ctx, force=True)

    def save_context(self, ctx, visuals=True):
        """
        Save a project now, in this thread. If the project is not active, it becomes active first.

        :return:    True if the file is written
        """
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

        self.app.f_handlers.save_project(path, silent=True)
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

Run: `.venv/Scripts/python.exe tests/test_projects_manager.py`
Expected: `OK` (45 tests).

- [ ] **Step 5: Commit**

```bash
rtk git add appHandlers/appProjects.py tests/test_projects_manager.py
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

Run: `.venv/Scripts/python.exe tests/test_projects_manager.py`
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

Run: `.venv/Scripts/python.exe tests/test_projects_manager.py`
Expected: `OK` (48 tests).

Also run: `.venv/Scripts/python.exe tests/test_titlebar.py`
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

Run: `.venv/Scripts/python.exe tests/test_project_selector.py`
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

Run: `.venv/Scripts/python.exe tests/test_project_selector.py`
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

Run: `.venv/Scripts/python.exe tests/test_app_refactor_integration.py`
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
        self.app = SimpleNamespace(
            log=Mock(), inform=Mock(), splash=Mock(), options={}, defaults=Defaults(), app_units='MM',
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

Run: `.venv/Scripts/python.exe tests/test_projects_appio.py`
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

Run: `.venv/Scripts/python.exe tests/test_projects_appio.py`
Expected: `OK` (4 tests).

Also run: `.venv/Scripts/python.exe tests/test_project_load_cleanup.py`
Expected: `OK`. This test uses an app without `projects`, so the `getattr` guard must work.

- [ ] **Step 7: Commit**

```bash
rtk git add appHandlers/appIO.py tests/test_projects_appio.py
rtk git commit -m "feat(projects): File New and File Open add a project to the Project tab"
```

---

### Task 10: Save and Save As use the project name

**Files:**
- Modify: `appHandlers/appIO.py`: `on_file_save_project` (about line 1405), `on_file_save_project_as` (about line 1428)
- Test: `tests/test_projects_appio.py` (add tests)

- [ ] **Step 1: Write the failing tests**

In `tests/test_projects_appio.py`, add this class before `if __name__ == '__main__':`:

```python
class TestSave(AppIOTestBase):
    def test_save_after_rename_writes_the_new_file(self):
        self.app.project_filename = self.path('Board_A.FlatPrj')
        self.projects.save_target.return_value = self.path('Board_B.FlatPrj')

        self.io.on_file_save_project()

        self.assertEqual(self.tasks[-1]['params'][0], self.path('Board_B.FlatPrj'))
        self.assertEqual(self.app.project_filename, self.path('Board_B.FlatPrj'))
        self.projects.adopt_filename.assert_called_once_with(self.path('Board_B.FlatPrj'))

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
        self.assertEqual(self.app.project_filename, chosen)
        self.projects.adopt_filename.assert_called_once_with(chosen)
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/Scripts/python.exe tests/test_projects_appio.py`
Expected: failures in `TestSave`.

- [ ] **Step 3: Change `on_file_save_project`**

In `appHandlers/appIO.py`, in `on_file_save_project`, find:

```python
        self.log.debug("on_file_save_project()")

        if self.app.project_filename is None:
            self.on_file_save_project_as()
        else:
```

Replace it with:

```python
        self.log.debug("on_file_save_project()")

        # after a rename, the project is saved as '<new name>.FlatPrj' in the same folder; the old file stays
        projects = getattr(self.app, 'projects', None)
        if projects is not None and self.app.project_filename is not None:
            target = projects.save_target()
            if target and not same_path(target, self.app.project_filename):
                if os.path.exists(target) and not projects.ask_yes_no(
                        _("Overwrite"), '%s: %s\n%s' % (_("The file already exists"), target,
                                                        _("Do you want to overwrite it?"))):
                    self.inform.emit('[WARNING_NOTCL] %s' % _("Cancelled."))
                    return
                self.app.project_filename = target
                projects.adopt_filename(target)

        if self.app.project_filename is None:
            self.on_file_save_project_as()
        else:
```

At the top of `appHandlers/appIO.py`, after the line `from appGUI.GUIElements import FCFileSaveDialog, FCMessageBox, add_case_variants`, add:

```python
from appObjects.ProjectContext import same_path
```

- [ ] **Step 4: Change `on_file_save_project_as`**

In `on_file_save_project_as`, find:

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

In the same method, find:

```python
        if not make_copy:
            self.app.project_filename = filename
```

Replace it with:

```python
        if not make_copy:
            self.app.project_filename = filename
            if projects is not None:
                projects.adopt_filename(filename)
```

- [ ] **Step 5: Run the tests and see them pass**

Run: `.venv/Scripts/python.exe tests/test_projects_appio.py`
Expected: `OK` (8 tests).

Also run: `.venv/Scripts/python.exe tests/test_project_load_cleanup.py`
Expected: `OK`.

- [ ] **Step 6: Commit**

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
                                   switch=Mock(return_value=True))
        app = SimpleNamespace(save_in_progress=False, projects=projects, trayIcon=Mock(),
                              inform=Mock(), log=Mock())
        lifecycle = AppLifecycle.__new__(AppLifecycle)
        lifecycle.app = app
        lifecycle.inform = app.inform
        lifecycle.quit_application = Mock()
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
        projects.switch.assert_called_once_with(start, visuals=False)

    def test_failed_save_stops_the_exit(self):
        first = SimpleNamespace(name='A')
        lifecycle, projects, start = self.make_lifecycle([first])
        projects.ask_save.return_value = 'yes'
        projects.save_context.return_value = False
        lifecycle.final_save()
        lifecycle.quit_application.assert_not_called()
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv/Scripts/python.exe tests/test_projects_manager.py`
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
        if self.app.save_in_progress:
            self.inform.emit('[WARNING_NOTCL] %s' % _("Application is saving the project. Please wait ..."))
            return

        # with more than 1 project, ask about each project that has unsaved changes
        projects = getattr(self.app, 'projects', None)
        if projects is not None:
            start = projects.active
            for ctx in projects.dirty_contexts():
                answer = projects.ask_save(ctx)
                if answer == 'cancel' or (answer == 'yes' and not projects.save_context(ctx, visuals=False)):
                    # the exit stops; show the project that was active before
                    projects.switch(start, visuals=False)
                    return
            try:
                self.app.trayIcon.hide()
            except Exception:
                pass
            self.quit_application()
            return

        if self.app.should_we_save and self.app.collection.get_list():
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `.venv/Scripts/python.exe tests/test_projects_manager.py`
Expected: `OK` (52 tests).

Also run: `.venv/Scripts/python.exe tests/test_shutdown_routing.py`
Expected: `OK`.

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

Run: `.venv/Scripts/python.exe tests/test_tcl_projects.py`
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

Run: `.venv/Scripts/python.exe tests/test_tcl_projects.py`
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

In `CHANGELOG.md`, the newest date block is at the top, below the line `CHANGELOG for FlatCAM Evo beta`. If a block `18.10.2026` with a `GUI:` section exists, add this line at the end of the `GUI:` list. If no block for today exists, make a new date block with today's date in the same format, with a `GUI:` section.

```markdown
- the Project tab can hold more than 1 project: a Project combobox above the tree selects the active project; a right-click on the combobox has New Project, Open Project, Rename Project and Close Project; an inactive project keeps its geometry but releases its plots and its Properties UI; File New and File Open add a project; after a rename, Save writes '<new name>.FlatPrj' in the same folder and the title bar shows the project name; exit asks about each project with unsaved changes; new Tcl commands list_projects, select_project and close_project
```

- [ ] **Step 2: Run all the new test files**

Run each command. Each one must show `OK`:

```bash
.venv/Scripts/python.exe tests/test_project_context.py
.venv/Scripts/python.exe tests/test_projects_manager.py
.venv/Scripts/python.exe tests/test_project_selector.py
.venv/Scripts/python.exe tests/test_projects_appio.py
.venv/Scripts/python.exe tests/test_tcl_projects.py
```

- [ ] **Step 3: Run the full test suite 1 time**

Run: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"`
Expected: `OK`. This takes about 4 minutes. If a test fails, compare with the result on the commit before Task 1 (`rtk git stash` is not needed; use `rtk git log --oneline -15` to find that commit and report the failing test names). Report the failures. Do not fix tests that were already failing before Task 1.

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
9. Change a preference in Project A, for example the units. Switch to Project B. The preference has the value of Project B.
10. In the Tcl shell: `list_projects`, `select_project Board_A`, `close_project Board_A` (with unsaved changes: error), `close_project Board_A -force 1`.
11. Make changes in 2 projects. Close the app. The app asks about each project by name.
12. Check the RAM in Task Manager: open a big project, add a second project and switch to it. The RAM of the app goes down or stays the same. It does not double.

---

## Known limits (do not fix in this plan)

- A switch re-creates all plugins (`init_tools`), the same as File > New Project. If the GRBL Sender has an open serial connection, a switch closes that connection.
- Autosave saves only the active project.
- The Code Editor tabs of Script and Document objects stay open after a switch.
- The Tcl commands `new` and `open_project` replace the active project. They do not add a project.
