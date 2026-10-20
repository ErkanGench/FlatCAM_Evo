# Headless Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `flatcam.py --headless` runs a FlatScript, inline Tcl commands or a Tcl prompt on stdin, on a machine with no display and no GPU, and ends with an exit code.

**Architecture:** The real `App` starts on the Qt `offscreen` platform. The main window and all forms are built but never shown, so every Tcl command reads real form values. A `NullCanvas` replaces the VisPy `PlotCanvas`, so no OpenGL context is made. A `HeadlessRunner` runs the job after `App()` and ends the process. The shell output goes to stdout/stderr.

**Tech Stack:** Python 3.11+, PyQt6 (offscreen platform), tkinter Tcl, pytest, cx_Freeze.

---

## Rules for every task (read first)

- Work on the local branch `1.0` in `D:\1.Development\1.PROJECTS\FlatCAM_EVO`. Use the interpreter `.venv\Scripts\python.exe`.
- The work tree has files that are not yours: `appPlugins/ToolGrblSender/Sender.py`, `appPlugins/ToolGrblSender/SenderUI.py`, `tests/test_levelling_audit.py`, `appPlugins/Common/ecut/`, `docs/mach3/`, `tests/ecut/`. Do not change, stage or commit them. Never use `git add -A` or `git add .`. Stage only the files of your task, by name.
- Commit messages: no `Co-Authored-By` line, no Claude attribution.
- Do not run Python from a heredoc (`python - <<EOF`). Write a script file in the scratchpad and run the file.
- Run only the test files that the task names. The full suite takes about 4 minutes; do not run it.
- Tests use `unittest`-style or pytest-style functions; both run with `.venv\Scripts\python.exe -m pytest <file> -q`.
- Match the style of the code around your change: comment density, naming, docstrings with `:param:`/`:return:`.

## Exit codes (all tasks use these)

| Code | Meaning |
|---|---|
| 0 | the job ran |
| 1 | a Tcl command failed (Tcl error); the error report is on stderr |
| 2 | bad command line or unreadable `--shellfile` (exists today) |
| N | `exit N` in the script or the prompt |

## File structure

| File | Responsibility |
|---|---|
| `appGUI/NullCanvas.py` (new) | `NullObject` and `NullCanvas`: the canvas of the headless mode |
| `appCommon/Headless.py` (new) | `HeadlessExit`, `console_write()`, `HeadlessRunner` |
| `appMain.py` | `--headless` / `--command` options, `App(headless=...)` switches, `shellvar_commands()` |
| `appObjects/AppObjectTemplate.py`, `appCommon/Common.py`, `appPlugins/ToolDistance.py`, `appPlugins/Common/levelling_core.py` | make shape collections through `plotcanvas.new_shape_collection()` |
| `appPlugins/ToolShell.py` | `TermWidget._append_to_browser()` writes to the console in headless mode |
| `appHandlers/appLifecycle.py` | `quit_application()` ends a headless run without saving preferences |
| `flatcam.py` | offscreen platform, headless excepthook, runs the `HeadlessRunner` |
| `make_freeze.py` (in `.gitignore`, edit it but it is not committed) | `FlatCAM-cli.exe` console executable on Windows |
| `tests/test_null_canvas.py`, `tests/test_headless_console.py`, `tests/test_headless_cli.py`, `tests/test_headless_app.py`, `tests/test_headless_runner.py`, `tests/test_headless_e2e.py` (new) | tests |
| `README.md`, `CHANGELOG.md` | documentation |

---

### Task 1: NullCanvas

**Files:**
- Create: `appGUI/NullCanvas.py`
- Test: `tests/test_null_canvas.py`

- [ ] **Step 1: Write the failing test**

```python
"""
The canvas of the headless mode accepts every call of the application and draws nothing. A number taken from it
raises TypeError, so canvas data can never reach a calculation (G-code) unnoticed.
"""

import pytest

from appGUI.NullCanvas import NullCanvas, NullObject


def test_any_attribute_and_any_call_is_accepted():
    canvas = NullCanvas(app=None)
    canvas.view.camera.zoom(2, (0, 0))
    canvas.graph_event_connect('mouse_move', print)
    canvas.native.setFocus()
    canvas.some_attribute = 5            # ignored
    assert isinstance(canvas.view.scene, NullObject)


def test_shape_collections_and_groups_draw_nothing():
    canvas = NullCanvas(app=None)
    shapes = canvas.new_shape_collection(layers=1)
    group = canvas.new_shape_group()
    texts = canvas.new_text_group()
    for item in (shapes, group, texts):
        item.add(shape=None, color='red', visible=True)
        item.clear(update=True)
        item.redraw()
        item.enabled = True
    assert list(shapes.data) == []
    assert len(group) == 0


def test_it_is_false_in_a_condition():
    assert not NullCanvas(app=None).view


@pytest.mark.parametrize('operation', [
    lambda x: float(x), lambda x: int(x), lambda x: x + 1, lambda x: 1 - x, lambda x: x * 2, lambda x: x / 2,
    lambda x: -x, lambda x: x < 1, lambda x: x >= 1, lambda x: round(x),
])
def test_a_number_from_the_canvas_raises(operation):
    with pytest.raises(TypeError, match='headless canvas'):
        operation(NullCanvas(app=None).view.camera.rect.width)


def test_dunder_lookups_are_not_absorbed():
    # copy, pickle and the Qt bindings probe dunder names; they must see a normal object
    assert not hasattr(NullObject('x'), '__array__')
```

- [ ] **Step 2: Run the test to make sure it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_null_canvas.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'appGUI.NullCanvas'`

- [ ] **Step 3: Write the implementation**

```python
# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# MIT Licence                                              #
# ##########################################################
"""
The canvas of the headless mode (flatcam.py --headless): no window, no OpenGL context, nothing is drawn.

The application calls the plot canvas, its shape collections and its text groups from many places. NullCanvas accepts
all of these calls. Only the display uses the canvas: a number taken from it (float(), int(), arithmetic, an order
comparison) raises TypeError, so canvas data can never reach a calculation such as G-code unnoticed.
"""


class NullObject:
    """
    Accepts any attribute access and any call and returns a NullObject. It is false in a condition and an empty
    collection (len() 0, iteration gives nothing): the headless mode draws nothing.
    """

    __slots__ = ('_name',)

    def __init__(self, name='null'):
        object.__setattr__(self, '_name', name)

    def __getattr__(self, item):
        if item.startswith('__') and item.endswith('__'):
            raise AttributeError(item)
        return NullObject('%s.%s' % (self._name, item))

    def __setattr__(self, key, value):
        pass

    def __call__(self, *args, **kwargs):
        return self

    def __bool__(self):
        return False

    def __len__(self):
        return 0

    def __iter__(self):
        return iter(())

    def __repr__(self):
        return '<NullObject %s>' % self._name

    def _no_number(self, *args):
        raise TypeError("the headless canvas has no data: %s" % self._name)

    __int__ = __float__ = __index__ = __round__ = _no_number
    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = _no_number
    __truediv__ = __rtruediv__ = __floordiv__ = __rfloordiv__ = __neg__ = __abs__ = _no_number
    __lt__ = __le__ = __gt__ = __ge__ = _no_number


class NullCanvas(NullObject):
    """The plot canvas of the headless mode. It has the factory methods of PlotCanvas; all of them draw nothing."""

    __slots__ = ()

    def __init__(self, app=None):
        NullObject.__init__(self, 'plotcanvas')

    def new_shape_collection(self, **kwargs):
        return NullObject('shape_collection')

    def new_shape_group(self, shape_collection=None):
        return NullObject('shape_group')

    def new_text_collection(self, **kwargs):
        return NullObject('text_collection')

    def new_text_group(self, collection=None):
        return NullObject('text_group')

    def new_cursor(self, big=None):
        return NullObject('cursor')
```

- [ ] **Step 4: Run the test to make sure it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_null_canvas.py -q`
Expected: all pass. If `round()` is not caught by `__round__` on your Python, keep `__round__` and remove the `round` case only if Python calls `__round__` for it (check with a quick script file).

- [ ] **Step 5: Commit**

```bash
rtk git add appGUI/NullCanvas.py tests/test_null_canvas.py
rtk git commit -m "feat(headless): NullCanvas, the canvas of the headless mode"
```

---

### Task 2: Shape collections only through the canvas

Five places make a VisPy `ShapeCollection` directly with `parent=self.app.plotcanvas.view.scene`. With `NullCanvas` that parent is not a VisPy node, so the headless start fails. `PlotCanvas.new_shape_collection(**kwargs)` already makes the same object (`appGUI/PlotCanvas.py:502-506`, it adds `pool` and `fcoptions`).

**Files:**
- Modify: `appMain.py:1159-1168`
- Modify: `appObjects/AppObjectTemplate.py:214-215`
- Modify: `appCommon/Common.py:245-246`
- Modify: `appPlugins/ToolDistance.py:87`
- Modify: `appPlugins/Common/levelling_core.py:191-195`
- Test: `tests/test_null_canvas.py` (add a test)

- [ ] **Step 1: Write the failing test** (append to `tests/test_null_canvas.py`)

```python
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# only the canvas classes themselves make a shape collection on their scene
ALLOWED = {os.path.join('appGUI', 'PlotCanvas.py'), os.path.join('appGUI', 'PlotCanvas3d.py')}
SKIPPED_DIRS = {'tests', 'Utils', 'docs', '.venv', 'build', '.git'}


def test_no_shape_collection_is_made_directly_on_the_plot_canvas():
    pattern = re.compile(r'ShapeCollection\(\s*parent\s*=\s*self\.(app\.)?plotcanvas\.view\.scene')
    offenders = []
    for folder, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIPPED_DIRS]
        for name in files:
            if not name.endswith('.py'):
                continue
            path = os.path.join(folder, name)
            relative = os.path.relpath(path, REPO)
            if relative in ALLOWED:
                continue
            with open(path, encoding='utf-8', errors='replace') as f:
                if pattern.search(f.read()):
                    offenders.append(relative)
    assert offenders == []
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_null_canvas.py -q -k directly`
Expected: FAIL, the list holds `appMain.py`, `appObjects\AppObjectTemplate.py`, `appCommon\Common.py`, `appPlugins\ToolDistance.py`, `appPlugins\Common\levelling_core.py`.

- [ ] **Step 3: Change the 5 places**

`appMain.py:1159-1168` becomes:

```python
        try:
            self.tool_shapes = self.plotcanvas.new_shape_collection(layers=1)
        except AttributeError:
            self.tool_shapes = None

        # Storage for Hover Shapes
        self.hover_shapes = self.plotcanvas.new_shape_collection(layers=1)

        # Storage for Selection shapes
        self.sel_shapes = self.plotcanvas.new_shape_collection(layers=1)
```

`appObjects/AppObjectTemplate.py:214-215` becomes:

```python
        self.mark_shapes = self.app.plotcanvas.new_shape_collection(layers=1)
```

`appCommon/Common.py:245-246` becomes:

```python
            self.exclusion_shapes = self.app.plotcanvas.new_shape_collection(layers=1)
```

`appPlugins/ToolDistance.py:87` becomes:

```python
        self.sel_shapes = self.app.plotcanvas.new_shape_collection(layers=1)
```

`appPlugins/Common/levelling_core.py:191-195` becomes:

```python
        self.probing_shapes = self.app.plotcanvas.new_shape_collection(layers=1)
```

After the change, remove each `ShapeCollection` import that has no other use in its file (check each file with a search for `ShapeCollection`). `PlotCanvas.new_shape_collection()` also passes `fcoptions=self.fcapp.options`; that is the same value `AppObjectTemplate` passed before and a harmless extra for the other 4.

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_null_canvas.py tests/test_stage4_shared_methods.py tests/test_unify_regressions_0b.py tests/test_levelling_tool.py tests/test_tool_distance_snap.py -q`
Expected: all pass. A test that mocks `plotcanvas` and counts `new_shape_collection` calls (for example `tests/test_unify_regressions_0b.py:198`) can now count 1 more call per object. If such a count fails, check that the new count is exactly the old count plus the `mark_shapes` call, and change the expected number in the test with a comment that says why.

- [ ] **Step 5: Commit**

```bash
rtk git add appMain.py appObjects/AppObjectTemplate.py appCommon/Common.py appPlugins/ToolDistance.py appPlugins/Common/levelling_core.py tests/test_null_canvas.py
rtk git commit -m "refactor(canvas): shape collections are made through plotcanvas.new_shape_collection()"
```

(Add any test file you changed in step 4 to the `git add` line.)

---

### Task 3: The `--headless` and `--command` options

**Files:**
- Modify: `appMain.py:171-201` (class body of `App`) and `appMain.py:1495-1536` (`_setup_startup`)
- Test: `tests/test_headless_cli.py`

- [ ] **Step 1: Write the failing test**

```python
"""The --headless and --command options are parsed in the class body of App, before anything starts."""

import os
import subprocess
import sys
import textwrap

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parse(argv, tmp_path):
    code = textwrap.dedent(f'''
        import sys
        sys.path.insert(0, {REPO!r})
        sys.argv = ['flatcam.py'] + {argv!r}
        import appMain
        A = appMain.App
        print(repr((A.cmd_line_headless, A.cmd_line_command, A.cmd_line_shellvar)))
    ''')
    return subprocess.run([sys.executable, '-c', code], cwd=str(tmp_path), capture_output=True, text=True,
                          timeout=300)


def test_without_options(tmp_path):
    result = _parse([], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "(False, '', '')"


def test_headless_and_command(tmp_path):
    result = _parse(['--headless', '--command=new_geometry g; puts ok', '--shellvar=1,2'], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "(True, 'new_geometry g; puts ok', '1,2')"


def test_the_help_names_the_new_options(tmp_path):
    result = _parse(['-h', 'x'], tmp_path)
    assert '--headless' in result.stdout
    assert '--command' in result.stdout
```

Note: `-h` is declared as `"h:"` in the current `getopt` call (it takes a value), so the test passes `-h x`. Keep that declaration as it is.

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_headless_cli.py -q`
Expected: FAIL, `AttributeError: type object 'App' has no attribute 'cmd_line_headless'` (and the getopt error for `--headless`).

- [ ] **Step 3: Write the implementation**

In the class body of `App` (`appMain.py:171-201`):

```python
    # #################################### Get Cmd Line Options #####################################################
    cmd_line_shellfile = ''
    cmd_line_shellvar = ''
    cmd_line_command = ''
    cmd_line_headless = False

    cmd_line_help = (
        "FlatCam.py --shellfile=<cmd_line_shellfile>\n"
        "FlatCam.py --shellvar=<1,'C:\\path',23>\n"
        "FlatCam.py --command=\"<Tcl commands, separated by ;>\"\n"
        "FlatCam.py --headless [--shellfile=...] [--shellvar=...] [--command=...]\n"
        "    no window and no OpenGL; without --shellfile and --command the Tcl commands are read from stdin.\n"
        "    Exit code: 0 done, 1 a Tcl command failed, 2 bad command line, N for 'exit N'."
    )
    try:
        # Multiprocessing pool will spawn additional processes with 'multiprocessing-fork' flag
        cmd_line_options, args = getopt.getopt(
            sys.argv[1:],
            "h:",
            [
                "shellfile=",
                "shellvar=",
                "command=",
                "headless",
                "multiprocessing-fork="
            ]
        )
    except getopt.GetoptError:
        print(cmd_line_help)
        sys.exit(2)

    for opt, arg in cmd_line_options:
        if opt == '-h':
            print(cmd_line_help)
            sys.exit()
        elif opt == '--shellfile':
            cmd_line_shellfile = arg
        elif opt == '--shellvar':
            cmd_line_shellvar = arg
        elif opt == '--command':
            cmd_line_command = arg
        elif opt == '--headless':
            cmd_line_headless = True
```

Move the `--shellvar` conversion out of `_setup_startup` into a method of `App`, so the GUI start and the headless runner use the same code. Put the method directly before `_setup_startup`:

```python
    def shellvar_commands(self):
        """
        :return: the Tcl commands that set shellvar_0, shellvar_1 ... from the --shellvar option
        """
        commands = []
        if not self.cmd_line_shellvar:
            return commands
        for cnt, i in enumerate(self.cmd_line_shellvar.split(',')):
            # noinspection PyBroadException
            try:
                command_tcl = eval(i)
            except Exception:
                command_tcl = i
            command_tcl_formatted = 'set shellvar_{nr} "{cmd}"'.format(cmd=str(command_tcl), nr=str(cnt))
            # if there are Windows paths then replace the path separator with a Unix like one
            if sys.platform == 'win32':
                command_tcl_formatted = command_tcl_formatted.replace('\\', '/')
            commands.append(command_tcl_formatted)
        return commands
```

In `_setup_startup`, replace the `if self.cmd_line_shellvar:` block (`appMain.py:1495-1517`) with:

```python
        if self.cmd_line_shellvar:
            try:
                for command_tcl_formatted in self.shellvar_commands():
                    self.shell.exec_command(command_tcl_formatted, no_echo=True)
            except Exception as ext:
                print("ERROR: ", ext)
                sys.exit(2)
```

After the `if self.cmd_line_shellfile:` block (ends at `appMain.py:1536`), add:

```python
        if self.cmd_line_command:
            if self.ui.shell_dock.isHidden():
                self.ui.shell_dock.show()
            self.shell.exec_command(self.cmd_line_command)
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_headless_cli.py tests/test_start_dir.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
rtk git add appMain.py tests/test_headless_cli.py
rtk git commit -m "feat(cli): --headless and --command options; shellvar_commands() shared by the GUI and headless starts"
```

---

### Task 4: Console output and HeadlessExit

**Files:**
- Create: `appCommon/Headless.py`
- Modify: `appPlugins/ToolShell.py:124-128` (`TermWidget._append_to_browser`)
- Test: `tests/test_headless_console.py`

- [ ] **Step 1: Write the failing test**

```python
"""In headless mode the shell output goes to stdout, the errors go to stderr, without HTML."""

import io
from types import SimpleNamespace

from appCommon.Headless import HeadlessExit, console_text, console_write


def _write(style, text):
    out, err = io.StringIO(), io.StringIO()
    console_write(style, text, out=out, err=err)
    return out.getvalue(), err.getvalue()


def test_output_goes_to_stdout():
    assert _write('out', 'hello\n') == ('hello\n', '')
    assert _write('success', '[success] Saved\n') == ('[success] Saved\n', '')
    assert _write('warning', '[WARNING] careful\n') == ('[WARNING] careful\n', '')


def test_errors_go_to_stderr():
    assert _write('err', 'ERROR Report: boom\n') == ('', 'ERROR Report: boom\n')
    assert _write('out', '[ERROR_NOTCL] Failed\n') == ('', '[ERROR_NOTCL] Failed\n')


def test_selected_and_input_echo_are_not_written():
    assert _write('selected', 'x\n') == ('', '')
    assert _write('in', '> help\n') == ('', '')


def test_raw_html_is_plain_text():
    assert console_text('<b>a</b><br>b &amp; c<br/>') == 'a\nb & c\n'
    assert _write('raw', '<span>x</span>\n') == ('x\n', '')


def test_headless_exit_is_not_an_exception():
    # the Tcl command wrappers catch Exception; HeadlessExit must pass through them
    assert not issubclass(HeadlessExit, Exception)
    assert HeadlessExit(3).code == 3


def test_the_shell_widget_writes_to_the_console_in_headless_mode(capsys):
    from appPlugins.ToolShell import TermWidget
    fake = SimpleNamespace(app=SimpleNamespace(headless_console=True))
    TermWidget._append_to_browser(fake, 'out', 'from the shell\n')
    assert capsys.readouterr().out == 'from the shell\n'
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_headless_console.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'appCommon.Headless'`

- [ ] **Step 3: Write `appCommon/Headless.py`**

```python
# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# MIT Licence                                              #
# ##########################################################
"""
The headless mode (flatcam.py --headless): the application runs a FlatScript, the --command text or a Tcl prompt on
stdin with no window and no OpenGL, writes the shell output to stdout / stderr and ends with an exit code.
"""

import html
import re
import sys


class HeadlessExit(BaseException):
    """
    Ends a headless run: quit_app and the Tcl exit. A BaseException because the Tcl command wrappers catch Exception.
    """

    def __init__(self, code=0):
        super().__init__(code)
        self.code = code


_TAG_RE = re.compile(r'<[^>]+>')


def console_text(text):
    """
    :param text: a shell message that can hold HTML (the raw messages of help, get_path ...)
    :return: the plain text
    """
    text = text.replace('<br/>', '\n').replace('<br>', '\n')
    return html.unescape(_TAG_RE.sub('', text))


def console_write(style, text, out=None, err=None):
    """
    Writes a shell message to the console.

    :param style: the style of TermWidget._append_to_browser(): in, out, err, warning, success, selected or raw
    :param text: the message
    :param out: the stream for the output, default sys.stdout
    :param err: the stream for the errors, default sys.stderr
    :return: None
    """

    # 'in' is the echo of a typed command and the banner of the shell, 'selected' a canvas selection
    if style in ('in', 'selected') or not text:
        return
    if style == 'raw':
        text = console_text(text)
    is_error = style == 'err' or text.lstrip().upper().startswith('[ERROR')
    stream = (err or sys.stderr) if is_error else (out or sys.stdout)
    stream.write(text)
    stream.flush()
```

- [ ] **Step 4: Hook the shell widget**

At the start of `TermWidget._append_to_browser` in `appPlugins/ToolShell.py` (after the docstring, before the `assert`):

```python
        if getattr(self.app, 'headless_console', False):
            # headless mode: the widget is never shown, the console is the output
            console_write(style, text)
            return
```

Add the import near the other imports of `appPlugins/ToolShell.py`:

```python
from appCommon.Headless import console_write
```

- [ ] **Step 5: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_headless_console.py tests/test_tcl_audit_regressions.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
rtk git add appCommon/Headless.py appPlugins/ToolShell.py tests/test_headless_console.py
rtk git commit -m "feat(headless): the shell output goes to stdout / stderr in headless mode"
```

---

### Task 5: App switches for the headless mode

**Files:**
- Modify: `appMain.py` (`__init__` near line 341-344, `_setup_logging` 566-577, `_setup_paths_and_config` 699, the `self._show_splash = show_splash` line near 952, `_setup_gui` 1154, `_setup_system_integration` 1330, `_setup_startup` 1463-1492, `on_plotcanvas_setup` 4020)
- Modify: `appHandlers/appLifecycle.py:352-364` (`quit_application`)
- Test: `tests/test_headless_app.py`

- [ ] **Step 1: Write the failing test**

```python
"""The switches of App for the headless mode, tested on the methods without a full App."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from appCommon.Headless import HeadlessExit
from appGUI.NullCanvas import NullCanvas


def test_the_headless_canvas_is_the_null_canvas():
    from appMain import App
    fake = SimpleNamespace(headless=True, log=Mock())
    canvas = App.on_plotcanvas_setup(fake)
    assert isinstance(canvas, NullCanvas)
    assert fake.app_cursor is not None


def test_quit_in_headless_mode_ends_the_run_and_saves_nothing():
    from appHandlers.appLifecycle import AppLifecycle
    app = Mock()
    app.headless = True
    app.headless_exit_code = None
    lifecycle = AppLifecycle(app=app)
    with pytest.raises(HeadlessExit) as info:
        lifecycle.quit_application(silent=True)
    assert info.value.code == 0
    assert app.headless_exit_code == 0
    app.preferencesUiManager.save_defaults.assert_not_called()


def test_quit_in_gui_mode_is_unchanged():
    from appHandlers.appLifecycle import AppLifecycle
    import inspect
    source = inspect.getsource(AppLifecycle.quit_application)
    assert 'save_defaults' in source
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_headless_app.py -q`
Expected: FAIL (the canvas test fails on `PlotCanvas(self)`, the quit test does not raise).

- [ ] **Step 3: Write the implementation**

1. `App.__init__`: change the signature to `def __init__(self, qapp, user_defaults=True, headless=None):` and add the docstring parameter `:param headless: no window and no OpenGL; default the --headless option`. Directly after `self.qapp = qapp` add:

```python
        # headless mode (--headless): no window, no OpenGL canvas, the HeadlessRunner of flatcam.py runs the job
        self.headless = App.cmd_line_headless if headless is None else headless
        # True while the HeadlessRunner runs: the shell output then goes to stdout / stderr
        self.headless_console = False
        # set by quit_app / exit in headless mode
        self.headless_exit_code = None
```

2. `_setup_logging`: after `handler.setFormatter(formatter)` add:

```python
        if self.headless:
            # the console is the output of a headless run: only warnings and errors of the log go there
            handler.setLevel(logging.WARNING)
```

3. `_setup_paths_and_config`: change `if sys.platform == 'win32':` (line 699, the ArgsThread block) to:

```python
        # a headless run never hands its arguments to an open instance (ArgsThread.my_loop() then ends this process)
        if sys.platform == 'win32' and not self.headless:
```

4. Splash: at the line `self._show_splash = show_splash` (near line 952), change it to `self._show_splash = show_splash and not self.headless`. Read the lines before it: if the splash widget is created before that line from the same `show_splash` value, put `and not self.headless` into that condition too, so no splash widget is made.

5. `on_plotcanvas_setup`: at the start of the method body (after the docstring) add:

```python
        if self.headless:
            self.log.debug("Setting up canvas: none (headless)")
            plotcanvas = NullCanvas(self)
            self.app_cursor = plotcanvas.new_cursor()
            return plotcanvas
```

and add `from appGUI.NullCanvas import NullCanvas` next to `from appGUI.PlotCanvas import PlotCanvas` in the imports of `appMain.py`.

6. `_setup_gui`: change `self.on_plotcanvas_add(self.plotcanvas, self.ui.right_layout)` (line 1154) to:

```python
        if not self.headless:
            self.on_plotcanvas_add(self.plotcanvas, self.ui.right_layout)
```

7. `_setup_system_integration`: change the tray condition to:

```python
        if self.options.get("global_systray_icon", self.defaults.get("global_systray_icon")) and not self.headless:
```

8. `_setup_startup`: after the three `self.log.debug(...)` lines at its start add:

```python
        if self.headless:
            # no window, no tray, no update check; the HeadlessRunner of flatcam.py runs --shellvar, --shellfile,
            # --command or the Tcl prompt
            return
```

9. `appHandlers/appLifecycle.py`, `quit_application`: at the start of the method body (before `if not self._confirm_tools_database():`) add:

```python
        if getattr(self.app, 'headless', False):
            # headless mode: quit_app ends the run; the preferences and the window state of the user stay as they are
            self.app.headless_exit_code = 0
            raise HeadlessExit(0)
```

and add `from appCommon.Headless import HeadlessExit` to the imports of `appHandlers/appLifecycle.py`.

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_headless_app.py tests/test_lifecycle_initialization.py tests/test_vispy_only_backend.py tests/test_appmain.py -q`
Expected: all pass. If a test builds a fake app with `Mock()` and calls `quit_application`, `getattr(Mock(), 'headless', False)` is a truthy Mock: in such a test set `headless = False` on the mock, with a comment. This applies to at least `TestAppShutdownSequence.test_quit_application_with_proper_preferencesUiManager` and `TestAppShutdownSequence.test_quit_application_before_the_event_loop_still_ends_the_app` in `tests/test_lifecycle_initialization.py`.

- [ ] **Step 5: Commit**

```bash
rtk git add appMain.py appHandlers/appLifecycle.py tests/test_headless_app.py
rtk git commit -m "feat(headless): App(headless=True) uses the NullCanvas, no window, no tray, no ArgsThread"
```

---

### Task 6: HeadlessRunner and flatcam.py

`_tkinter` does not re-raise a Python exception of a Tcl callback after `tcl.eval()`: it gives a `TclError`. So `quit_app` and `exit` store the exit code in `app.headless_exit_code` before they raise, and the runner reads it when `tcl.eval()` raises.

**Files:**
- Modify: `appCommon/Headless.py` (add `HeadlessRunner`)
- Modify: `flatcam.py:50-211`
- Test: `tests/test_headless_runner.py`, `tests/test_headless_e2e.py` (first test)

- [ ] **Step 1: Write the failing unit tests**

```python
"""HeadlessRunner on a real Tcl interpreter and a fake app."""

import io
import tkinter
from types import SimpleNamespace
from unittest.mock import Mock

from appCommon.Headless import HeadlessExit, HeadlessRunner


def _app(**options):
    tcl = tkinter.Tcl()
    app = SimpleNamespace(
        shell=SimpleNamespace(tcl=tcl), headless_console=False, headless_exit_code=None,
        cmd_line_shellfile=options.get('shellfile', ''), cmd_line_command=options.get('command', ''),
        shellvar_commands=lambda: options.get('shellvar', []),
        workers=Mock(pending_count=Mock(return_value=0)), pool=Mock(),
    )
    return app


def _run(app, stdin=''):
    out, err = io.StringIO(), io.StringIO()
    code = HeadlessRunner(app, stdin=io.StringIO(stdin), out=out, err=err).run()
    return code, out.getvalue(), err.getvalue()


def test_a_command_runs_and_its_result_is_written():
    code, out, err = _run(_app(command='set a 5; expr {$a * 2}'))
    assert (code, out, err) == (0, '10\n', '')


def test_a_tcl_error_gives_exit_code_1_and_the_report_on_stderr():
    code, out, err = _run(_app(command='no_such_command'))
    assert code == 1
    assert 'invalid command name "no_such_command"' in err


def test_exit_n_gives_exit_code_n_and_stops_the_script():
    code, out, err = _run(_app(command='exit 3; set never 1'))
    assert code == 3
    assert err == ''


def test_quit_app_raising_headless_exit_in_a_callback_ends_the_run():
    app = _app(command='fake_quit; set never 1')

    def fake_quit():
        app.headless_exit_code = 0
        raise HeadlessExit(0)

    app.shell.tcl.createcommand('fake_quit', fake_quit)
    code, out, err = _run(app)
    assert code == 0
    assert app.shell.tcl.eval('info exists never') == '0'


def test_shellvar_then_shellfile_then_command(tmp_path):
    script = tmp_path / 'job.FlatScript'
    # the last command of the file gives an empty result, so only the result of --command is written
    script.write_text('set b "$shellvar_0-file"\nset unused ""\n')
    app = _app(shellvar=['set shellvar_0 "var"'], shellfile=str(script), command='set b')
    code, out, err = _run(app)
    assert (code, out) == (0, 'var-file\n')


def test_the_prompt_reads_complete_commands_from_stdin():
    stdin = 'set x {\n1 2\n}\nllength $x\nno_such_command\nset y 1\n'
    code, out, err = _run(_app(), stdin=stdin)
    assert '2\n' in out
    assert 'invalid command name' in err
    assert code == 1   # a command failed; the prompt went on with the next one


def test_the_prompt_ends_at_exit():
    code, out, err = _run(_app(), stdin='exit 4\nset never 1\n')
    assert code == 4


def test_the_console_is_switched_on_and_the_pool_stopped():
    app = _app(command='set a 1')
    _run(app)
    assert app.headless_console is True
    app.pool.terminate.assert_called_once_with()
    app.workers.quit.assert_called_once_with()
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_headless_runner.py -q`
Expected: FAIL, `ImportError: cannot import name 'HeadlessRunner'`

- [ ] **Step 3: Write `HeadlessRunner`** (append to `appCommon/Headless.py`; add `import tkinter as tk` and `from PyQt6 import QtCore` to its imports)

```python
class HeadlessRunner:
    """
    Runs the job of a headless start in this order: --shellvar, --shellfile, --command. Without --shellfile and
    --command it reads Tcl commands from stdin (a prompt when stdin is a terminal).
    """

    def __init__(self, app, stdin=None, out=None, err=None):
        """
        :param app: the App, started with headless=True
        :param stdin: the stream of the prompt, default sys.stdin
        :param out: the stream for the output, default sys.stdout
        :param err: the stream for the errors, default sys.stderr
        """
        self.app = app
        self.tcl = app.shell.tcl
        self.stdin = stdin
        self.out = out
        self.err = err

    def run(self):
        """
        :return: the exit code: 0 done, 1 a Tcl command failed, N for 'exit N'
        """
        self.app.headless_console = True
        self._install_exit()
        try:
            try:
                for command in self.app.shellvar_commands():
                    self._eval(command, echo=False)
                if self.app.cmd_line_shellfile:
                    with open(self.app.cmd_line_shellfile, 'r') as f:
                        self._eval(f.read())
                if self.app.cmd_line_command:
                    self._eval(self.app.cmd_line_command)
                code = 0
                if not (self.app.cmd_line_shellfile or self.app.cmd_line_command):
                    code = self._prompt()
            except HeadlessExit as stop:
                code = stop.code
            except tk.TclError:
                code = 1
            self._wait_for_workers()
        finally:
            self._shutdown()
        return code

    def _install_exit(self):
        def tcl_exit(code='0'):
            self.app.headless_exit_code = int(code)
            raise HeadlessExit(int(code))

        # the Tcl exit would end the process at once, without stopping the process pool
        if self.tcl.eval('info commands flatcam_tcl_exit') == '':
            self.tcl.eval('rename exit flatcam_tcl_exit')
        self.tcl.createcommand('exit', tcl_exit)

    def _eval(self, text, echo=True):
        """
        Runs Tcl code. A Tcl error is written to stderr and raised again; quit_app and exit raise HeadlessExit.
        """
        try:
            result = self.tcl.eval(text)
        except tk.TclError:
            if self.app.headless_exit_code is not None:
                raise HeadlessExit(self.app.headless_exit_code)
            console_write('err', 'ERROR Report: %s\n' % self.tcl.eval('set errorInfo'), out=self.out, err=self.err)
            raise
        if echo and result not in ('', 'None'):
            console_write('out', '%s\n' % result, out=self.out, err=self.err)
        return result

    def _prompt(self):
        """
        :return: 0, or 1 when a command failed; the prompt goes on after a failed command
        """
        stdin = self.stdin or sys.stdin
        out = self.out or sys.stdout
        interactive = stdin.isatty()
        failed = False
        buffer = ''
        while True:
            if interactive:
                out.write('> ' if buffer else '% ')
                out.flush()
            line = stdin.readline()
            if not line:
                break
            buffer += line
            if not self.tcl.getboolean(self.tcl.call('info', 'complete', buffer)):
                continue
            command, buffer = buffer, ''
            if not command.strip():
                continue
            try:
                self._eval(command)
            except tk.TclError:
                failed = True
        return 1 if failed else 0

    def _wait_for_workers(self):
        qapp = QtCore.QCoreApplication.instance()
        while True:
            if qapp is not None:
                qapp.processEvents()
            if self.app.workers.pending_count() == 0:
                break
            QtCore.QThread.msleep(20)
        if qapp is not None:
            qapp.processEvents()

    def _shutdown(self):
        try:
            self.app.pool.terminate()
            self.app.pool.join()
        except (ValueError, AttributeError):
            pass
        self.app.workers.quit()
        for stream in (self.out or sys.stdout, self.err or sys.stderr):
            stream.flush()
```

- [ ] **Step 4: Run the unit tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_headless_runner.py -q`
Expected: all pass.

- [ ] **Step 5: Wire `flatcam.py`**

1. Directly before `app = QtWidgets.QApplication(sys.argv)` (line 172) add:

```python
    if App.cmd_line_headless:
        # no display and no GPU: Qt draws nothing and needs no X11, Wayland or Windows desktop
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
```

2. In `excepthook` (line 124), as its first lines:

```python
        if App.cmd_line_headless:
            # no window for a message box: the traceback goes to stderr and the run ends with exit code 1
            sys.stderr.write("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
            sys.stderr.flush()
            os._exit(1)
```

3. Directly after `fc = App(qapp=app)` (line 200) add:

```python
    if fc.headless:
        from appCommon.Headless import HeadlessRunner
        os._exit(HeadlessRunner(fc).run())
```

- [ ] **Step 6: Write the first end-to-end test** (`tests/test_headless_e2e.py`)

```python
"""flatcam.py --headless in a new process, without a display setting (QT_QPA_PLATFORM not set)."""

import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_headless(args, cwd, stdin=None, timeout=300):
    env = dict(os.environ)
    env.pop('QT_QPA_PLATFORM', None)
    return subprocess.run([sys.executable, os.path.join(REPO, 'flatcam.py'), '--headless'] + args, cwd=str(cwd),
                          input=stdin, capture_output=True, text=True, timeout=timeout, env=env)


def test_a_command_writes_a_project(tmp_path):
    result = run_headless(['--command=new_geometry g; save_project out.FlatPrj'], tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'out.FlatPrj').is_file()
```

- [ ] **Step 7: Run it and make the headless start work**

Run: `.venv\Scripts\python.exe -m pytest tests/test_headless_e2e.py -q`

The first runs can fail during `App()` because a place passes a part of the `NullCanvas` to a Qt function (for example `layout.addWidget(self.plotcanvas.native)`, `installEventFilter(...)`, a `connect()` on a canvas signal). Qt raises `TypeError` for a `NullObject`. For each such failure:
1. Read the traceback in `result.stderr` (print it in the test failure message as above).
2. Guard only that line with `if not self.headless:` (or `if not self.app.headless:` in a plugin). Do not guard more than the failing line. Never let a guard skip a value that a Tcl command reads.
3. Run the test again.

Write each guarded place (file:line, what it did) into the commit message. Expected at the end: PASS, and `out.FlatPrj` exists.

- [ ] **Step 8: Commit**

```bash
rtk git add appCommon/Headless.py flatcam.py tests/test_headless_runner.py tests/test_headless_e2e.py
rtk git commit -m "feat(headless): HeadlessRunner runs --shellvar, --shellfile, --command or the Tcl prompt and ends the process"
```

(Add every file you guarded in step 7 to the `git add` line.)

---

### Task 7: End-to-end tests of the headless mode

**Files:**
- Modify: `tests/test_headless_e2e.py`

- [ ] **Step 1: Add the tests**

```python
import shutil

EXAMPLE_GERBER = os.path.join(REPO, 'assets', 'examples', 'files', 'test.gbr')


def test_nothing_from_the_shell_banner_or_the_log_debug_reaches_stdout(tmp_path):
    result = run_headless(['--command=puts hello'], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'hello\n'


def test_a_failed_command_gives_exit_code_1(tmp_path):
    result = run_headless(['--command=no_such_command'], tmp_path)
    assert result.returncode == 1
    assert 'invalid command name "no_such_command"' in result.stderr


def test_exit_n(tmp_path):
    result = run_headless(['--command=exit 3'], tmp_path)
    assert result.returncode == 3, result.stderr


def test_quit_app_stops_the_script(tmp_path):
    result = run_headless(['--command=quit_app; new_geometry g; save_project after.FlatPrj'], tmp_path)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / 'after.FlatPrj').exists()


def test_shellfile_with_a_relative_name_and_shellvar(tmp_path):
    (tmp_path / 'job.FlatScript').write_text('new_geometry g\nsave_project $shellvar_0\n')
    result = run_headless(['--shellfile=job.FlatScript', '--shellvar=var.FlatPrj'], tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'var.FlatPrj').is_file()


def test_the_prompt_reads_stdin(tmp_path):
    result = run_headless([], tmp_path, stdin='puts hello\nnew_geometry g\nsave_project r.FlatPrj\n')
    assert result.returncode == 0, result.stderr
    assert 'hello' in result.stdout
    assert (tmp_path / 'r.FlatPrj').is_file()


def test_gerber_to_gcode(tmp_path):
    shutil.copy(EXAMPLE_GERBER, tmp_path / 'test.gbr')
    script = (
        'open_gerber test.gbr -outname board\n'
        'isolate board -dia 0.2 -outname iso\n'
        'cncjob iso -dia 0.2 -z_cut -0.1 -z_move 2 -feedrate 100 -outname cnc\n'
        'write_gcode cnc out.nc\n'
    )
    (tmp_path / 'job.FlatScript').write_text(script)
    result = run_headless(['--shellfile=job.FlatScript'], tmp_path)
    assert result.returncode == 0, result.stderr + result.stdout
    gcode = (tmp_path / 'out.nc').read_text()
    moves = [line for line in gcode.splitlines() if line.startswith(('G01', 'G1 ')) and 'X' in line]
    assert len(moves) > 10
```

- [ ] **Step 2: Run them**

Run: `.venv\Scripts\python.exe -m pytest tests/test_headless_e2e.py -q`
Expected: all pass. Each test starts the app (about 10 s each).

If `test_gerber_to_gcode` fails because a name differs (for example `isolate` makes `iso` with a suffix), run the script once with `get_names` added at the end (`--command` or a temporary script in the scratchpad), read the real names in stdout, and change the script of the test. Do not change the application for this.

If a test fails because the app crashes during a command (a `NullObject` reaches a Qt function), fix it as in Task 6 step 7: guard only the failing line with `if not self.app.headless:` and name it in the commit message.

- [ ] **Step 3: Commit**

```bash
rtk git add tests/test_headless_e2e.py
rtk git commit -m "test(headless): exit codes, quit_app, shellfile, prompt and a Gerber to G-code job"
```

(Add every application file you guarded in step 2.)

---

### Task 8: FlatCAM-cli.exe in the frozen build

On Windows `FlatCAM.exe` uses the `gui` base: it has no stdout, stderr or stdin, so a headless run shows nothing. A second executable with the console base runs the same `flatcam.py`.

`make_freeze.py` is in `.gitignore` (`.gitignore:24`): change it, but it is not committed. `tests/test_make_freeze.py` is tracked.

**Files:**
- Modify: `make_freeze.py` (`MAIN_EXE_NAME` area, `make_main_executable`, `create_main_freezer`, `validate_main_stage`)
- Test: `tests/test_make_freeze.py`

- [ ] **Step 1: Read `tests/test_make_freeze.py`** to see how it replaces `make_freeze.Executable` and `make_freeze.Freezer` with fakes. Write the new test in the same style:

```python
    def test_windows_has_a_console_executable_for_headless_runs(self):
        created = []

        def fake_executable(script, **kwargs):
            created.append((Path(script).name, kwargs))
            return SimpleNamespace(script=script, kwargs=kwargs)

        with patch.object(make_freeze, 'Executable', fake_executable), \
                patch.object(make_freeze.sys, 'platform', 'win32'):
            executables = make_freeze.make_main_executables(make_freeze.ROOT)

        self.assertEqual(
            [('flatcam.py', {'target_name': 'FlatCAM.exe', 'base': 'gui'}),
             ('flatcam.py', {'target_name': 'FlatCAM-cli.exe'})],
            created)
        self.assertEqual(2, len(executables))

    def test_other_platforms_have_one_executable(self):
        with patch.object(make_freeze, 'Executable', lambda script, **kwargs: kwargs), \
                patch.object(make_freeze.sys, 'platform', 'linux'):
            self.assertEqual(1, len(make_freeze.make_main_executables(make_freeze.ROOT)))
```

Use the imports that the file already has; add `SimpleNamespace` / `patch` imports only if they are missing.

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_make_freeze.py -q`
Expected: FAIL, `AttributeError: module 'make_freeze' has no attribute 'make_main_executables'`

- [ ] **Step 3: Write the implementation in `make_freeze.py`**

After `MAIN_EXE_NAME = "FlatCAM.exe"` add:

```python
# Windows: FlatCAM.exe has no console (gui base); flatcam.py --headless needs stdout, stderr and stdin
CLI_EXE_NAME = "FlatCAM-cli.exe"
```

After `make_main_executable` add:

```python
def make_main_executables(root: Path = ROOT):
    """Create the cx_Freeze definitions of the main stage: the GUI executable and, on Windows, the console one."""
    executables = [make_main_executable(root)]
    if sys.platform == "win32":
        executables.append(_load_executable()(str(Path(root) / MAIN_SCRIPT.name), target_name=CLI_EXE_NAME))
    return executables
```

In `create_main_freezer`, change `executables=[make_main_executable(root)],` to `executables=make_main_executables(root),`.

In `validate_main_stage`, after the check of `MAIN_EXE_NAME` add:

```python
    if sys.platform == "win32" and not (stage_dir / CLI_EXE_NAME).is_file():
        raise RuntimeError(f"Frozen main application is missing {CLI_EXE_NAME}")
```

If an existing test of `validate_main_stage` builds a stage folder with only `FlatCAM.exe` and runs on Windows, add `FlatCAM-cli.exe` to that folder in the test.

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_make_freeze.py -q`
Expected: all pass.

- [ ] **Step 5: Commit** (only the test; `make_freeze.py` is ignored)

```bash
rtk git add tests/test_make_freeze.py
rtk git commit -m "test(freeze): Windows gets FlatCAM-cli.exe, a console executable for headless runs"
```

---

### Task 9: Documentation

**Files:**
- Modify: `README.md` (add a section)
- Modify: `CHANGELOG.md` (the `20.10.2026` section at the top)

- [ ] **Step 1: Add to `README.md`** a section `## Headless mode` after the section that describes how to start the application:

````markdown
## Headless mode

`--headless` runs FlatCAM with no window and no OpenGL, for example on a build server or in a container with no display.

```bash
python flatcam.py --headless --shellfile=job.FlatScript --shellvar=board.gbr,out.nc
python flatcam.py --headless --command="open_gerber board.gbr -outname b; isolate b -dia 0.2 -outname iso"
python flatcam.py --headless            # a Tcl prompt; or pipe the commands: ... --headless < job.tcl
```

- The order is: `--shellvar` (sets `shellvar_0`, `shellvar_1` ...), `--shellfile`, `--command`. Without `--shellfile` and `--command`, the commands are read from stdin.
- Relative file names are relative to the folder where FlatCAM was started.
- The output of the commands goes to stdout, errors go to stderr.
- `quit_app` or `exit N` ends the run. The preferences of the user are read but not changed.
- Exit codes: `0` done, `1` a Tcl command failed, `2` bad command line or unreadable `--shellfile`, `N` for `exit N`.
- Windows frozen build: use `FlatCAM-cli.exe` (it has a console); `FlatCAM.exe` has no console output.
- Linux: Qt needs these libraries even with no display: `libgl1 libegl1 libglu1-mesa libxkbcommon0 libfontconfig1 libdbus-1-3`. Example for Debian/Ubuntu:

```bash
apt-get install -y libgl1 libegl1 libglu1-mesa libxkbcommon0 libfontconfig1 libdbus-1-3
```
````

- [ ] **Step 2: Add to `CHANGELOG.md`**, in the `20.10.2026` section, a new block before `Packaging:`:

```markdown
Headless mode:

- new: flatcam.py --headless runs a FlatScript (--shellfile), Tcl commands (--command) or a Tcl prompt on stdin with no window and no OpenGL (Qt offscreen platform), for build servers and containers with no display; the output goes to stdout, the errors to stderr; exit code 0 done, 1 a Tcl command failed, 2 bad command line, N for 'exit N'
- new: --command="cmd1; cmd2" runs Tcl commands after the --shellfile, also in GUI mode
- in headless mode quit_app ends the run and the preferences of the user are not saved; a headless run never hands its arguments to an open FlatCAM window
- the frozen Windows build has FlatCAM-cli.exe, a console executable for headless runs
```

- [ ] **Step 3: Commit**

```bash
rtk git add README.md CHANGELOG.md
rtk git commit -m "docs(headless): README section and changelog"
```

---

### Task 10: Tcl commands do not plot

Rule of the project: a Tcl command makes no plot; only `plot_all` and `plot_objects` draw. All object-creating commands pass `plot=False` to `new_object()` except `tclCommands/TclCommandInteriors.py:70`. In headless mode `plot_all` and `plot_objects` have nothing to draw on.

**Files:**
- Modify: `tclCommands/TclCommandInteriors.py:70`
- Modify: `tclCommands/TclCommandPlotAll.py` (the `execute` method, line ~81)
- Modify: `tclCommands/TclCommandPlotObjects.py` (the `execute` method, line ~78)
- Test: `tests/test_tcl_no_plot.py`

- [ ] **Step 1: Write the failing test**

```python
"""A Tcl command makes no plot: every new_object() call in tclCommands passes plot=False. Only plot_all and
plot_objects draw, and in headless mode they draw nothing."""

import ast
import os
from types import SimpleNamespace
from unittest.mock import Mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TCL_DIR = os.path.join(REPO, 'tclCommands')


def _new_object_calls_without_plot_false():
    offenders = []
    for name in sorted(os.listdir(TCL_DIR)):
        if not name.endswith('.py'):
            continue
        path = os.path.join(TCL_DIR, name)
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'new_object':
                plot = [kw for kw in node.keywords if kw.arg == 'plot']
                if not (plot and isinstance(plot[0].value, ast.Constant) and plot[0].value.value is False):
                    offenders.append('%s:%d' % (name, node.lineno))
    return offenders


def test_every_new_object_call_of_a_tcl_command_passes_plot_false():
    assert _new_object_calls_without_plot_false() == []


def test_plot_all_draws_nothing_in_headless_mode():
    from tclCommands.TclCommandPlotAll import TclCommandPlotAll
    app = SimpleNamespace(headless=True, plot_all=Mock(), inform=Mock())
    command = TclCommandPlotAll.__new__(TclCommandPlotAll)
    command.app = app
    command.execute({}, [])
    app.plot_all.assert_not_called()
    app.inform.emit.assert_called_once()


def test_plot_objects_draws_nothing_in_headless_mode():
    from tclCommands.TclCommandPlotObjects import TclCommandPlotObjects
    obj = Mock()
    app = SimpleNamespace(headless=True, inform=Mock(), collection=Mock(get_by_name=Mock(return_value=obj)))
    command = TclCommandPlotObjects.__new__(TclCommandPlotObjects)
    command.app = app
    command.execute({}, ['a'])
    obj.plot.assert_not_called()
    app.inform.emit.assert_called_once()
```

Read `execute()` of both plot commands before you run the tests: if `execute` takes other argument names, or reads options such as `args['plot_status']` before it plots, change the `execute({}, ...)` calls of the test to pass what the command needs. The assertions stay.

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tcl_no_plot.py -q`
Expected: FAIL; the first test lists `TclCommandInteriors.py:70`, the 2 headless tests see a plot call.

- [ ] **Step 3: Write the implementation**

`tclCommands/TclCommandInteriors.py:70`:

```python
        result = self.app.app_obj.new_object('geometry', outname, geo_init, plot=False)
```

At the start of `execute()` of `TclCommandPlotAll` and of `TclCommandPlotObjects` (after the docstring):

```python
        if getattr(self.app, 'headless', False) is True:
            # headless mode: there is no canvas, and a Tcl command makes no plot anyway
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Headless mode: nothing is plotted."))
            return
```

If the file has no `_` (translation) defined, use the same translation setup as the other `tclCommands` files that use `_(...)` (search one and copy its import lines).

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tcl_no_plot.py tests/test_tcl_audit_regressions.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
rtk git add tclCommands/TclCommandInteriors.py tclCommands/TclCommandPlotAll.py tclCommands/TclCommandPlotObjects.py tests/test_tcl_no_plot.py
rtk git commit -m "fix(tcl): interiors makes no plot; plot_all / plot_objects draw nothing in headless mode"
```

Add a line to the `Headless mode:` block of `CHANGELOG.md` (Task 9 makes the block) in the same commit if Task 9 is done, else in Task 9:

```markdown
- fixed: the Tcl command interiors plotted its result; a Tcl command makes no plot (only plot_all and plot_objects draw), a test checks every command
```

---

## Not in this plan

- Moving the plugins off their widgets (the forms stay real widgets on the offscreen platform).
- `open_folder` uses `QFileDialog`; in headless mode a dialog has no user. It is not changed here.
- A test on a real Linux machine with no display: this machine runs Windows; the `offscreen` platform on Windows is the nearest test.
