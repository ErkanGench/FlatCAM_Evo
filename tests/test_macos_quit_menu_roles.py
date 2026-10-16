"""macOS: the File > Exit action must be Qt's quit action, and 'Exit Editor' must not be.

On macOS Qt moves the action with QuitRole into the application menu as 'Quit' and gives it Cmd+Q.
- The Exit action had no role and no shortcut. Cmd+Q is Qt's Ctrl+Q, which MainGUI.keyPressEvent handles as a no-op,
  so Cmd+Q did nothing.
- 'Exit Editor' (disabled outside the editors) starts with 'Exit', so Qt's text heuristic gave it QuitRole as well and
  the application menu's Quit item showed its disabled state: it could not be clicked.

MainGUI cannot be built without the whole application, so this checks the wiring in the source; it was also verified
by hand on macOS (see the pull request).
"""

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / 'appGUI' / 'MainGUI.py'


def init_calls(attribute):
    """Method calls on self.<attribute> inside MainGUI.__init__ as {method name: [argument source strings]}."""
    source = SOURCE.read_text(encoding='utf-8')
    tree = ast.parse(source)
    main_gui = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == 'MainGUI')
    init = next(n for n in main_gui.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
    calls = {}
    for node in ast.walk(init):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == attribute
                and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == 'self'):
            calls.setdefault(node.func.attr, []).extend(ast.get_source_segment(source, a) for a in node.args)
    return calls


def test_exit_action_has_quit_role():
    roles = init_calls('menufile_exit').get('setMenuRole', [])
    assert any(r.endswith('MenuRole.QuitRole') for r in roles), roles


def test_exit_action_has_the_standard_quit_shortcut():
    shortcuts = init_calls('menufile_exit').get('setShortcut', [])
    assert any('StandardKey.Quit' in s for s in shortcuts), shortcuts


def test_exit_editor_action_is_not_a_quit_action():
    roles = init_calls('menueditok').get('setMenuRole', [])
    assert any(r.endswith('MenuRole.NoRole') for r in roles), roles
