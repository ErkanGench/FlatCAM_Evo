# Split of Application Settings and Project Options — Design

Date: 2026-10-18
Branch: 1.0

## Goal

`app.defaults` holds the application settings and the starting values for new projects.
`app.options` holds only the options of the project. A project file saves and loads only
project options. An old project file can not change the application settings any more.

## Problem

The 2 dictionaries are mixed now:

1. A Preferences save copies all defaults into the project options
   (`PreferencesUIManager.py:1241`, `options.update(self.defaults)`). Every value that is
   special to the project is lost.
2. `save_project` writes all 612 keys of `app.options` into the `.FlatPrj` file, including
   the 95 `global_*` keys. "Import Settings?" on open puts all of them back. An old project
   can change the theme, the layout or the autosave. The code removes 1 key by hand
   (`global_graphic_engine`, `appIO.py:2995`).
3. The application code reads its own settings from the project: about 200 reads of the
   form `options.get("global_x", defaults.get("global_x"))`.
4. `on_defaults2options` (`appLifecycle.py:582`) reads the Preferences form into `defaults`
   and copies all of `defaults` into `options`.
5. The change callback on `options` writes the Preferences form from `defaults`, not from
   the value that changed.

## Decisions

| Decision | Choice |
|---|---|
| Where application settings live | Only in `app.defaults`. |
| Where project options live | In `app.options`. A new project copies them from `app.defaults`. |
| What the Preferences window shows | A project key: the value of the project. An application key: the value of `app.defaults`. |
| What a Preferences save writes | An application key: `app.defaults`. A project key that the user changed: the project and `app.defaults`. A project key that the user did not change: nothing. |
| "Import Settings?" on project open | Removed. The project options in the file are always loaded. |
| How the existing code keeps working | `AppOptions` becomes a merged view (section 2). The about 230 read and loop sites do not change. |

## 1. The key list

A new function `is_project_key(key)` in `defaults.py` decides the kind of each key.

**Rule:** a key is a project key if it gives a starting value for a manufacturing parameter
or holds a value that a plugin remembers for the job. A key that controls the GUI, the
display, the plots, import or export formats, the editors, the keyboard, paths, the machine
or speed is an application key.

**Project keys:**

- `units`
- `gerber_noncoppermargin`, `gerber_noncopperrounded`, `gerber_bboxmargin`,
  `gerber_bboxrounded`, `gerber_follow`
- `excellon_drill_tooldia`, `excellon_slot_tooldia`
- `geometry_seg_x`, `geometry_seg_y`
- Every key that starts with `tools_`, except the application keys below.

**Application keys among the `tools_` keys:**

- Every key that starts with `tools_grbl_` or `tools_calc_`.
- Every key that ends with `_plotting`, `_big_cursor` or `_preprocessor_list`.
- `tools_al_controller`, `tools_gcode_fit_view`, `tools_dist_snap_center`,
  `tools_opt_precision`, `tools_qrcode_sel_limit`.

**Every other key is an application key.** This includes all `global_*` keys, the plot,
editor, export and parser keys of Gerber, Excellon, Geometry and CNCJob, all `cncjob_*`
keys (G-code output format and machine bed), `fa_*`, the keyboard keys, `script_*`,
`document_*`, `units_precision`, `first_run` and `root_folder_path`.

The rule is a function, not a fixed set, so a key that a later version adds follows the
rule without an edit to the list.

## 2. `AppOptions` as a merged view

`AppOptions` gets a link to the live `AppDefaults` object:
`AppOptions(version, baseline=..., defaults=None)`.

- If `defaults` is `None`, `AppOptions` works as it does now. This keeps the existing
  tests and any code that makes an `AppOptions` without defaults working.
- If `defaults` is set, `AppOptions` stores only the project keys in its own `LoudDict`.
  Application keys go to `defaults`.

| Operation | Project key | Application key |
|---|---|---|
| `options[key]`, `options.get(key, ...)` | Own storage | `defaults` |
| `options[key] = value` | Own storage (the change callback runs) | `defaults[key] = value`, then the change callback runs |
| `del options[key]` | Own storage | `defaults` |
| `key in options` | Own storage | `key in defaults` |
| `for key in options`, `keys()`, `items()`, `values()`, `len()`, `copy()` | All project keys plus all application keys, as 1 merged dictionary | |
| `update(other)` | Each key goes to its place by the rows above | |

New methods:

- `project_items()`: only the project keys and values, for the project file.
- `reset_from_defaults()`: copy each project key from `defaults` (deep copy). Used for a new
  project.
- `load_project(project_options)`: run `reset_from_defaults()`, then put each project key of
  `project_options` into the own storage. Application keys in `project_options` are
  ignored.

`AppOptions.load(filename, ...)` (used on File > New and on Import Preferences) keeps its
current function, but with a `defaults` link it puts only the project keys into its own
storage.

`appMain.py:860` changes to `AppOptions(version=self.version, baseline=self.defaults,
defaults=self.defaults)`.

## 3. Project file

- `save_project` writes `"options": dict(self.app.options.project_items())`.
- `_restore_project_handler` removes the "Import Settings?" message box. In all cases it
  calls `self.app.options.load_project(proj_dict['options'])`. Then it refreshes the
  Preferences form (`preferencesUiManager.defaults_write_form()`).
- The special case for `global_graphic_engine` is removed, because application keys are
  never loaded from a project.
- An old project file still loads. Its application keys are ignored. A project key that
  the file does not have gets its value from `defaults`.

## 4. New project

`on_defaults2options` (`appLifecycle.py:582`) changes to:

1. `self.options.reset_from_defaults()`
2. `self.app.preferencesUiManager.defaults_write_form()`

It does not read the Preferences form any more. Before, a new project copied the form,
which can hold the values of the old project.

## 5. Preferences window

In `PreferencesUIManager`:

- A new method `_source(key)` returns `self.ui.app.options` for a project key and
  `self.defaults` for an application key.
- `defaults_write_form` and `defaults_write_form_field` read each field from `_source(key)`
  when no `source_dict` is given.
- `defaults_read_form` writes each field:
  - Application key: `self.defaults[key] = value`.
  - Project key: if `value` is not equal to `options[key]`, then `options[key] = value` and
    `self.defaults[key] = value`. Else nothing.
- In `on_save_button`, the line `self.ui.app.options.update(self.defaults)` is removed.
- The change callback on `options` (`on_defaults_dict_change`) writes the form field from
  `_source(key)`, so it shows the value that changed.

The Preferences pages that write `app.options[...]` directly (for example
`GeneralGUIPrefGroupUI.py`) need no change. The merged view sends their application keys to
`defaults`.

## 6. What does not change

- The about 200 reads of `global_*` keys from `options` keep working through the merged
  view. They can move to `defaults` later, 1 at a time. That work is not in this design.
- `current_defaults.FlatConfig` keeps all keys: the application settings and the starting
  values of the project keys.
- The Tcl commands `get_sys` and `set_sys` keep working. `set_sys` on an application key
  changes `defaults`.
- The handling of `units` when a project with other units is opened stays as it is now.

## 7. Tests

`AppOptions`:

- `is_project_key` returns the expected kind for each group of section 1, including each
  exception.
- A read and a write of an application key go to `defaults`. A read and a write of a
  project key stay in own storage.
- A loop and `items()` see all keys. `project_items()` sees only project keys.
- `load_project` ignores application keys and fills missing project keys from `defaults`.
- Without a `defaults` link, `AppOptions` works as before.

Project file:

- A saved project has no application keys in `options`.
- An opened project with a `global_theme` value does not change `defaults['global_theme']`.
- No "Import Settings?" message box shows on open.

Preferences:

- The form shows the value of the project for a project key.
- A save with 1 changed project key writes it to the project and to `defaults`. The other
  project keys in `defaults` do not change.
- A save does not copy `defaults` into the project.

New project:

- A new project gets the project keys from `defaults`, not from the Preferences form.
