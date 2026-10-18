# Remove the Project Autosave — Plan

**Goal:** Remove the timer that saves the project (Preferences > General > "Enable Auto Save" and "Interval") and all the code that exists only for it.

**Why:** The autosave is off by default. With more than 1 project it does harm: for a project without a file it opens Save As from the timer; after a rename it writes a new file or asks to overwrite from the timer; it saves only the active project; it needs `block_autosave`, `hold_autosave` and `release_autosave` around every dialog of the close and the exit.

**Branch:** local `1.0`. Do not push. No `Co-Authored-By` line or Claude attribution in the commit.

## Rules for the agent

1. Run Python with `.venv/Scripts/python.exe`. Run a unittest file with `-m unittest discover -s tests -p "<file>"`; a pytest file with `-m pytest <file> -q -p no:cacheprovider`.
2. Never run `python -` or a heredoc with Python. Never run `taskkill /IM python.exe`. Do not start the GUI app.
3. Prefix git with `rtk`.
4. Do not touch or stage the user files: `CHANGELOG.md`, `appEditors/appGerberEditor.py`, `appEditors/grb_plugins/GrbBufferPlugin.py`, `appParsers/ParseExcellon.py`, `appParsers/ParseGerber.py`, `appPlugins/ToolMove.py`, `tests/test_gerber_editor_pick.py`, `tests/test_move_tool.py`, `docs/mach3/`.
5. Find each place by its text. The line numbers are approximate.

## Step 1: Remove the code

| File | Change |
|---|---|
| `defaults.py` (about line 132) | Remove the keys `global_autosave` and `global_autosave_timeout` from `factory_defaults`. In `AppDefaults.load()`, next to `defaults.pop('global_graphic_engine', None)`, add `defaults.pop('global_autosave', None)` and `defaults.pop('global_autosave_timeout', None)`, so an old preferences file does not bring them back. |
| `appGUI/preferences/general/GeneralAppPrefGroupUI.py` (about lines 312-335) | Remove `autosave_cb`, `autosave_label`, `autosave_entry`, their tooltips, their `addWidget` calls and the commented `as_ois` line. If this leaves an empty grid, a header or a separator that belongs only to the autosave, remove it too. Keep the row numbers of the other widgets valid. |
| `appGUI/preferences/PreferencesUIManager.py` | Remove the 2 entries `"global_autosave"` and `"global_autosave_timeout"` of the form map (about line 78). Remove the comment `# update the autosave timer` and the call `self.ui.app.save_project_auto_update()` (about line 1347). |
| `appMain.py` | Remove `self.block_autosave = False` (2 places, about lines 422 and 1096), `self.autosave_timer = None` (about line 462), the timer creation, `self.save_project_auto_update()` and the `timeout.connect` (about lines 1097-1099), and the 2 methods `save_project_auto` and `save_project_auto_update` (about line 4035). |
| `appHandlers/appLifecycle.py` | Remove the methods `save_project_auto` and `save_project_auto_update` and their "Method 14/15" comment headers. In `quit_application`, remove the comment and `self.app.autosave_timer.stop()`. In the class docstring, remove "autosave". In `final_save`, remove `hold_autosave` / `release_autosave` and the variable `autosave_state`; keep the `quitting` logic and keep `projects.return_to(start)` in the `finally` for every exit that stops. Update the comments: no comment may mention the autosave. |
| `appHandlers/appProjects.py` | Remove `hold_autosave` and `release_autosave`. In `request_close` (about line 554), remove the hold and the release around the dialogs; keep the rest of the logic as it is. Update the comment about line 573 so it does not mention the autosave. |
| `appHandlers/appIO.py` | Remove `self._project_autosave_state = None` from `__init__`, the method `_restore_project_autosave`, its 2 calls, and the 2 lines in `_open_project` that save and set `block_autosave` (with their comment `# block auto-saving while a project is loaded`). Read the code around each call before you remove it: if `_restore_project_autosave` is the only line of a branch or a method, keep the branch or the method correct (for example, keep the method that calls it if it does other work). |

After the edits, this search must find nothing in the `.py` files outside `tests/`: `autosave`, `block_autosave`, `save_project_auto`.

## Step 2: Update the tests

Search `tests/` for `autosave`, `block_autosave`, `save_project_auto`, `hold_autosave`, `release_autosave`, `_project_autosave_state`, `_restore_project_autosave`.

- A test whose only purpose is the autosave: remove it. Examples: a test that a timer saves, a test that the autosave is blocked in a dialog, a test that a cancel restores the autosave.
- A test that checks other behavior and also the autosave: remove only the autosave setup and the autosave asserts. Keep the other asserts. Example: `test_refused_quit_after_the_save_of_an_inactive_project_returns_to_the_start_project` in `tests/test_projects_manager.py` must still check the active project, `app.collection`, the tree page, `displayed` and the tray icon. `test_cancel_of_the_tools_database_question_restores_the_autosave` must become a test that a cancel of the Tools Database question does not quit and does not hide the tray icon (rename it to `test_cancel_of_the_tools_database_question_does_not_quit`).
- A mock or a stub that only sets `block_autosave` or `hold_autosave`: remove that part.
- Add 1 test in `tests/test_lifecycle_initialization.py` or a fitting existing file: `AppDefaults.load()` of a file that has `global_autosave: true` and `global_autosave_timeout: 1000` does not keep these keys.

Do not change a test for any other reason.

## Step 3: Update the spec of the multiple projects

In `docs/superpowers/specs/2026-10-18-multiple-projects-design.md`:
- Remove the bullet "**No autosave in the dialogs:** ..." from section 4 "Save". Keep its last sentence as its own bullet: "**No quit during a save:** before the app quits, it checks again that no save is pending."
- In section 4 "Save", bullet "1 save at a time", remove "or autosave".
- In section 7 "Tests", remove "An autosave that fires while the exit or close question is open does not start a save." and "A cancel of the Tools Database question restores the autosave." Keep "The exit does not quit while a save is pending."

## Step 4: Run the tests

Run every test file that you changed, and these files:

```
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_manager.py"
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_projects_appio.py"
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_project_load_cleanup.py"
.venv/Scripts/python.exe -m pytest tests/test_shutdown_routing.py tests/test_lifecycle_initialization.py tests/test_app_refactor_characterization.py tests/test_app_handler_characterization.py tests/test_app_refactor_integration.py tests/test_appmain.py tests/test_batch_properties_qt.py tests/test_responsive_batch_executor.py tests/test_tools_database.py tests/test_unify_characterization.py tests/test_vispy_only_backend.py -q -p no:cacheprovider
.venv/Scripts/python.exe -c "import appMain"
```

All must pass. Do not run the full suite.

## Step 5: Commit

Stage only the files of Steps 1-3 and this plan file. Message:

```
refactor: remove the project autosave

The timer saved only the active project, opened Save As for a project
without a file and needed a block around every close and exit dialog.
An old preferences file with the autosave keys still loads.
```

## Manual check

1. Start the app with an old preferences file that has `"global_autosave": true`. The app starts, and Preferences > General has no Auto Save options.
2. Change a project and wait 5 minutes. No save and no dialog happens.
3. Close the app with 2 changed projects. The app asks about each project. Cancel the Tools Database question: the app stays open and shows the project that was active before.
