"""Numeric Gerber drawing creates explicit material, not guessed aperture sweeps."""

from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import pytest
from PyQt6 import QtGui, QtWidgets
from shapely.affinity import rotate, translate
from shapely.geometry import box, MultiPolygon
from shapely.ops import unary_union

from appEditors.grb_plugins.GrbDrawingPlugin import RegionDrawingDialog, rectangle_region, text_region
from appEditors.appGerberEditor import AppGerberEditor
from appParsers.ParseFont import ParseFont
from test_gerber_editor_clear import editor_save
from test_gerber_editor_pick import make_editor, aperture, pad
from test_unify_characterization import app, _headless_qt, make_gerber, NATIVE_GBR, reparse_gerber, assert_poly_equiv  # noqa: F401


@pytest.mark.parametrize('anchor,bounds', [('c', (-2, -1, 2, 1)), ('tl', (0, -2, 4, 0)),
                                          ('tr', (-4, -2, 0, 0)), ('bl', (0, 0, 4, 2)),
                                          ('br', (-4, 0, 0, 2))])
def test_rectangle_anchors(anchor, bounds):
    assert rectangle_region(0, 0, 4, 2, anchor, 's', 0, 0, 16).bounds == bounds


@pytest.mark.parametrize('corner', ['s', 'r', 'b'])
def test_rectangle_corners_and_rotation(corner):
    polygon = rectangle_region(3, 4, 4, 2, 'c', corner, 0.5, 90, 16)
    assert polygon.is_valid
    assert polygon.bounds == pytest.approx((2, 2, 4, 6))
    assert polygon.area <= 8


@pytest.mark.parametrize('values', [(0, 0, 0, 2, 'c', 's', 0, 0, 16),
                                   (0, 0, -1, 2, 'c', 's', 0, 0, 16),
                                   (0, 0, 4, 2, 'c', 'r', 2, 0, 16),
                                   (0, 0, 4, 2, 'c', 'b', -1, 0, 16),
                                   (float('nan'), 0, 4, 2, 'c', 's', 0, 0, 16),
                                   (0, 0, 4, 2, 'c', 's', 0, float('inf'), 16)])
def test_rectangle_rejects_invalid_input(values):
    with pytest.raises(ValueError):
        rectangle_region(*values)


def font_parser(editor):
    parser = ParseFont(editor.app)
    parser.get_fonts_by_types()
    assert parser.regular_f, 'A usable installed font is required for the real outline test.'
    return parser, 'Arial' if 'Arial' in parser.regular_f else next(iter(parser.regular_f))


def test_text_holes_units_and_transform():
    editor = make_editor()
    parser, family = font_parser(editor)
    mm = text_region(parser, 'Oi', family, 'regular', 12, 'MM', 0, 0, 0)
    inch = text_region(parser, 'Oi', family, 'regular', 12, 'IN', 0, 0, 0)
    assert mm.is_valid and not mm.is_empty
    parts = list(mm.geoms) if isinstance(mm, MultiPolygon) else [mm]
    assert sum(len(p.interiors) for p in parts) >= 1
    assert len(parts) >= 2
    assert mm.area / inch.area == pytest.approx(25.4 ** 2)
    moved = text_region(parser, 'Oi', family, 'regular', 12, 'MM', 10, 20, 90)
    assert moved.equals_exact(translate(rotate(mm, 90, origin=(0, 0)), 10, 20), 1e-10)
    for text, size, x in [('', 12, 0), ('O', 0, 0), ('O', float('nan'), 0), ('O', 12, float('inf'))]:
        with pytest.raises(ValueError):
            text_region(parser, text, family, 'regular', size, 'MM', x, 0, 0)


def test_region_commit_preserves_owners_and_undo():
    existing = pad(20, 20, 1)
    editor = make_editor({10: aperture([existing])})
    polygon = box(0, 0, 5, 5).difference(box(1, 1, 4, 4))
    added = editor.add_region_geometry(MultiPolygon([polygon, box(2, 2, 3, 3)]))
    assert len(added) == 2
    assert editor.storage_dict[10]['geometry'] == [existing]
    assert editor.storage_dict[editor.last_aperture_selected]['type'] == 'REG'
    assert editor.loaded_as_regions
    assert len(editor.history.undo_stack) == 1
    assert editor.undo()
    assert list(editor.storage_dict) == [10]
    assert editor.redo()
    assert unary_union([s.geo['solid'] for s in editor.selected]).equals(unary_union([polygon, box(2, 2, 3, 3)]))


def test_rectangle_dialog_commit_and_cancel():
    editor = make_editor()
    dialog = RegionDrawingDialog(editor, 'rectangle')
    dialog.ui.length_entry.set_value(4)
    dialog.ui.width_entry.set_value(2)
    dialog.ui.add_button.click()
    assert dialog.result() == QtWidgets.QDialog.DialogCode.Accepted
    assert editor.selected[0].geo['solid'].area == pytest.approx(8)
    assert editor.undo()
    cancelled = RegionDrawingDialog(editor, 'rectangle')
    cancelled.reject()
    assert not editor.storage_dict and not editor.history.undo_stack
    invalid = RegionDrawingDialog(editor, 'rectangle')
    invalid.ui.add_button.click()
    assert invalid.result() != QtWidgets.QDialog.DialogCode.Accepted
    assert not editor.storage_dict and not editor.history.undo_stack


def skip_without_fonts():
    # the offscreen Qt platform has an empty font database: the font combo box cannot select a family
    if QtWidgets.QFontComboBox().count() == 0:
        pytest.skip('no fonts in the Qt font database (offscreen platform)')


def test_text_dialog_commit():
    editor = make_editor()
    skip_without_fonts()
    dialog = RegionDrawingDialog(editor, 'text')
    parser, family = font_parser(editor)
    dialog.parser = parser
    dialog.ui.font_type_cb.setCurrentFont(QtGui.QFont(family))
    dialog.ui.text_input_entry.setPlainText('O')
    dialog.ui.apply_button.click()
    assert dialog.result() == QtWidgets.QDialog.DialogCode.Accepted
    assert sum(len(s.geo['solid'].interiors) for s in editor.selected) == 1
    assert editor.undo()


def test_drawing_buttons_open_the_correct_dialog():
    editor = make_editor()
    editor.app.grb_editor = editor
    editor.gerber_obj = SimpleNamespace(obj_options={'name': 'drawing'})
    editor.build_ui = AppGerberEditor.build_ui.__get__(editor)
    skip_without_fonts()
    parser, family = font_parser(editor)
    opened = []
    results = []

    # no assert in here: an exception that leaves a Qt slot aborts the interpreter (qFatal)
    def execute(dialog):
        opened.append(dialog.kind)
        if dialog.kind == 'rectangle':
            dialog.ui.length_entry.set_value(4)
            dialog.ui.width_entry.set_value(2)
            dialog.ui.add_button.click()
        else:
            dialog.parser = parser
            dialog.ui.font_type_cb.setCurrentFont(QtGui.QFont(family))
            dialog.ui.text_input_entry.setPlainText('O')
            dialog.ui.apply_button.click()
        results.append(dialog.result())

    with patch.object(RegionDrawingDialog, 'exec', execute):
        editor.ui.rectangle_region_btn.click()
        editor.ui.text_region_btn.click()
    assert opened == ['rectangle', 'text']
    assert results == [QtWidgets.QDialog.DialogCode.Accepted] * 2
    assert len(editor.history.undo_stack) == 2
    assert editor.ui.features_table.rowCount() == 2
    assert editor.current_storage is editor.storage_dict[editor.last_aperture_selected]['geometry']
    assert editor.undo() and editor.undo() and not editor.storage_dict


def test_dialog_rejects_stale_session_and_font_failure_without_mutation():
    editor = make_editor()
    dialog = RegionDrawingDialog(editor, 'rectangle')
    dialog.ui.length_entry.set_value(4)
    dialog.ui.width_entry.set_value(2)
    editor.history.reset()
    dialog.ui.add_button.click()
    assert not editor.storage_dict
    text = RegionDrawingDialog(editor, 'text')
    text.parser = MagicMock()
    text.parser.font_to_geometry.side_effect = RuntimeError('font engine unavailable')
    text.ui.text_input_entry.setPlainText('O')
    text.on_apply()
    assert not editor.storage_dict and not editor.history.undo_stack
    assert text.result() != QtWidgets.QDialog.DialogCode.Accepted


def test_pending_worker_rejects_region_addition():
    editor = make_editor()
    editor.history.pending = object()
    assert editor.add_region_geometry(box(0, 0, 2, 2)) == 'fail'
    assert not editor.storage_dict and not editor.history.undo_stack


def test_text_and_rectangle_native_export_reparse(app, tmp_path):
    editor = make_editor()
    parser, family = font_parser(editor)
    editor.add_region_geometry(text_region(parser, 'Oi', family, 'regular', 12, 'MM', 0, 0, 20))
    editor.add_region_geometry(rectangle_region(20, 20, 4, 2, 'c', 'r', 0.5, 30, 16))
    tools = {key: {**value, 'geometry': [shape.geo for shape in value['geometry']]}
             for key, value in editor.storage_dict.items()}
    expected = unary_union([shape.geo['solid'] for value in editor.storage_dict.values() for shape in value['geometry']])
    source = make_gerber(app, NATIVE_GBR)
    edited = editor_save(app, source, tools, loaded_as_regions=editor.loaded_as_regions)
    again = reparse_gerber(app, edited.source_file, tmp_path)
    assert_poly_equiv(again.solid_geometry, expected, abs_tol=1e-4)
