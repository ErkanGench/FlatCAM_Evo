# Split of Application Settings and Project Options — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `app.defaults` holds the application settings. `app.options` stores only the project options and reads and writes the application settings through `app.defaults`.

**Architecture:** A rule function `is_project_key(key)` in `defaults.py` decides the kind of each key. `AppOptions` gets an optional link to the live `AppDefaults` and becomes a merged view. The project file, a new project and the Preferences window use the rule.

**Tech Stack:** Python 3.11, PyQt6, `unittest` and `pytest`.

**Spec:** `docs/superpowers/specs/2026-10-18-options-defaults-split-design.md`

---

## Rules for the agent

- Work on the local branch `1.0`. Do not push. Do not create a branch.
- Do not add `docs/mach3/` to a commit.
- Do not add a `Co-Authored-By` line or any Claude attribution to a commit message.
- Prefix each shell command with `rtk`. Example: `rtk git status`.
- The Python of the project is `.venv/Scripts/python.exe`. Run commands from the repository root.
- Run only the test files that the task names. Do not run the full test suite, except in Task 6.
- Do not change code that the task does not name.

## Clarifications to the spec

1. The spec names a method `project_items()`. This plan uses a module function `project_options(options)` in `defaults.py`. It works on an `AppOptions` and on a plain `dict`. Many tests give `app.options` as a plain `dict`, so `save_project` must work with both.
2. `AppOptions.load()` gets a new argument `include_app_keys=False`. File > New calls `load()` with the default value, so only the project keys load. Edit > Import Preferences calls it with `True`, so the application keys of the file go into `app.defaults`. Before this change the import put all keys into `app.options`, which was the place where the app read them.
3. The Preferences form is written again when the Preferences tab opens, if it has no unsaved edits. This keeps the form correct after a project opens from Tcl, where the app does not write the form.
4. "Restore Defaults" in Preferences shows the values of `app.defaults` for all keys. "Close without save" restores `app.defaults` first and then writes the form.

## File map

| File | Change |
|---|---|
| `defaults.py` | New `PROJECT_KEYS`, `APP_TOOL_PREFIXES`, `APP_TOOL_SUFFIXES`, `APP_TOOL_KEYS`, `is_project_key()`, `project_options()`. `AppOptions` becomes a merged view. |
| `appMain.py` | `AppOptions(...)` gets `defaults=self.defaults`. The copy loop after it is removed. |
| `appHandlers/appIO.py` | `save_project`, `_restore_project_handler`, `on_import_preferences`. |
| `appHandlers/appLifecycle.py` | `on_defaults2options`. |
| `appGUI/preferences/PreferencesUIManager.py` | `_source`, `defaults_write_form_field`, `defaults_read_form`, `show_preferences_gui`, `on_save_button`, `on_restore_defaults_preferences`, `on_pref_close_button`. |
| `tests/test_options_split.py` | New. |
| `tests/test_preferences_project_keys.py` | New. |
| `tests/test_vispy_only_settings.py`, `tests/test_unify_characterization.py`, `tests/test_app_refactor_characterization.py`, `tests/test_app_handler_characterization.py`, `tests/test_theme_color_scheme.py` | Updated tests. |
| `CHANGELOG.md` | New entries. |

---

### Task 1: The key rule

**Files:**
- Modify: `defaults.py` (add code after the line `_MISSING = object()`, line 22)
- Create: `tests/test_options_split.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_options_split.py` with this content:

```python
"""Tests for the split of application settings and project options."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from defaults import AppDefaults, APP_TOOL_KEYS, PROJECT_KEYS, is_project_key


class TestIsProjectKey(unittest.TestCase):
    def test_named_project_keys(self):
        for key in ('units', 'gerber_noncoppermargin', 'gerber_noncopperrounded', 'gerber_bboxmargin',
                    'gerber_bboxrounded', 'gerber_follow', 'excellon_drill_tooldia', 'excellon_slot_tooldia',
                    'geometry_seg_x', 'geometry_seg_y'):
            self.assertTrue(is_project_key(key), key)

    def test_tools_keys_are_project_keys(self):
        for key in ('tools_iso_tooldia', 'tools_drill_ppname_e', 'tools_mill_ppname_g', 'tools_ncc_operation'):
            self.assertTrue(is_project_key(key), key)

    def test_tools_application_exceptions(self):
        for key in ('tools_grbl_travelz', 'tools_calc_vshape_tip_dia', 'tools_iso_plotting',
                    'tools_dist_big_cursor', 'tools_drill_preprocessor_list', 'tools_al_controller',
                    'tools_gcode_fit_view', 'tools_dist_snap_center', 'tools_opt_precision',
                    'tools_qrcode_sel_limit'):
            self.assertFalse(is_project_key(key), key)

    def test_other_keys_are_application_keys(self):
        for key in ('global_gridx', 'global_workspace', 'global_appearance', 'cncjob_tooldia',
                    'excellon_optimization_type', 'gerber_plot', 'units_precision', 'first_run',
                    'root_folder_path', None, 5):
            self.assertFalse(is_project_key(key), key)

    def test_listed_keys_exist_in_factory_defaults(self):
        for key in PROJECT_KEYS | APP_TOOL_KEYS:
            self.assertIn(key, AppDefaults.factory_defaults, key)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run the test to see it fail**

Run: `rtk .venv/Scripts/python.exe tests/test_options_split.py`
Expected: FAIL with `ImportError: cannot import name 'APP_TOOL_KEYS' from 'defaults'`.

- [ ] **Step 3: Add the rule**

In `defaults.py`, after the line `_MISSING = object()`, add:

```python


# Keys outside the "tools_" family that belong to the project.
PROJECT_KEYS = frozenset((
    'units',
    'gerber_noncoppermargin', 'gerber_noncopperrounded', 'gerber_bboxmargin', 'gerber_bboxrounded',
    'gerber_follow',
    'excellon_drill_tooldia', 'excellon_slot_tooldia',
    'geometry_seg_x', 'geometry_seg_y',
))
# "tools_" keys that belong to the application.
APP_TOOL_PREFIXES = ('tools_grbl_', 'tools_calc_')
APP_TOOL_SUFFIXES = ('_plotting', '_big_cursor', '_preprocessor_list')
APP_TOOL_KEYS = frozenset((
    'tools_al_controller', 'tools_gcode_fit_view', 'tools_dist_snap_center',
    'tools_opt_precision', 'tools_qrcode_sel_limit',
))


def is_project_key(key):
    """Return True if the key is a project option, False if it is an application setting."""
    if key in PROJECT_KEYS:
        return True
    if not isinstance(key, str) or not key.startswith('tools_'):
        return False
    if key.startswith(APP_TOOL_PREFIXES) or key.endswith(APP_TOOL_SUFFIXES):
        return False
    return key not in APP_TOOL_KEYS


def project_options(options):
    """Return a dict with only the project keys of "options", for the project file."""
    return {k: v for k, v in options.items() if is_project_key(k)}
```

- [ ] **Step 4: Run the test to see it pass**

Run: `rtk .venv/Scripts/python.exe tests/test_options_split.py`
Expected: `OK` (5 tests).

- [ ] **Step 5: Commit**

```bash
rtk git add defaults.py tests/test_options_split.py
rtk git commit -m "feat(options): add the rule that sorts project keys and application keys"
```

---

### Task 2: `AppOptions` as a merged view

**Files:**
- Modify: `defaults.py` (class `AppOptions`, starts at about line 1200 after Task 1)
- Modify: `appMain.py:860-867`
- Modify: `tests/test_options_split.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_options_split.py`:

1. Change the import line `from defaults import AppDefaults, APP_TOOL_KEYS, PROJECT_KEYS, is_project_key` to:

```python
from defaults import AppDefaults, AppOptions, APP_TOOL_KEYS, PROJECT_KEYS, is_project_key, project_options
```

2. Add this class before the line `if __name__ == '__main__':`:

```python
class TestAppOptionsMergedView(unittest.TestCase):
    def make(self):
        defaults = AppDefaults(beta=False)
        calls = []
        options = AppOptions(version='test', callback=calls.append, baseline=defaults, defaults=defaults)
        return defaults, options, calls

    def test_storage_holds_only_project_keys(self):
        _defaults, options, _calls = self.make()
        self.assertIn('units', options.options)
        self.assertNotIn('global_gridx', options.options)
        self.assertTrue(all(is_project_key(key) for key in options.options))

    def test_application_key_reads_and_writes_defaults(self):
        defaults, options, calls = self.make()
        options['global_gridx'] = 7.5
        self.assertEqual(defaults['global_gridx'], 7.5)
        self.assertEqual(options['global_gridx'], 7.5)
        self.assertEqual(options.get('global_gridx'), 7.5)
        self.assertIn('global_gridx', options)
        self.assertEqual(calls, ['global_gridx'])
        defaults['global_gridx'] = 3.0
        self.assertEqual(options['global_gridx'], 3.0)

    def test_project_key_stays_in_own_storage(self):
        defaults, options, calls = self.make()
        before = defaults['gerber_bboxmargin']
        options['gerber_bboxmargin'] = before + 1.0
        self.assertEqual(options['gerber_bboxmargin'], before + 1.0)
        self.assertEqual(defaults['gerber_bboxmargin'], before)
        self.assertEqual(calls, ['gerber_bboxmargin'])

    def test_unchanged_value_does_not_call_back(self):
        defaults, options, calls = self.make()
        options['global_gridx'] = defaults['global_gridx']
        options['units'] = options['units']
        self.assertEqual(calls, [])

    def test_loop_and_items_see_all_keys(self):
        defaults, options, _calls = self.make()
        self.assertEqual(set(options), set(defaults))
        self.assertEqual(set(options.keys()), set(defaults))
        self.assertEqual(len(options), len(list(defaults)))
        merged = dict(options.items())
        self.assertEqual(merged['global_gridx'], defaults['global_gridx'])
        self.assertEqual(options.copy(), merged)
        self.assertEqual(len(options.values()), len(merged))

    def test_update_setdefault_pop_go_to_the_right_place(self):
        defaults, options, _calls = self.make()
        options.update({'global_gridx': 9.0, 'gerber_bboxmargin': 4.0})
        self.assertEqual(defaults['global_gridx'], 9.0)
        self.assertEqual(options.options['gerber_bboxmargin'], 4.0)
        options.update(global_gridy=8.0)
        self.assertEqual(defaults['global_gridy'], 8.0)
        self.assertEqual(options.setdefault('global_new_test_key', 1), 1)
        self.assertEqual(defaults['global_new_test_key'], 1)
        self.assertEqual(options.pop('global_new_test_key'), 1)
        self.assertNotIn('global_new_test_key', options)
        self.assertIsNone(options.pop('global_missing_test_key', None))

    def test_project_options_has_only_project_keys(self):
        _defaults, options, _calls = self.make()
        saved = project_options(options)
        self.assertIn('units', saved)
        self.assertNotIn('global_gridx', saved)
        self.assertTrue(all(is_project_key(key) for key in saved))
        self.assertEqual(project_options({'units': 'MM', 'global_gridx': 1}), {'units': 'MM'})

    def test_reset_from_defaults(self):
        defaults, options, _calls = self.make()
        options['gerber_bboxmargin'] = 99.0
        defaults['gerber_bboxmargin'] = 0.25
        options.reset_from_defaults()
        self.assertEqual(options['gerber_bboxmargin'], 0.25)

    def test_reset_from_defaults_copies_values(self):
        defaults, options, _calls = self.make()
        defaults['tools_test_list'] = [1, 2]
        options.reset_from_defaults()
        options['tools_test_list'].append(3)
        self.assertEqual(defaults['tools_test_list'], [1, 2])

    def test_load_project_ignores_application_keys(self):
        defaults, options, _calls = self.make()
        appearance = defaults['global_appearance']
        options['gerber_bboxrounded'] = not defaults['gerber_bboxrounded']
        options.load_project({'global_appearance': 'not-a-theme', 'gerber_bboxmargin': 0.75,
                              'global_graphic_engine': '2D'})
        self.assertEqual(defaults['global_appearance'], appearance)
        self.assertEqual(options['gerber_bboxmargin'], 0.75)
        self.assertEqual(options['gerber_bboxrounded'], defaults['gerber_bboxrounded'])
        self.assertNotIn('global_graphic_engine', options)

    def test_load_keeps_only_project_keys_unless_asked(self):
        defaults, options, _calls = self.make()
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'prefs.FlatConfig')
            with open(path, 'w') as f:
                json.dump({'global_gridx': 42.0, 'gerber_bboxmargin': 0.5}, f)
            options.load(path, Mock())
            self.assertEqual(options['gerber_bboxmargin'], 0.5)
            self.assertNotEqual(defaults['global_gridx'], 42.0)
            options.load(path, Mock(), include_app_keys=True)
            self.assertEqual(defaults['global_gridx'], 42.0)
        self.assertTrue(all(is_project_key(key) for key in options.options))

    def test_without_defaults_link_works_as_before(self):
        options = AppOptions(version='test', baseline={'global_gridx': 1.0, 'units': 'MM'})
        self.assertEqual(dict(options.options), {'global_gridx': 1.0, 'units': 'MM'})
        options['global_gridx'] = 2.0
        self.assertEqual(options.options['global_gridx'], 2.0)
        self.assertEqual(set(options), {'global_gridx', 'units'})
        self.assertEqual(options.get('missing', 5), 5)
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `rtk .venv/Scripts/python.exe tests/test_options_split.py`
Expected: FAIL. The new tests show `TypeError: AppOptions.__init__() got an unexpected keyword argument 'defaults'`.

- [ ] **Step 3: Replace the class `AppOptions`**

In `defaults.py`, replace the whole class `AppOptions` (from the line `class AppOptions:` to the end of its `load` method, the line `self.current_options = deepcopy(dict(self.options))`) with this code:

```python
# A marker for a missing key. Do not use _MISSING for this: AppDefaults.get(key, _MISSING) returns the factory value.
_ABSENT = object()


class AppOptions:
    def __init__(self, version, callback=lambda x: None, baseline=None, defaults=None):
        """
        Class that holds the options parameters used throughout the app.

        :param callback:    A method called each time that one of the values are changed in the self.defaults LouDict
        :param baseline:    The values used to fill the options at the start
        :param defaults:    The live AppDefaults. If it is set, only the project keys are stored here and the
                            application keys are read from and written to "defaults".
        """
        self.options = LoudDict()
        self.current_options = {}  # copy used for restoring after cancelled prefs changes
        self.version = version
        self.app_defaults = defaults
        self.baseline = deepcopy(dict(baseline)) if baseline is not None else deepcopy(AppDefaults.factory_defaults)
        self.baseline.pop('global_graphic_engine', None)
        if baseline is not None:
            self.options.update(deepcopy(self._own(self.baseline)))
            self.current_options = deepcopy(dict(self.options))
        # set after the first fill, so the callback runs only for later changes
        self.options.set_change_callback(callback)

    def _is_app_key(self, key):
        """Return True if "key" is read from and written to the linked defaults."""
        return self.app_defaults is not None and not is_project_key(key)

    def _own(self, values):
        """Return the part of "values" that this object stores itself."""
        if self.app_defaults is None:
            return dict(values)
        return {k: v for k, v in values.items() if is_project_key(k)}

    # #### Pass-through to the defaults LoudDict #####
    def __len__(self):
        return len(self.keys())

    def __getitem__(self, item):
        if self._is_app_key(item):
            return self.app_defaults[item]
        return self.options.__getitem__(item)

    def __setitem__(self, key, value):
        if self._is_app_key(key):
            current = self.app_defaults.get(key, _ABSENT)
            if current is not _ABSENT and current == value:
                return
            self.app_defaults[key] = value
            self.options.callback(key)
            return
        return self.options.__setitem__(key, value)

    def __delitem__(self, key):
        if self._is_app_key(key):
            del self.app_defaults[key]
            return
        return self.options.__delitem__(key)

    def __contains__(self, key):
        if self._is_app_key(key):
            return self.app_defaults.get(key, _ABSENT) is not _ABSENT
        return key in self.options

    def __iter__(self):
        return iter(self.keys())

    def __getattr__(self, item):
        # Unfortunately this method alone is not enough to pass through the other magic methods above.
        return self.options.__getattribute__(item)

    def keys(self):
        if self.app_defaults is None:
            return self.options.keys()
        return list(self.options.keys()) + [k for k in self.app_defaults if not is_project_key(k)]

    def items(self):
        if self.app_defaults is None:
            return self.options.items()
        return [(k, self[k]) for k in self.keys()]

    def values(self):
        if self.app_defaults is None:
            return self.options.values()
        return [self[k] for k in self.keys()]

    def copy(self):
        return dict(self.items())

    def update(self, *args, **kwargs):
        if len(args) > 1:
            raise TypeError("update expected at most 1 arguments, got %d" % len(args))
        other = dict(*args, **kwargs)
        for key in other:
            self[key] = other[key]

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]

    def pop(self, key, *default):
        if self._is_app_key(key):
            return self.app_defaults.pop(key, *default)
        return self.options.pop(key, *default)

    def get(self, key, default=_MISSING):
        """Return an option or its copied baseline when the option is missing."""
        if key in self:
            return self[key]
        if default is not _MISSING:
            return default
        return deepcopy(self.baseline.get(key))

    def reset_from_defaults(self):
        """Copy each project key from the linked defaults, or from the baseline if no defaults are linked."""
        source = self.app_defaults if self.app_defaults is not None else self.baseline
        for key in list(source):
            if is_project_key(key):
                self.options[key] = deepcopy(source[key])

    def load_project(self, project_options):
        """Set the project keys from a project file. The application keys in the file are ignored."""
        self.reset_from_defaults()
        for key, value in project_options.items():
            if is_project_key(key):
                self.options[key] = value

    def load(self, filename: str, inform, baseline=None, include_app_keys=False):
        """
        Loads the options from a file on disk, performing migration if required.

        :param filename:            a path to the file that is to be loaded
        :param inform:              a pyqtSignal used to display information's in the StatusBar of the GUI
        :param baseline:            the values used for the keys that the file does not have
        :param include_app_keys:    if defaults are linked, also write the application keys of the file
                                    into the defaults
        """

        # Read in the file
        try:
            f = open(filename)
            options = f.read()
            f.close()
        except IOError:
            log.error("Could not load defaults file.")
            inform.emit('[ERROR] %s' % _("Could not load the file."))
            return

        # Parse the JSON
        try:
            options = simplejson.loads(options)
        except Exception:
            # in case the defaults file can't be loaded, show all toolbars
            log.error(str(sys.exc_info()[0]))
            inform.emit('[ERROR] %s' % _("Failed to parse defaults file."))
            return
        if options is None:
            return

        if baseline is not None:
            self.baseline = deepcopy(dict(baseline))
        self.baseline.pop('global_graphic_engine', None)
        options.pop('global_graphic_engine', None)

        # Save the resulting defaults
        self.options.clear()
        self.options.update(deepcopy(self._own(self.baseline)))
        if self.app_defaults is None:
            self.options.update(options)
        else:
            for key, value in options.items():
                if is_project_key(key):
                    self.options[key] = value
                elif include_app_keys:
                    self[key] = value
        self.current_options = deepcopy(dict(self.options))
```

Note: `__setitem__` and `__contains__` read `self.app_defaults.get(key, _ABSENT)`. Do not change this to `key in self.app_defaults`. `AppDefaults` has no `__contains__`, so `in` makes a slow loop over all keys. Do not change `_ABSENT` to `_MISSING`. For `_MISSING`, `AppDefaults.get` returns the factory value (`None` for an unknown key), so a missing key looks present.

- [ ] **Step 4: Run the tests to see them pass**

Run: `rtk .venv/Scripts/python.exe tests/test_options_split.py`
Expected: `OK` (17 tests).

- [ ] **Step 5: Link the app options to the defaults**

In `appMain.py`, find these lines (about line 859-867):

```python
        # ######################################## UPDATE THE OPTIONS ###############################################
        self.options = AppOptions(version=self.version, baseline=self.defaults)
        # -----------------------------------------------------------------------------------------------------------
        #   Update the self.options from the self.defaults
        #   The self.options holds the application defaults while the self.options holds the object defaults
        # -----------------------------------------------------------------------------------------------------------
        # Copy app defaults to project options
        for def_key, def_val in self.defaults.items():
            self.options[def_key] = deepcopy(def_val)
```

Replace them with:

```python
        # ######################################## UPDATE THE OPTIONS ###############################################
        # The options store only the project keys. They read and write the application keys in self.defaults.
        self.options = AppOptions(version=self.version, baseline=self.defaults, defaults=self.defaults)
```

Do not remove the `deepcopy` import of `appMain.py`. Other code in the file uses it.

- [ ] **Step 6: Run the existing tests of `AppOptions`**

Run each command:

```bash
rtk .venv/Scripts/python.exe tests/test_options_split.py
rtk .venv/Scripts/python.exe -m pytest tests/test_vispy_only_settings.py -q -k "settings_migration or only_shape"
rtk .venv/Scripts/python.exe -m pytest tests/updater/test_ticket6.py tests/test_defaults_audit_regressions.py -q
```

Expected: all pass. The test `test_project_settings_import` in `tests/test_vispy_only_settings.py` is not run here. Task 3 changes it.

- [ ] **Step 7: Commit**

```bash
rtk git add defaults.py appMain.py tests/test_options_split.py
rtk git commit -m "feat(options): make AppOptions a merged view that keeps the application keys in defaults"
```

---

### Task 3: The project file

**Files:**
- Modify: `appHandlers/appIO.py` (`save_project` at about line 3156, `_restore_project_handler` at about lines 2968-2998, `on_import_preferences` at about line 1803)
- Modify: `tests/test_vispy_only_settings.py:37-59`
- Modify: `tests/test_unify_characterization.py` (add 1 test)

- [ ] **Step 1: Write the failing tests**

1. In `tests/test_vispy_only_settings.py`, replace the whole function `test_project_settings_import` (the `@pytest.mark.parametrize('cli,accept', ...)` line and the function under it, lines 37-59) with:

```python
@pytest.mark.parametrize('cli', [False, True])
def test_project_open_loads_only_project_options(cli):
    from PyQt6 import QtWidgets
    from appHandlers.appIO import appIO

    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    defaults = AppDefaults(beta=False)
    defaults['global_appearance'] = 'light'
    app = MagicMock()
    app.defaults = defaults
    app.options = AppOptions(version='test', baseline=defaults, defaults=defaults)
    app.resource_location = 'assets/resources'
    handler = SimpleNamespace(app=app, on_file_new_project=MagicMock())
    project = {'objs': [], 'options': {'global_graphic_engine': '2D', 'global_appearance': 'dark',
                                     'gerber_bboxmargin': 0.75}}
    with patch('appHandlers.appIO.FCMessageBox') as message:
        assert appIO._restore_project_handler(handler, project, 'board.FlatPrj',
                                             True, True, cli, False) is True
    message.assert_not_called()
    assert defaults['global_appearance'] == 'light'
    assert app.options['global_appearance'] == 'light'
    assert app.options['gerber_bboxmargin'] == 0.75
    assert app.options['gerber_bboxrounded'] == defaults['gerber_bboxrounded']
    assert 'global_graphic_engine' not in list(defaults)
    assert app.preferencesUiManager.defaults_write_form.called is (not cli)
    assert project['options']['global_graphic_engine'] == '2D'
```

2. In `tests/test_unify_characterization.py`, add this test after the function `save_and_load` (after its line `return proj, restored`):

```python


def test_saved_project_has_only_project_options(tmp_path):
    from defaults import is_project_key
    app = make_app()
    proj, _restored = save_and_load(app, [], tmp_path)
    assert 'units' in proj['options']
    assert 'global_save_compressed' not in proj['options']
    assert all(is_project_key(key) for key in proj['options'])
```

- [ ] **Step 2: Run the tests to see them fail**

Run:

```bash
rtk .venv/Scripts/python.exe -m pytest tests/test_vispy_only_settings.py -q -k project_open
rtk .venv/Scripts/python.exe -m pytest tests/test_unify_characterization.py -q -k saved_project_has_only
```

Expected: both FAIL. The first fails on `message.assert_not_called()`. The second fails on `'global_save_compressed' not in proj['options']`.

- [ ] **Step 3: Save only the project keys**

In `appHandlers/appIO.py`, in `save_project`, replace:

```python
            app_options = {k: v for k, v in self.app.options.items()}
```

with:

```python
            # Only the project keys go into the project file. The application settings stay in the defaults.
            app_options = project_options(self.app.options)
```

At the top of `appHandlers/appIO.py`, after the line `from camlib import to_dict, dict2obj, ET, ParseError` (line 10), add:

```python
from defaults import project_options
```

- [ ] **Step 4: Load the project keys without the question**

In `appHandlers/appIO.py`, in `_restore_project_handler`, replace this block (from `if not run_from_arg or not cli or from_tcl is False:` after `self.on_file_new_project()`, to the line before `self.app.project_filename = filename`):

```python
        if not run_from_arg or not cli or from_tcl is False:
            msgbox = FCMessageBox(parent=self.app.ui)
            title = _("Import Settings")
            ...
        else:
            # Load by default new options when not using GUI
            # Project options
            self.app.options.update({k: v for k, v in proj_dict['options'].items()
                                     if k != 'global_graphic_engine'})
```

with:

```python
        # Project options. The application settings in the file are ignored.
        self.app.options.load_project(proj_dict['options'])
        if not run_from_arg or not cli or from_tcl is False:
            # Show the options of the loaded project in the Preferences form.
            self.app.preferencesUiManager.defaults_write_form()
```

Make sure that the first `if not run_from_arg or not cli or from_tcl is False:` block of the method (the "Legacy Project" message box at the top) does not change. Only the second block, with the title "Import Settings", is replaced.

- [ ] **Step 5: Import Preferences writes the application keys to the defaults**

In `appHandlers/appIO.py`, in `on_import_preferences`, replace:

```python
        # Load in the options from the chosen file
        self.options.load(filename=filename, inform=self.inform, baseline=self.app.defaults)
```

with:

```python
        # Load in the options from the chosen file. The application settings go into the defaults.
        self.options.load(filename=filename, inform=self.inform, baseline=self.app.defaults, include_app_keys=True)
        self.app.preferencesUiManager.defaults_write_form()
```

- [ ] **Step 6: Run the tests to see them pass**

Run:

```bash
rtk .venv/Scripts/python.exe -m pytest tests/test_vispy_only_settings.py -q
rtk .venv/Scripts/python.exe -m pytest tests/test_unify_characterization.py -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
rtk git add appHandlers/appIO.py tests/test_vispy_only_settings.py tests/test_unify_characterization.py
rtk git commit -m "feat(project): save and load only the project options, remove the Import Settings question"
```

---

### Task 4: A new project gets its options from the defaults

**Files:**
- Modify: `appHandlers/appLifecycle.py` (`on_defaults2options`, about line 582)
- Modify: `tests/test_app_refactor_characterization.py:201-216`
- Modify: `tests/test_app_handler_characterization.py:533` and `:552-556`

- [ ] **Step 1: Change the tests**

1. In `tests/test_app_refactor_characterization.py`, replace the whole method `test_defaults_are_read_before_project_options_update` (lines 201-216) with:

```python
    def test_new_project_options_come_from_defaults_not_from_the_form(self):
        app = base_app()
        app.defaults.update({'units': 'IN', 'new_key': 7})
        app.options = AppOptions(version='test', baseline={}, defaults=app.defaults)
        app.options['units'] = 'MM'
        app.preferencesUiManager = SimpleNamespace(defaults_read_form=Mock(), defaults_write_form=Mock())
        target, _ = target_for(app, 'lifecycle')

        target.on_defaults2options()

        app.preferencesUiManager.defaults_read_form.assert_not_called()
        app.preferencesUiManager.defaults_write_form.assert_called_once_with()
        self.assertEqual(app.options['units'], 'IN')
        self.assertEqual(app.options['new_key'], 7)
```

   At the top of the same file, add `from defaults import AppOptions` after the other imports, if the file does not import `AppOptions` yet.

2. In `tests/test_app_handler_characterization.py`, line 533, change:

```python
        prefs = Recorder(("defaults_write_form_field", "defaults_read_form", "save_defaults"))
```

   to:

```python
        prefs = Recorder(("defaults_write_form_field", "defaults_read_form", "defaults_write_form", "save_defaults"))
```

3. In the same file, replace these lines (about line 553-555):

```python
        handler.defaults.update({"answer": 42})
        invoke("lifecycle", handler, "on_defaults2options")
        self.assertEqual(42, handler.options["answer"])
```

   with:

```python
        handler.options = AppOptions(version="test", baseline={}, defaults=handler.defaults)
        handler.defaults.update({"answer": 42, "units": "IN"})
        reads = [call for call in prefs.calls if call[0] == "defaults_read_form"]
        invoke("lifecycle", handler, "on_defaults2options")
        self.assertEqual(42, handler.options["answer"])
        self.assertEqual("IN", handler.options["units"])
        self.assertIn(("defaults_write_form", (), {}), prefs.calls)
        self.assertEqual(reads, [call for call in prefs.calls if call[0] == "defaults_read_form"])
```

   At the top of the same file, add `from defaults import AppOptions` after the other imports, if the file does not import `AppOptions` yet.

- [ ] **Step 2: Run the tests to see them fail**

Run:

```bash
rtk .venv/Scripts/python.exe -m pytest tests/test_app_refactor_characterization.py -q -k new_project_options
rtk .venv/Scripts/python.exe -m pytest tests/test_app_handler_characterization.py -q -k Lifecycle
```

Expected: FAIL. `defaults_read_form` is called and `defaults_write_form` is not called.

- [ ] **Step 3: Change `on_defaults2options`**

In `appHandlers/appLifecycle.py`, replace the method `on_defaults2options` with:

```python
    def on_defaults2options(self):
        """
        Set the project options of a new project from the application defaults
        and show them in the Preferences form.

        :return:    None
        """

        self.options.reset_from_defaults()
        self.app.preferencesUiManager.defaults_write_form()
```

- [ ] **Step 4: Run the tests to see them pass**

Run the 2 commands of Step 2 again.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
rtk git add appHandlers/appLifecycle.py tests/test_app_refactor_characterization.py tests/test_app_handler_characterization.py
rtk git commit -m "feat(options): a new project copies the project keys from the defaults, not from the Preferences form"
```

---

### Task 5: The Preferences window

**Files:**
- Modify: `appGUI/preferences/PreferencesUIManager.py`
- Create: `tests/test_preferences_project_keys.py`
- Modify: `tests/test_theme_color_scheme.py:189-225`

- [ ] **Step 1: Write the failing tests**

1. Create `tests/test_preferences_project_keys.py`:

```python
"""The Preferences form shows and saves the project keys of the active project."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6 import QtCore

from appGUI.preferences.PreferencesUIManager import PreferencesUIManager
from defaults import AppDefaults, AppOptions


class Field:
    def __init__(self, value=None):
        self.value = value

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value


def make_manager():
    defaults = AppDefaults(beta=False)
    options = AppOptions(version='test', baseline=defaults, defaults=defaults)
    manager = PreferencesUIManager.__new__(PreferencesUIManager)
    QtCore.QObject.__init__(manager)
    manager.defaults = defaults
    manager.ui = SimpleNamespace(app=SimpleNamespace(options=options, log=Mock()))
    manager.preferences_changed_flag = False
    manager.defaults_form_fields = {
        'gerber_bboxmargin': Field(), 'gerber_bboxrounded': Field(), 'global_gridx': Field()}
    return manager, defaults, options


class TestPreferencesProjectKeys(unittest.TestCase):
    def test_form_shows_project_value_for_project_key(self):
        manager, defaults, options = make_manager()
        defaults['gerber_bboxmargin'] = 0.1
        options['gerber_bboxmargin'] = 0.5
        defaults['global_gridx'] = 2.0
        manager.defaults_write_form()
        self.assertEqual(manager.defaults_form_fields['gerber_bboxmargin'].value, 0.5)
        self.assertEqual(manager.defaults_form_fields['global_gridx'].value, 2.0)

    def test_change_of_options_writes_the_project_value(self):
        manager, defaults, options = make_manager()
        defaults['gerber_bboxmargin'] = 0.1
        options['gerber_bboxmargin'] = 0.5
        manager.defaults_write_form_field('gerber_bboxmargin')
        self.assertEqual(manager.defaults_form_fields['gerber_bboxmargin'].value, 0.5)

    def test_read_form_writes_only_changed_project_keys(self):
        manager, defaults, options = make_manager()
        defaults['gerber_bboxmargin'] = 0.1
        defaults['gerber_bboxrounded'] = False
        options['gerber_bboxmargin'] = 0.5
        options['gerber_bboxrounded'] = True
        fields = manager.defaults_form_fields
        fields['gerber_bboxmargin'].value = 0.7
        fields['gerber_bboxrounded'].value = True
        fields['global_gridx'].value = 2.5
        manager.defaults_read_form()
        self.assertEqual(options['gerber_bboxmargin'], 0.7)
        self.assertEqual(defaults['gerber_bboxmargin'], 0.7)
        self.assertIs(options['gerber_bboxrounded'], True)
        self.assertIs(defaults['gerber_bboxrounded'], False)
        self.assertEqual(defaults['global_gridx'], 2.5)

    def test_show_writes_the_form_when_there_are_no_edits(self):
        manager, _defaults, options = make_manager()
        options['gerber_bboxmargin'] = 0.5
        with patch.object(PreferencesUIManager, 'init_preferences_gui'), \
                patch.object(PreferencesUIManager, 'pref_connect'), \
                patch.object(PreferencesUIManager, '_PreferencesUIManager__init_color_pickers'):
            manager.show_preferences_gui()
            self.assertEqual(manager.defaults_form_fields['gerber_bboxmargin'].value, 0.5)
            manager.defaults_form_fields['gerber_bboxmargin'].value = 0.9
            manager.preferences_changed_flag = True
            manager.show_preferences_gui()
        self.assertEqual(manager.defaults_form_fields['gerber_bboxmargin'].value, 0.9)


if __name__ == '__main__':
    unittest.main()
```

2. In `tests/test_theme_color_scheme.py`, in `test_theme_preferences_confirm_revert_and_save`:
   - Change the line `app.options = dict(defaults.items())` to:

```python
    app.options = AppOptions(version='test', baseline=defaults, defaults=defaults)
    app.options['gerber_bboxmargin'] = 0.123
```

   - After the last line of the function, `assert defaults[key] == app.options[key] == defaults.current_defaults[key] == expected`, add:

```python
    assert app.options['gerber_bboxmargin'] == 0.123
```

   - If the file does not import `AppOptions`, change its line `from defaults import AppDefaults` to `from defaults import AppDefaults, AppOptions`.

- [ ] **Step 2: Run the tests to see them fail**

Run:

```bash
rtk .venv/Scripts/python.exe tests/test_preferences_project_keys.py
rtk .venv/Scripts/python.exe -m pytest tests/test_theme_color_scheme.py -q -k confirm_revert_and_save
```

Expected: FAIL. The form shows 0.1 instead of 0.5. The theme test fails on `app.options['gerber_bboxmargin'] == 0.123`.

- [ ] **Step 3: Add `_source` and use it**

In `appGUI/preferences/PreferencesUIManager.py`:

1. Change the import line `from defaults import AppDefaults` to:

```python
from defaults import AppDefaults, is_project_key
```

2. After the method `_pref`, add:

```python
    def _source(self, key):
        """Return the storage that the Preferences form shows for this key."""
        if is_project_key(key):
            return self.ui.app.options
        return self.defaults
```

3. In `defaults_read_form`, replace:

```python
        for option in self.defaults_form_fields:
            try:
                self.defaults[option] = self.defaults_form_fields[option].get_value()
            except Exception as e:
                self.ui.app.log.error("App.defaults_read_form() --> %s" % str(e))
```

   with:

```python
        options = self.ui.app.options
        for option in self.defaults_form_fields:
            try:
                value = self.defaults_form_fields[option].get_value()
                if not is_project_key(option):
                    self.defaults[option] = value
                elif option not in options or options[option] != value:
                    # a changed project key goes to the project and becomes the default for new projects
                    options[option] = value
                    self.defaults[option] = value
            except Exception as e:
                self.ui.app.log.error("App.defaults_read_form() --> %s" % str(e))
```

   Also change the docstring line `Will read all the values in the Preferences GUI and update the defaults dictionary.` to:

```
        Will read all the values in the Preferences GUI. An application key is written to the defaults. A project key
        that is changed is written to the project options and to the defaults.
```

4. In `defaults_write_form_field`, replace:

```python
        def_dict = self.defaults if defaults_dict is None else defaults_dict
```

   with:

```python
        def_dict = self._source(field) if defaults_dict is None else defaults_dict
```

- [ ] **Step 4: Write the form when the Preferences tab opens**

In `show_preferences_gui`, before the line `self.init_preferences_gui()`, add:

```python
        # Show the current values: the active project for the project keys, the defaults for the other keys.
        if not self.preferences_changed_flag:
            self.defaults_write_form()

```

- [ ] **Step 5: A save does not copy the defaults into the project**

In `on_save_button`, replace:

```python
        self.defaults_read_form()
        self.defaults.current_defaults.update(self.defaults)
        # Apply the `defaults` dict to project options
        self.ui.app.options.update(self.defaults)
```

with:

```python
        self.defaults_read_form()
        self.defaults.current_defaults.update(self.defaults)
```

- [ ] **Step 6: Restore Defaults and Close without save**

1. In `on_restore_defaults_preferences`, replace:

```python
        self.defaults.reset_to_factory_defaults()
        self.defaults_write_form()
```

   with:

```python
        self.defaults.reset_to_factory_defaults()
        # show the factory values for all keys; a save writes the changed project keys to the project
        self.defaults_write_form(source_dict=self.defaults)
```

2. In `on_pref_close_button`, replace:

```python
        self.defaults_write_form(source_dict=self.defaults.current_defaults)

        self.defaults.update(self.defaults.current_defaults)
```

   with:

```python
        self.defaults.update(self.defaults.current_defaults)

        self.defaults_write_form()
```

- [ ] **Step 7: Run the tests to see them pass**

Run:

```bash
rtk .venv/Scripts/python.exe tests/test_preferences_project_keys.py
rtk .venv/Scripts/python.exe -m pytest tests/test_theme_color_scheme.py tests/test_vispy_only_settings.py -q
rtk .venv/Scripts/python.exe tests/test_icon_colors.py
rtk .venv/Scripts/python.exe tests/test_titlebar.py
rtk .venv/Scripts/python.exe tests/test_plugin_object_creation.py
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
rtk git add appGUI/preferences/PreferencesUIManager.py tests/test_preferences_project_keys.py tests/test_theme_color_scheme.py
rtk git commit -m "feat(preferences): show and save the project keys of the active project"
```

---

### Task 6: Changelog and full test run

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the changelog entries**

In `CHANGELOG.md`, under the date `18.10.2026`, add this section after the last section of that date (before the next date line). Use the same format as the other sections:

```
Preferences:

- the application settings are kept only in the application preferences; the project options are kept in the project
- a project file saves only the project options (Tools parameters, units and some Gerber, Excellon and Geometry parameters); an old project file still opens and its application settings are ignored
- removed the "Import Settings" question on project open; the project options of the file are always loaded
- a new project gets its options from the preferences and not from the Preferences form
- the Preferences window shows the project options of the active project; a save writes a changed project option to the project and to the preferences
- fixed: a save of the Preferences copied all the preferences into the project options
- Import Preferences writes the application settings of the file into the preferences
```

- [ ] **Step 2: Run the full test suite 1 time**

Run: `rtk .venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider`
Expected: no new failures. The run takes about 4 minutes. If a test fails, read the error text and find out if a change of this plan causes it. Report each failure with its error text and your finding. Do not change a test to hide a failure. Do not run `git stash`, `git checkout` or `git reset`.

- [ ] **Step 3: Commit**

```bash
rtk git add CHANGELOG.md
rtk git commit -m "docs(changelog): add the split of application settings and project options"
```

---

## Manual check list (for the user)

1. Start the app. Open Edit > Preferences. Change the Isolation tool diameter (a project key) and the grid X (an application key). Save. Close and start the app again. Both values stay.
2. Make a new project (File > New). The Isolation tool diameter is the saved value.
3. Change a project key in Preferences and save the project. Open the `.FlatPrj` file in a text editor (save without compression). The `options` part has no `global_` keys.
4. Change the theme. Open an old project that was saved with another theme. No "Import Settings" question shows. The theme does not change.
5. Open a project with other tool values. Open Preferences. The form shows the tool values of the project.
6. In Preferences, click Restore Defaults and then save. The tool values of the project change to the factory values.
7. In Preferences, change a value and close the tab without a save. The value goes back.
