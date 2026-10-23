"""
The canvas of the headless mode accepts every call of the application and draws nothing. A number taken from it
raises TypeError, so canvas data can never reach a calculation (G-code) unnoticed.
"""

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


