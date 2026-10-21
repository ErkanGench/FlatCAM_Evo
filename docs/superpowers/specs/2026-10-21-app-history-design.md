# App Undo / Redo history — design

Date: 2026-10-21. Branch: 1.0.

## Goal

One Undo / Redo history for each project. It covers the operations of the app outside the editors. Tools record their operations with a small number of lines, so more tools can use it later. The editors keep their own history.

## Scope of version 1

- The history module, the Edit menu items, the toolbar buttons and the keys.
- These operations record steps:
  - Align Objects (all modes)
  - the Transform plugin (rotate, skew, scale, flip, offset, buffer)
  - the Edit menu transforms: Flip X / Flip Y, Rotate, Skew X / Skew Y, Set Origin, Move to Origin, Custom Origin
  - the Offset / Scale / Skew buttons of the object Properties
  - object delete
  - object create (an object that a tool or a file import makes)
  - object rename
- Out of scope: Tcl commands, headless mode, the editors, save of the history in the project file.

## Keys and UI

- Ctrl+Z: Undo. Ctrl+Shift+Z and Ctrl+Y: Redo. The keys are free in the app context now (Alt+Z is Panelize, Shift+Y is Skew Y).
- The keys do nothing if the focus is in a text field (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox), as the Geometry Editor does (`appGUI/MainGUI.py:3538`).
- In an editor (`app.call_source != 'app'`) the keys stay with the editor.
- Edit menu: "Undo <label>" and "Redo <label>" at the top. The items are disabled when nothing can be undone or redone.
- 2 toolbar buttons (Undo, Redo) in the Edit toolbar. The tooltip shows the label of the next step.
- The Undo / Redo buttons and the 2 stacks of the Align plugin are removed. The Align plugin records into the app history.

## Module — `appHandlers/appHistory.py`

### Object identity

Undo of a delete makes a new Python object. So a step does not keep object references. It keeps `history_uid` values.

- `FlatCAMObj.__init__` sets `self.history_uid = uuid4().hex`.
- `to_dict()` / `from_dict()` keep `history_uid`, so a rebuilt object gets the same value. An old project without the key gets a new value.
- `HistoryManager.find(uid)` returns the object with this uid in the collection of the project, or None.

### Steps

```python
class HistoryStep:
    label: str          # shown in the menu, already translated
    uids: set           # the objects that the step touches
    size: int           # estimated bytes that the step keeps alive
    def undo(self, history) -> None    # raises HistoryError if it cannot run
    def redo(self, history) -> None
```

| Step | Content | Undo | Redo | size |
|---|---|---|---|---|
| `MatrixStep` | `[(uid, matrix)]` | applies `invert(matrix)` to each object | applies `matrix` | 0 |
| `SnapshotStep` | `[(uid, before, after)]`, each a state dict | puts back `before` | puts back `after` | coordinates of `before` and `after` × 16 |
| `CreateStep` | `[uid]`; the state is taken at undo | deletes the objects and keeps their state | rebuilds the objects with the same uid | coordinates of the kept state × 16 |
| `DeleteStep` | `[(uid, state)]` | rebuilds the objects | deletes them again | coordinates × 16 |
| `RenameStep` | `[(uid, old, new)]` | sets `old` | sets `new` | 0 |
| `GroupStep` | a list of steps | undo of each, in reverse order | redo of each, in order | sum |

- Object state: `obj.to_dict()` as project save uses it, plus `kind`. Shapely geometries are immutable, so the state keeps references and does not copy them. The implementation checks that `to_dict()` does not convert the geometry to text. If it does, the step keeps a shallow copy of the attributes that `from_dict()` reads.
- Rebuild: the same `obj_init` path that `appIO.open_project()` uses (`new_obj.from_dict(state)`, then the `LoudDict` options), through `app.app_obj.new_object(kind, name, obj_init)`. The rebuild records no `CreateStep`.
- Apply of a matrix: the function `apply_matrix_to_object` moves from `appPlugins/ToolAlignObjects/Align.py` to `appHandlers/appHistory.py` (Align imports it from there). It supports Gerber, Excellon and Geometry. For a CNCJob object, the tool records a `SnapshotStep`, not a `MatrixStep`.
- After each undo or redo of a geometry change, the step updates the bounds options, emits `object_changed` and plots the object (`plot_transformed(matrix)` for a matrix, else `plot()`).

### HistoryManager

```python
class HistoryManager(QtCore.QObject):
    changed = QtCore.pyqtSignal(str, str)          # undo label, redo label ('' = nothing)

    def push(self, step)                           # thread safe; clears Redo; applies the limits
    def undo(self) -> bool
    def redo(self) -> bool
    def can_undo(self) / can_redo(self)
    def clear(self)
    def forget(self, uid)                          # drops every step that touches uid (Undo and Redo)
    def group(self, label)                         # context manager: the steps pushed inside become 1 GroupStep
    def suspended(self)                            # context manager: push() does nothing inside (project load, rebuild)

    # 1-line helpers for the tools
    def record_matrix(self, label, pairs)          # pairs: [(obj, matrix)]
    def snapshot(self, label, objects)             # context manager: state before, the body runs, state after
    def record_create(self, label, objects)
    def record_delete(self, label, objects)        # called BEFORE the objects are deleted
    def record_rename(self, obj, old, new)
```

- `push` from a worker thread: it takes a lock and emits `changed` (queued to the GUI thread).
- `push` does nothing if the app is headless, if a Tcl command runs, or inside `suspended()`.
- Undo / redo run only on the GUI thread. They do nothing if `ProjectManager.is_busy()` is true or an editor is open, and they show a message.
- If a step raises `HistoryError` (for example, its object is gone), the manager drops the step, shows the message and does not move other steps.
- An undo step that fails halfway leaves the objects as they are and drops the step. A step never half-undoes silently.

### Limits

- 2 preferences in `defaults.py`:
  - `global_history_steps`: default 100, range 1 to 1000.
  - `global_history_memory_mb`: default 256, range 16 to 4096.
- After each push, the manager drops the oldest Undo steps while there are too many steps or the sum of `size` is too big. Redo steps count toward the memory limit too.
- The preferences UI gets 2 fields in General > App Settings (or the nearest existing group).

## Projects

- `ProjectContext` gets `history: HistoryManager`.
- `app.history` is the history of the active project. `ProjectManager.capture()` / `_load()` exchange it as they do for `app.collection`.
- `app.history.changed` drives the menu and the toolbar. A project switch reconnects the signal and emits it once.
- New project, open project and close project: the new context has an empty history. Project open runs inside `suspended()`, so the load records nothing.

## Editors

- While an editor is open, Undo / Redo of the app are disabled.
- When an editor saves an object back, the app calls `history.forget(uid)` for that object. The old steps could give a wrong result after the edit.

## Recording rules for the tools

- A tool that applies 1 affine matrix: `app.history.record_matrix(label, [(obj, matrix)])` after the apply.
- A tool that changes geometry in a way that is not affine: `with app.history.snapshot(label, objects): ...`.
- A tool that works on many objects in 1 action: `with app.history.group(label): ...`.
- A tool that makes objects: `AppObject.new_object` records a `CreateStep` by default. A new parameter `record_history=True` lets a caller switch it off. Tcl commands, project open and the rebuild of a step switch it off.

## Tests — `tests/test_app_history.py`

1. `HistoryManager` with fake steps: push, undo, redo, the clear of Redo after a push, the count limit, the memory limit, `group`, `suspended`, `forget`, a step that raises `HistoryError`.
2. Each step type on real Gerber, Excellon and Geometry objects (the fixtures of `tests/test_unify_characterization.py`): undo and redo give the same bounds, the same feature count and the same name.
3. Delete + undo rebuilds an object with the same `history_uid`; a later `MatrixStep` on that uid still works.
4. 2 projects: each has its own history; a switch shows the right labels.
5. `forget` after an editor save.
6. The keys: Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y call undo / redo in the app context, and do nothing with the focus in a QLineEdit.

## Later (not version 1)

- The other tools (Isolation, NCC, Paint, Cutout, Drilling, Milling, Panelize, ...): most of them make new objects, so `CreateStep` already covers them through `new_object`.
- The editor save as 1 `SnapshotStep` (Undo of a whole edit session).
- A History panel with the list of steps.
