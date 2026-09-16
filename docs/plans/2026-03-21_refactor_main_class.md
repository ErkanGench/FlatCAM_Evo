# Refactoring Plan: appMain.py → Modular Handler Architecture

## Context

`appMain.py` contains the `App` class with **154 methods** spanning **~8200 lines** and an `__init__` of **1,136 lines**. It is the central hub of FlatCAM EVO — every component accesses it via `self.app`. The class has grown into a "god object" mixing unrelated concerns: mouse events, object transforms, plot management, signal wiring, editor lifecycle, preferences, dialogs, and more.

Two handlers already exist in `appHandlers/` (`appIO` with 68 methods, `appEditor` with 10 methods) and follow a proven, consistent pattern. This plan extends that pattern to decompose `App` into focused handler modules while **preserving all method interfaces** — external code continues to call `self.app.method_name()` unchanged.

---

## Strategy: Delegation with Thin Facades

1. **Extract** groups of related methods into new handler classes in `appHandlers/`.
2. **Keep facade methods** on `App` that delegate to the handler (one-liner wrappers). This preserves the `self.app.method_name()` API that 150+ files depend on.
3. **Break up `__init__`** into logical private setup methods.
4. Follow the **exact same pattern** as `appIO`/`appEditor`: `QtCore.QObject` subclass, receives `app` in `__init__`, caches common attributes (`self.log`, `self.inform`, `self.options`, etc.).

**No mixins. No interface changes. No magic.**

---

## Phase 1: Break Up `__init__` (Low Risk, High Readability)

Extract the 1,136-line `__init__` into private setup methods called in sequence. All remain on the `App` class — no new files needed.

### New private methods:

| Method | Lines | What it does |
|--------|-------|-------------|
| `_setup_logging()` | 306–329 | Logger initialization |
| `_setup_state_variables()` | 331–475 | Mouse state, selection lists, UI flags, coordinates |
| `_setup_paths_and_config()` | 476–607 | OS detection, data_path, portable mode, folder/file creation |
| `_setup_defaults_and_preferences()` | 609–695 | Load AppDefaults, AppOptions, theme, units |
| `_setup_gui()` | 697–945 | Object classes, splash, language, preprocessors, MainGUI, shell, PreferencesUIManager |
| `_setup_canvas_and_plotting()` | 947–1076 | ObjectCollection, PlotCanvas, shape collections, workers, activity monitor |
| `_setup_tools_and_editors()` | 1078–1192 | Tool references (None), install_tools, editors, ExclusionAreas, handlers |
| `_setup_system_integration()` | 1194–1227 | First-run, system tray, recent items |
| `_setup_signal_connections()` | 1229–1345 | All signal/slot wiring (menus, canvas, preferences, status) |
| `_setup_startup()` | 1347–1441 | Show window, process CLI args, old defaults warning |

### Resulting `__init__`:
```python
def __init__(self, qapp, user_defaults=True):
    super().__init__()
    self.qapp = qapp

    self._setup_logging()
    self._setup_state_variables()
    self._setup_paths_and_config()
    self._setup_defaults_and_preferences()
    self._setup_gui()
    self._setup_canvas_and_plotting()
    self._setup_tools_and_editors()
    self._setup_system_integration()
    self._setup_signal_connections()
    self._setup_startup()
```

**Files modified:** `appMain.py` only.

---

## Phase 2: Extract Canvas Event Handler (`appHandlers/appCanvasEvents.py`)

**~15 methods, ~700 lines** — the largest cohesive group.

### Methods to extract:

| Method | Line | Purpose |
|--------|------|---------|
| `on_mouse_click_over_plot` | 5919 | Left/right click dispatch |
| `on_mouse_double_click_over_plot` | 5953 | Double-click handler |
| `on_mouse_move_over_plot` | 5957 | Mouse move + coordinate display |
| `on_mouse_click_release_over_plot` | 6115 | Click release + selection |
| `on_mouse_and_key_modifiers` | 6235 | Ctrl/Shift+click logic |
| `on_mouse_context_menu` | 6278 | Right-click context menu |
| `selection_area_handler` | 6329 | Drag-selection rectangle |
| `select_objects` | 6437 | Object selection by click |
| `selected_message` | 6571 | Status bar selection message |
| `on_plugin_mouse_click_release` | 6606 | Plugin-specific mouse release |
| `on_plugin_mouse_move` | 6633 | Plugin-specific mouse move |
| `delete_hover_shape` | 6660 | Remove hover highlight |
| `draw_hover_shape` | 6664 | Draw hover highlight |
| `delete_selection_shape` | 6710 | Remove selection box |
| `draw_selection_shape` | 6714 | Draw selection box |
| `draw_moving_selection_shape` | 6777 | Animated drag-selection |

### Handler class:
```python
# appHandlers/appCanvasEvents.py
class AppCanvasEvents(QtCore.QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.log = app.log
        self.inform = app.inform
        self.options = app.options

    def on_mouse_click_over_plot(self, event): ...
    def on_mouse_move_over_plot(self, event, origin_click=None): ...
    # ... all methods moved here
```

### Facade on App:
```python
# In App class — one-liner delegates
def on_mouse_click_over_plot(self, event):
    self.canvas_events.on_mouse_click_over_plot(event)
```

**Files modified:** `appMain.py`, new `appHandlers/appCanvasEvents.py`.

---

## Phase 3: Extract Object Operations Handler (`appHandlers/appObjectOps.py`)

**~20 methods, ~800 lines** — object transforms, copy, delete, move.

### Methods to extract:

| Method | Line | Purpose |
|--------|------|---------|
| `on_flipy` | 5544 | Flip on Y axis |
| `on_flipx` | 5589 | Flip on X axis |
| `on_rotate` | 5635 | Rotate selection |
| `on_skewx` | 5693 | Skew on X axis |
| `on_skewy` | 5741 | Skew on Y axis |
| `on_set_origin` | 4410 | Set origin to click |
| `on_set_zero_click` | 4454 | Set zero at click position |
| `on_move2origin` | 4547 | Move objects to origin |
| `on_jump_to` | 4617 | Jump cursor to location |
| `on_locate` | 4737 | Locate object corner/center |
| `on_numeric_move` | 4862 | Move by numeric offset |
| `on_copy_command` | 4935 | Copy selected objects |
| `on_copy_object2` | 5010 | Copy with custom name |
| `on_rename_object` | 5061 | Rename object |
| `on_delete_keypress` | 4261 | Delete key handler |
| `on_delete` | 4300 | Delete selected objects |
| `delete_first_selected` | 4377 | Delete single object |
| `on_selectall` | 5095 | Select all objects |
| `on_deselect_all` | 4118 | Deselect all |
| `on_copy_name` | 5905 | Copy object name to clipboard |

**Files modified:** `appMain.py`, new `appHandlers/appObjectOps.py`.

---

## Phase 4: Extract Plot Manager (`appHandlers/appPlotManager.py`)

**~15 methods, ~400 lines** — plot enable/disable/toggle/replot.

### Methods to extract:

| Method | Line | Purpose |
|--------|------|---------|
| `plot_all` | 7054 | Re-plot all objects |
| `on_toolbar_replot` | 5800 | Toolbar replot button |
| `on_plots_updated` | 5789 | Plots changed callback |
| `disable_all_plots` | 7589 | Hide all |
| `disable_other_plots` | 7595 | Hide non-selected |
| `enable_all_plots` | 7601 | Show all |
| `enable_other_plots` | 7607 | Show non-selected |
| `on_enable_sel_plots` | 7613 | Show selected |
| `on_disable_sel_plots` | 7621 | Hide selected |
| `enable_plots` | 7629 | Enable plot list |
| `disable_plots` | 7681 | Disable plot list |
| `toggle_plots` | 7736 | Toggle visibility |
| `clear_plots` | 7761 | Clear all plots |
| `gerber_redraw` | 7776 | Redraw Gerber objects |
| `on_set_color_action_triggered` | 7792 | Color context menu |
| `set_obj_color_in_preferences_dict` | 7937 | Save color prefs |

**Files modified:** `appMain.py`, new `appHandlers/appPlotManager.py`.

---

## Phase 5: Extract Signal Connector (`appHandlers/appSignalConnector.py`)

**~10 methods, ~250 lines** — all `connect_*_signals` methods.

### Methods to extract:

| Method | Line | Purpose |
|--------|------|---------|
| `connect_filemenu_signals` | 1906 | File menu signals |
| `connect_editmenu_signals` | 1949 | Edit menu signals |
| `connect_optionsmenu_signals` | 1981 | Options menu signals |
| `connect_menuview_signals` | 2000 | View menu signals |
| `connect_menuhelp_signals` | 2024 | Help menu signals |
| `connect_project_context_signals` | 2035 | Project context menu |
| `connect_canvas_context_signals` | 2051 | Canvas context menu |
| `connect_tools_signals_to_toolbar` | 2080 | Tool toolbar signals |
| `connect_editors_toolbar_signals` | 2117 | Editor toolbar signals |
| `connect_toolbar_signals` | 2132 | Main toolbar signals |

**Files modified:** `appMain.py`, new `appHandlers/appSignalConnector.py`.

---

## Phase 6: Extract UI Actions Handler (`appHandlers/appUIActions.py`)

**~25 methods, ~700 lines** — dialogs, preferences UI, tabs, workspace, grid.

### Methods to extract:

| Method | Line | Purpose |
|--------|------|---------|
| `on_about` | 2969 | About dialog |
| `on_howto` | 3497 | Howto dialog |
| `install_bookmarks` | 3675 | Bookmark menu entries |
| `on_bookmarks_manager` | 3737 | Bookmark manager tab |
| `on_backup_site` | 3766 | Open backup URL |
| `on_toggle_preferences` | 5115 | Toggle preferences panel |
| `on_preferences` | 5133 | Open preferences tab |
| `on_tools_database` | 5213 | Tools database tab |
| `on_geometry_tool_add_from_db_executed` | 5343 | Add tool from DB |
| `on_plot_area_tab_closed` | 5399 | Tab close handler |
| `on_plot_area_tab_double_clicked` | 5457 | Tab double-click |
| `on_notebook_closed` | 5462 | Notebook close handler |
| `on_properties_tab_click` | 7285 | Properties tab click |
| `on_notebook_tab_changed` | 7290 | Tab changed slot |
| `setup_default_properties_tab` | 7318 | Default properties |
| `on_workspace` | 4129 | Workspace setup |
| `on_workspace_modified` | 4122 | Workspace changed |
| `on_workspace_toggle` | 4139 | Toggle workspace |
| `grid_status` | 5815 | Get grid state |
| `populate_cmenu_grids` | 5818 | Grid context menu |
| `set_grid` | 5847 | Apply grid settings |
| `on_grid_add` | 5854 | Add grid value |
| `on_grid_delete` | 5879 | Remove grid value |
| `on_show_log` | 4150 | Show log file |
| `on_cursor_type` | 4159 | Set cursor type |
| `on_3d_area` | 5293 | 3D view tab |

**Files modified:** `appMain.py`, new `appHandlers/appUIActions.py`.

---

## Phase 7: Extract App Lifecycle Handler (`appHandlers/appLifecycle.py`)

**~15 methods, ~400 lines** — startup, shutdown, autosave, version check.

### Methods to extract:

| Method | Line | Purpose |
|--------|------|---------|
| `on_app_restart` | 1627 | Restart application |
| `quit_application` | 3846 | Quit with save prompt |
| `kill_app` | 4005 | Force kill |
| `final_save` | 3794 | Save prefs on quit |
| `start_delayed_quit` | 7979 | Delayed quit timer |
| `check_project_file_size` | 7993 | Verify project save |
| `save_project_auto` | 8010 | Auto-save callback |
| `save_project_auto_update` | 8022 | Update auto-save interval |
| `version_check` | 7400 | Check for updates |
| `on_portable_checked` | 4012 | Portable mode toggle |
| `on_defaults_dict_change` | 4108 | Defaults changed callback |
| `on_defaults2options` | 8038 | Transfer defaults→options |
| `on_options_value_changed` | 1615 | Options changed handler |
| `setup_obj_classes` | 7383 | Configure object classes |
| `on_layout` | 2183 | Set toolbar layout |

**Files modified:** `appMain.py`, new `appHandlers/appLifecycle.py`.

---

## Phase 8: Clean Up Remaining Methods on App

After extraction, **~30 methods remain** directly on `App`. These are either:
- **Thin facade delegates** (one-liners calling handlers)
- **Core identity methods** that genuinely belong on App:
    - `__init__` (now clean, ~30 lines)
    - `info()`, `info_shell()`, `shell_message()` — messaging API
    - `dec_format()` — utility
    - `app_is_idle()`, `abort_all_tasks()` — task control
    - `clear_pool()` — resource management
    - `install_tools()`, `remove_tools()`, `init_tools()` — plugin lifecycle
    - `on_editing_start()`, `on_editing_finished()`, `on_editing_final_action()` — editor lifecycle
    - `on_plotcanvas_setup()`, `on_plotcanvas_add()` — canvas setup
    - `on_zoom_fit()`, `on_zoom_in()`, `on_zoom_out()` — zoom (thin, ~5 lines each)
    - `on_startup_args()` — CLI argument processing
    - Path properties (`tools_database_path`, `defaults_path`, etc.)
    - `register_folder()`, `register_save_folder()`, `register_recent()`, `setup_recent_items()` — file tracking
    - Code editor methods (`init_code_editor`, `on_view_source`, `on_toggle_code_editor`, `on_code_editor_close`)
    - `script_processing()` — Tcl script execution
    - `obj_properties()`, `on_project_context_save()`, `obj_move()` — context menu actions
    - `on_tool_add_keypress()` — shortcut handler
    - `on_gui_coords_clicked()`, `on_flipy` facade, etc.

---

## Execution Order & Risk Management

| Phase | Files Changed | Risk | LOC Moved | Verification |
|-------|-------------|------|-----------|-------------|
| 1 | appMain.py | **Low** — internal restructure only | 0 (reorganized) | App starts, all features work |
| 2 | appMain.py + new file | **Medium** — mouse events are critical | ~700 | Click, drag, hover, selection all work |
| 3 | appMain.py + new file | **Medium** — object ops widely used | ~800 | Copy, delete, rotate, move objects |
| 4 | appMain.py + new file | **Low** — plot toggling is isolated | ~400 | Enable/disable/toggle plots |
| 5 | appMain.py + new file | **Low** — signal wiring is init-time only | ~250 | All menu actions still fire |
| 6 | appMain.py + new file | **Low** — UI actions mostly isolated | ~700 | Dialogs, prefs, grid, workspace |
| 7 | appMain.py + new file | **Low** — lifecycle events are terminal | ~400 | Quit, restart, autosave |
| 8 | appMain.py | **Low** — cleanup only | 0 | Final integration test |

### Per-phase verification:
1. `python flatcam.py` — app launches, all menus/tools accessible
2. Manual testing of the specific feature group extracted
3. Run existing unit tests: `python tests/test_gerber_parser.py` etc.

---

## Naming Convention

All new handler files follow existing convention:

```
appHandlers/
├── appIO.py              # (existing) File I/O
├── appEdit.py            # (existing) Edit/conversion
├── appCanvasEvents.py    # NEW: Mouse/canvas events
├── appObjectOps.py       # NEW: Object transforms/management
├── appPlotManager.py     # NEW: Plot visibility/rendering
├── appSignalConnector.py # NEW: Signal wiring
├── appUIActions.py       # NEW: Dialogs, preferences, workspace
└── appLifecycle.py       # NEW: Startup, shutdown, autosave
```

---

## Facade Pattern Detail

Every extracted method gets a one-liner on `App`:

```python
# Before (method lives on App, 50 lines):
def on_mouse_click_over_plot(self, event):
    # ... 50 lines of logic ...

# After (handler has the logic, App has a facade):
def on_mouse_click_over_plot(self, event):
    self.canvas_events.on_mouse_click_over_plot(event)
```

This means **zero changes needed** in any file that calls `self.app.on_mouse_click_over_plot(event)`. The facade can be removed later once callers are migrated, but that's optional and separate from this refactoring.

---

## What This Does NOT Change

- No method signatures change
- No `self.app.xxx` access patterns change anywhere in the codebase
- No signal names or signatures change
- No import changes in any file outside `appMain.py`
- No mixin usage
- No abstract base classes or over-engineering
- Editors, plugins, parsers, preprocessors are untouched

---

## End State

| Metric | Before | After |
|--------|--------|-------|
| `appMain.py` methods (real logic) | 154 | ~30 core + ~100 one-liner facades |
| `appMain.py` LOC | ~8200 | ~2500 (facades + core + __init__) |
| `__init__` lines | 1136 | ~30 (calls 10 setup methods) |
| Handler files | 2 | 8 |
| External API changes | — | **Zero** |

The App class becomes a **thin orchestrator** — easy to read, easy to navigate, easy to maintain. Each handler is a focused module you can understand in isolation.
