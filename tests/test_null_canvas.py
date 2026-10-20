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


import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# only the canvas classes themselves make a shape collection on their scene
ALLOWED = {os.path.join('appGUI', 'PlotCanvas.py'), os.path.join('appGUI', 'PlotCanvas3d.py')}
SKIPPED_DIRS = {'tests', 'Utils', 'docs', '.venv', 'build', '.git', '.worktrees'}


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
