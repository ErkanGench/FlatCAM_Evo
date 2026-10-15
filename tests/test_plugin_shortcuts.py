"""Headless checks of the plugin shortcut labels and the app level Alt key bindings."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# the editor Transformation plugins live in other key contexts (editor level), skip them
EDITOR_FILES = {
    'appEditors/appGerberEditor.py',
    'appEditors/geo_plugins/GeoTransformationPlugin.py',
    'appEditors/grb_plugins/GrbTransformationPlugin.py',
}


def _labels():
    found = {}
    for sub in ('appPlugins',):
        for path in (ROOT / sub).rglob('*.py'):
            text = path.read_text(encoding='utf-8')
            for m in re.finditer(r"AppTool\.install\([^)]*shortcut='([^']*)'", text):
                found[path.relative_to(ROOT).as_posix()] = m.group(1)
    return found


def _app_level_alt_bindings():
    """Alt letter -> plugin attribute run by the app level Alt branch of keyPressEvent."""
    text = (ROOT / 'appGUI' / 'MainGUI.py').read_text(encoding='utf-8')
    start = text.index('elif modifiers == QtCore.Qt.KeyboardModifier.AltModifier:')
    end = text.index('elif modifiers == QtCore.Qt.KeyboardModifier.NoModifier:', start)
    block = text[start:end]
    return dict(re.findall(
        r"if key == QtCore\.Qt\.Key\.Key_([A-Z])\:\s*self\.app\.(\w+)\.run", block))


def test_labels_are_unique():
    labels = {k: v for k, v in _labels().items() if v}
    seen = {}
    for path, label in labels.items():
        seen.setdefault(label.lower(), []).append(path)
    dup = {k: v for k, v in seen.items() if len(v) > 1}
    assert not dup, dup


def test_drilling_and_extract_labels():
    labels = _labels()
    assert labels['appPlugins/ToolDrilling.py'] == 'Alt+D'
    assert labels['appPlugins/ToolExtract.py'] == 'Alt+E'
    assert labels['appPlugins/ToolDblSided.py'] == 'Alt+U'


def test_app_level_bindings():
    keys = _app_level_alt_bindings()
    assert keys['D'] == 'drilling_tool'
    assert keys['U'] == 'dblsidedtool'
    assert keys['E'] == 'extract_tool'
    assert keys['I'] == 'isolation_tool'


def test_shortcut_list_tables_have_a_place_for_every_argument():
    # The F3 shortcut list builds each table with 'template' % (key, text, ...). A row added to the arguments
    # without a row in the template raises TypeError when the list is shown.
    tree = ast.parse((ROOT / 'appGUI' / 'MainGUI.py').read_text(encoding='utf-8'))
    checked = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Attribute)
                and '_sh_' in node.targets[0].attr):
            continue
        value = node.value
        if not (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Mod)
                and isinstance(value.left, ast.Constant) and isinstance(value.right, ast.Tuple)):
            continue
        places = len(re.findall(r'%s', value.left.value.replace('%%', '')))
        assert places == len(value.right.elts), (node.targets[0].attr, places, len(value.right.elts))
        assert '<strong%s>' not in value.left.value, node.targets[0].attr
        checked += 1
    assert checked >= 6
