"""Numeric material drawing using the Geometry editor's controls and font outlines."""

import builtins
import gettext
import math

from PyQt6 import QtWidgets
from shapely.affinity import rotate, translate
from shapely.geometry import box

from appEditors.geo_plugins.GeoRectanglePlugin import RectangleEditorUI
from appEditors.geo_plugins.GeoTextPlugin import TextEditorUI
from appGUI.GUIElements import FCDoubleSpinner
from appParsers.ParseFont import ParseFont
import appTranslation as fcTranslate

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


def rectangle_region(x, y, length, width, anchor, corner, radius, angle, steps):
    values = (x, y, length, width, radius, angle)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values) or \
            length <= 0 or width <= 0 or radius < 0 or anchor not in ('c', 'tl', 'tr', 'bl', 'br') or \
            corner not in ('s', 'r', 'b') or (corner != 's' and radius * 2 >= min(length, width)):
        raise ValueError(_("Enter finite coordinates, positive dimensions and a corner radius smaller than half the size."))
    cx = x + (length / 2 if anchor in ('tl', 'bl') else -length / 2 if anchor in ('tr', 'br') else 0)
    cy = y + (width / 2 if anchor in ('bl', 'br') else -width / 2 if anchor in ('tl', 'tr') else 0)
    inset = radius if corner in ('r', 'b') else 0
    polygon = box(cx - length / 2 + inset, cy - width / 2 + inset,
                  cx + length / 2 - inset, cy + width / 2 - inset)
    if inset:
        polygon = polygon.buffer(inset, quad_segs=steps, join_style='round' if corner == 'r' else 'bevel')
    return rotate(polygon, angle, origin=(x, y))


def text_region(parser, text, family, style, size, units, x, y, angle):
    try:
        size = float(size)
        valid = all(math.isfinite(value) for value in (size, x, y, angle)) and size > 0
    except (TypeError, ValueError, OverflowError):
        valid = False
    if not valid or not text.strip() or units.upper() not in ('MM', 'IN'):
        raise ValueError(_("Enter text, a positive font size and finite coordinates and rotation."))
    polygon = parser.font_to_geometry(char_string=text, font_name=family, font_type=style,
                                      font_size=size, units=units.upper())
    if isinstance(polygon, str) or polygon is None or polygon.is_empty:
        raise ValueError(_("No geometry generated from text input."))
    return translate(rotate(polygon, angle, origin=(0, 0)), xoff=x, yoff=y)


class RegionDrawingDialog(QtWidgets.QDialog):
    def __init__(self, editor, kind):
        super().__init__(editor.ui.grb_edit_widget)
        self.editor = editor
        self.app = editor.app
        self.kind = kind
        self.session = editor.history.session
        self.units = self.app.app_units
        self.parser = None
        self.setWindowTitle(_("Rectangle Region") if kind == 'rectangle' else _("Text Regions"))
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(_("Explicit material regions. Dimensions use %s; font size uses points.") %
                                          self.app.app_units))
        if kind == 'rectangle':
            self.ui = RectangleEditorUI(layout, self)
            self.ui.anchor_radio.set_value('c')
            self.ui.corner_radio.set_value('s')
            self.ui.radius_entry.set_value(0)
            self.ui.length_entry.set_value(0)
            self.ui.width_entry.set_value(0)
            self.ui.note_description_lbl.setText(_("Creates new material; existing features aren't replaced."))
            button = self.ui.add_button
        else:
            self.ui = TextEditorUI(layout, self)
            position = QtWidgets.QFormLayout()
            layout.addLayout(position)
            self.ui.x_entry = self.coordinate_entry()
            self.ui.y_entry = self.coordinate_entry()
            position.addRow(_("Baseline X"), self.ui.x_entry)
            position.addRow(_("Baseline Y"), self.ui.y_entry)
            button = self.ui.apply_button
        for entry, value in ((self.ui.x_entry, editor.snap_x), (self.ui.y_entry, editor.snap_y)):
            entry.set_value(value if isinstance(value, (int, float)) and math.isfinite(value) else 0)
        self.angle_entry = self.coordinate_entry()
        angle_row = QtWidgets.QFormLayout()
        angle_row.addRow(_("Rotation (degrees, about anchor)"), self.angle_entry)
        layout.addLayout(angle_row)
        cancel = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        cancel.rejected.connect(self.reject)
        layout.addWidget(cancel)
        button.clicked.connect(self.on_apply)

    def coordinate_entry(self):
        entry = FCDoubleSpinner()
        entry.set_precision(self.app.decimals)
        entry.set_range(-10000, 10000)
        return entry

    def on_apply(self):
        if self.session != self.editor.history.session or self.units != self.app.app_units:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Editor session or units changed. Reopen the drawing tool."))
            return
        if not self.editor.history.ready():
            return
        try:
            x, y = self.ui.x_entry.get_value(), self.ui.y_entry.get_value()
            angle = self.angle_entry.get_value()
            if self.kind == 'rectangle':
                polygon = rectangle_region(x, y, self.ui.length_entry.get_value(), self.ui.width_entry.get_value(),
                                           self.ui.anchor_radio.get_value(), self.ui.corner_radio.get_value(),
                                           self.ui.radius_entry.get_value(), angle,
                                           int(self.app.options.get('gerber_circle_steps', 64)))
            else:
                if self.parser is None:
                    self.parser = ParseFont(self.app)
                    self.parser.get_fonts_by_types()
                bold, italic = self.ui.font_bold_tb.isChecked(), self.ui.font_italic_tb.isChecked()
                style = 'bi' if bold and italic else 'bold' if bold else 'italic' if italic else 'regular'
                polygon = text_region(self.parser, self.ui.text_input_entry.get_value(),
                                      self.ui.font_type_cb.currentFont().family(), style,
                                      self.ui.font_size_cb.get_value(), self.app.app_units, x, y, angle)
            if self.editor.add_region_geometry(polygon) != 'fail':
                self.accept()
        except (ValueError, TypeError, OverflowError) as error:
            self.app.inform.emit('[WARNING_NOTCL] %s' % str(error))
        except Exception as error:
            self.app.log.error('RegionDrawingDialog.on_apply() --> %s' % str(error))
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Action was not executed"), str(error)))
