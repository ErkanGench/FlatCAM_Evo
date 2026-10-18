# Multiple Projects in the Project Tab — Design

Date: 2026-10-18
Branch: 1.0

## Goal

The Project tab can hold more than one project. Only 1 project is active at a time.
A combobox above the object tree selects the active project. Inactive projects keep
their geometry in RAM but release their plot data and their Properties UI.

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
| `options` | The project copy of the options. |
| `should_we_save` | The dirty flag. |
| `all_objects_list` | The project copy of `app.all_objects_list`. |
| `view_rect` | The canvas view rectangle when the project was last active. |

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
- Delete the Properties UI of the object.

The geometry of the objects stays in RAM.

On activate:

- Rebuild the Properties UI of each object (`set_ui` + `build_ui`).
- Replot all objects.
- Restore the canvas view rectangle.

On a switch, the app also closes any open editor and resets the plugins, the same as
`on_file_new_project` does now (`appIO.py:1117-1172`). The tool shapes, the exclusion
areas, the selection shape and the hover shapes are cleared.

While a background task runs, the combobox and its menu are disabled. The status bar
tells the user why.

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
- The "Import Settings?" answer applies only to the options of the new project.

### Save

- **A project with no file:** Save opens Save As. The suggested file is
  `<last save folder>/<name>.FlatPrj`. This replaces the `Project_<date>` default.
- **A project with a file, name equal to the file basename:** Save writes to that file.
- **A project with a file, name not equal to the file basename (after a rename):** Save
  writes `<same folder>/<name>.FlatPrj`. The old file stays on disk. `filename` changes
  to the new file. If the new file already exists, the app asks before it overwrites it.

### Settings

Each project keeps its own options. A change in Preferences applies to the active
project only.

### Exit

The app asks about each project that has unsaved changes.

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
- A switch is refused while `is_busy()` returns `True`.

Option B test:

- A switch clears the shapes and deletes the Properties UI of the inactive objects. The
  geometry stays.
- A switch back rebuilds the Properties UI and plots the objects.

Qt test:

- The combobox menu shows the 4 commands.
- A rename changes the title bar.

Tcl tests:

- `list_projects` returns the names in order.
- `select_project` switches by name and returns an error for an unknown name.
- `close_project` refuses a dirty project without `-force` and closes it with `-force 1`.
