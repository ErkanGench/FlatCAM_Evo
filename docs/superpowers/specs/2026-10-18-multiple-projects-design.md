# Multiple Projects in the Project Tab — Design

Date: 2026-10-18
Branch: 1.0

## Goal

The Project tab can hold more than one project. Only 1 project is active at a time.
A combobox above the object tree selects the active project. Inactive projects keep
their geometry and their Properties UI in RAM but release their plot data.

## Current state

- `App` holds the state of 1 project in separate attributes: `app.collection`,
  `app.options`, `app.project_filename`, `app.should_we_save`, `app.all_objects_list`.
- 817 call sites in 154 files use `app.collection`. All of them assume 1 collection.
- `ObjectCollection.__init__` creates its own tree view (`self.view`).
  `appMain.py:1130` adds that view to `ui.project_tab_layout`.
- `ObjectCollection.append` builds the Properties UI of each object at once
  (`ObjectCollection.py:650-651`).
- Each object has a VisPy shape group (`AppObjectTemplate.py:213`). Gerber objects also
  have `mark_shapes`. CNCJob objects also have `text_col` and `annotation`.
- A project load can overwrite `app.options` (`appIO.py:2995`).
- `on_file_save_project_as` suggests the file name `Project_<date>` (`appIO.py:1446`).

## 1. Architecture

### `ProjectContext` (new file `appObjects/ProjectContext.py`)

Holds the state of 1 project:

| Field | Content |
|---|---|
| `name` | The project name. It is unique among the open projects. |
| `filename` | The path of the `.FlatPrj` file, or `None`. |
| `collection` | The `ObjectCollection` of the project. |
| `options` | The project keys of the project (`defaults.project_options`). The application settings are in `app.defaults` and are the same for all projects. |
| `should_we_save` | The dirty flag. |
| `all_objects_list` | The project copy of `app.all_objects_list`. |
| `view_rect` | The canvas view rectangle when the project was last shown on the canvas. A switch with `visuals=False` (exit) does not change the canvas, so it does not change this value. `ProjectManager.displayed` is the project that the canvas shows. |

### `ProjectManager` (new file `appHandlers/appProjects.py`)

Holds the list of `ProjectContext` objects and the active one. All project operations go
through it. The GUI and the Tcl commands do not change the contexts directly.

| Method | Function |
|---|---|
| `new()` | Adds an empty project with a unique name and makes it active. |
| `open(filename)` | Adds a project from a file and makes it active. See section 4. |
| `switch(ctx)` | Makes `ctx` the active project. See below. |
| `rename(ctx, name)` | Changes the name. It refuses a name that another project uses. |
| `close(ctx, force=False)` | Closes and removes the project. See section 3. |
| `names()` | Returns the names in the order of the combobox. |
| `get_by_name(name)` | Returns the context or `None`. |
| `is_busy()` | Returns `True` if a background task runs. |

`switch` does these steps:

1. Write the live state of the active project back to its context: `app.options`,
   `app.project_filename`, `app.should_we_save`, `app.all_objects_list` and the canvas
   view rectangle.
2. Deactivate the old project (section 2).
3. Put the state of the new context into `app.collection`, `app.options`,
   `app.project_filename`, `app.should_we_save` and `app.all_objects_list`.
4. Show the tree view of the new collection.
5. Activate the new project (section 2).
6. Update the combobox and the title bar.

Because `switch` changes `app.collection`, the 817 existing call sites keep working.

### Project tab

- A row with the label `Project:` and a combobox goes above the object tree.
- Below the row, a `QStackedWidget` holds 1 tree view for each collection. A switch
  changes only the visible page.
- All the connections to `collection.view` (for example in `appSignalConnector` and
  `appExcEditor.py:4013`, `appExcEditor.py:4035`) move into 1 function. That function runs for
  each new collection.

## 2. Inactive projects

On deactivate, for each object in the collection:

- Clear and disable `shapes`.
- Clear and disable `mark_shapes` (Gerber) and `annotation` / `text_col` (CNCJob).

The geometry and the Properties UI of the objects stay in RAM. The Properties UI is not
deleted, because `set_ui()` is not safe to run 2 times: `CNCJobObject.set_ui()` generates
the G-code and `source_file` again and sets the units from `app.app_units`, and the
`set_ui()` of 4 object kinds connects object signals again.

On activate:

- Replot all objects.
- Restore the canvas view rectangle.

On a switch, the app resets the plugins, the same as `on_file_new_project` does now
(`appIO.py:1117-1172`). The tool shapes, the exclusion areas, the selection shape and the
hover shapes are cleared.

A switch is refused while:

- an editor is open (`app.call_source != 'app'`). A switch would lose the editor changes.
  The status bar shows "Close the editor first."
- a background task is queued or runs: a task in the worker stack (from the moment it is
  queued), a process in the process container, a save, a promise or an object load batch.

The status bar tells the user why.

A save that a close or an exit asks for must succeed before the project closes.
`appIO.save_project()` returns `True` after a written and verified file, else `False`.

## 3. Combobox and its right-click menu

The combobox list holds only project names. A right-click on the combobox opens this
menu:

| Item | Function |
|---|---|
| New Project | Adds `Project_1`, `Project_2`, ... and makes it active. |
| Open Project... | The same as File > Open Project. |
| Rename Project... | Opens an input dialog. A name that another project uses is refused with a message. After a rename, the title bar shows the new name. |
| Close Project | If the project has unsaved changes, it asks to save. If the user closes the last project, 1 empty new project replaces it. |

File > New Project and File > Open Project also add an entry. They do not replace the
active project.

The title bar shows the name of the active project.

## 4. Open and Save rules

### Open

- The project name is the basename of the file, without the extension. If another
  project already uses that name, the app adds a number, the same as
  `ObjectCollection.append` does for object names.
- If a project with the same file path is already open, a message box asks to overwrite
  it. The app compares normalized absolute paths.
  - **Yes** reloads that entry from the file and makes it active.
  - **No** makes the existing entry active.
- If the active project is empty, has no file and has no unsaved changes, it receives the
  opened file. No new entry is added. This stops an empty `Project_1` from staying in the
  list after the first open.
- The project keys of the file go into the new project. The application settings in the file are ignored
  (see `2026-10-18-options-defaults-split-design.md`).

### Save

- **A project with no file:** Save opens Save As. The suggested file is
  `<last save folder>/<name>.FlatPrj`. This replaces the `Project_<date>` default.
- **A project with a file, name equal to the file basename:** Save writes to that file.
- **A project with a file, name not equal to the file basename (after a rename):** Save
  writes `<same folder>/<name>.FlatPrj`. The old file stays on disk. `filename` changes
  to the new file. If the new file already exists, the app asks before it overwrites it.
- **Every save (Save, Save As, close, exit):** the file name, the project name, the dirty
  flag, the "file saved" notification and the title change only after `save_project()`
  returns `True`. A failed or cancelled save keeps the old state.
- **A change during a save:** the dirty flag is cleared when the save is queued, before
  the worker reads the objects. A change during the save sets it again, and a good save
  does not clear it. A failed save sets it back.
- **1 save at a time:** a File > Save or Save As is refused while another one is
  pending. `app.project_save_pending` is set when the save is queued and cleared only when
  the GUI has its result. While it is set, the exit, a project switch and a save from a
  close or an exit wait. The save of a close or an exit checks this also for the active project.
- **An error during a save:** `appIO.save_project_checked()` never raises. An error is a
  failed save: `save_in_progress` is reset and the completion of the save always comes.

A project is dirty if its flag is set and it has objects or a file. So a saved project
whose objects are all deleted is dirty. An empty project without a file is not dirty.

### Settings

Each project keeps its own project keys. A change of a project key in Preferences applies to
the active project and becomes the default for new projects. A change of an application setting
applies to all projects.

### Exit

The app asks about each project that has unsaved changes. To save a project that is not
active, the exit makes it active without a change of the canvas. If the exit stops for any
reason (a cancel, a failed save, a pending save, a cancel of the Tools Database question or
an error), the project that was active before becomes active again.

## 5. Tcl commands

The Tcl commands act on the active project. The commands `new` and `open_project` keep
their current behavior, which replaces the active project. This keeps the current
scripts working.

New commands:

| Command | Arguments | Result |
|---|---|---|
| `list_projects` | none | The project names, 1 name on each line, in the order of the combobox. |
| `select_project` | `name` (required) | Makes that project active. The combobox changes to it. If no project has that name, the command returns an error. If a background task runs, the command returns an error and does not switch. |
| `close_project` | `name` (optional; the default is the active project), `-force` (default `False`) | Closes and removes the project. There is no dialog. If the project has unsaved changes and `-force` is not `True`, the command returns an error. If the command closes the last project, 1 empty new project replaces it. |

- Files: `tclCommands/TclCommandListProjects.py`, `tclCommands/TclCommandSelectProject.py`,
  `tclCommands/TclCommandCloseProject.py`.
- Each command follows the pattern of `TclCommandGetNames` and calls `ProjectManager`.
  None of them has its own logic.
- Each command is registered in `tclCommands/__init__.py`.

## 6. Out of scope

- Unloading a project to disk.
- Moving or copying an object from one project to another.
- Running a background task on an inactive project.

## 7. Tests

`ProjectManager` unit tests:

- A switch swaps the collection, the options, the filename, the dirty flag and
  `all_objects_list`.
- New names are unique. A duplicate name is refused on rename.
- The save path is correct for each of the 3 cases in section 4.
- The "already open" check uses normalized paths.
- `close` of the last project leaves 1 empty project.
- A switch is refused while `is_busy()` returns `True`, while a task is queued in the
  worker stack and while an editor is open.
- A failed save stops a close: the project stays and keeps its unsaved changes.
- A failed File > Save or Save As keeps the file name, the name and the dirty flag.
- A saved project with all objects deleted is dirty.
- A switch with `visuals=False` (exit) does not change the saved view of any project.
- The exit does not quit while a save is pending.
- An exit that saves a project that is not active and then stops makes the first project
  active again: the active project, the live collection, the tree and the canvas match.
- `appIO.save_project()` returns `False` for a real write failure and `True` for a good save.

Option B test:

- A switch clears the shapes of the inactive objects. The geometry and the Properties UI
  stay.
- A switch back plots the objects and does not call `set_ui()`.

Qt test:

- The combobox menu shows the 4 commands.
- A rename changes the title bar.

Tcl tests:

- `list_projects` returns the names in order.
- `select_project` switches by name and returns an error for an unknown name.
- `close_project` refuses a dirty project without `-force` and closes it with `-force 1`.
