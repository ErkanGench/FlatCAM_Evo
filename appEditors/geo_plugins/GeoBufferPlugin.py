
from PyQt6 import QtWidgets
from appTool import AppToolEditor
from appGUI.GUIElements import VerticalScrollArea, FCLabel, FCButton, FCFrame, GLay, FCDoubleSpinner, FCComboBox

from shapely import Polygon
from camlib import object_quad_segs, flatten_shapely_geometry
from math import isfinite

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class BufferSelectionTool(AppToolEditor):
    """
    Simple input for buffer distance.
    """

    def __init__(self, app, draw_app):
        AppToolEditor.__init__(self, app)

        self.draw_app = draw_app
        self.decimals = app.decimals

        self.ui = BufferEditorUI(layout=self.layout, buffer_class=self)

        self.connect_signals_at_init()
        self.set_tool_ui()

    def connect_signals_at_init(self):
        # Signals
        self.ui.buffer_button.clicked.connect(self.on_buffer)
        self.ui.buffer_int_button.clicked.connect(self.on_buffer_int)
        self.ui.buffer_ext_button.clicked.connect(self.on_buffer_ext)

    def run(self):
        self.app.defaults.report_usage("Geo Editor ToolBuffer()")
        super().run()

        # if the splitter us hidden, display it
        if self.app.ui.splitter.sizes()[0] == 0:
            self.app.ui.splitter.setSizes([1, 1])

        # if the Tool Tab is hidden display it, else hide it but only if the objectName is the same
        found_idx = None
        for idx in range(self.app.ui.notebook.count()):
            if self.app.ui.notebook.widget(idx).objectName() == "plugin_tab":
                found_idx = idx
                break
        # show the Tab
        if not found_idx:
            try:
                self.app.ui.notebook.addTab(self.app.ui.plugin_tab, _("Plugin"))
            except RuntimeError:
                self.app.ui.plugin_tab = QtWidgets.QWidget()
                self.app.ui.plugin_tab.setObjectName("plugin_tab")
                self.app.ui.plugin_tab_layout = QtWidgets.QVBoxLayout(self.app.ui.plugin_tab)
                self.app.ui.plugin_tab_layout.setContentsMargins(2, 2, 2, 2)

                self.app.ui.plugin_scroll_area = VerticalScrollArea()
                self.app.ui.plugin_tab_layout.addWidget(self.app.ui.plugin_scroll_area)
                self.app.ui.notebook.addTab(self.app.ui.plugin_tab, _("Plugin"))

            # focus on Tool Tab
            self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)

        # self.app.ui.notebook.callback_on_close = self.on_tab_close

        self.app.ui.notebook.setTabText(2, _("Buffer"))

    def set_tool_ui(self):
        # Init appGUI
        self.ui.buffer_distance_entry.set_value(0.01)

    def on_tab_close(self):
        self.draw_app.select_tool("select")
        self.app.ui.notebook.callback_on_close = lambda: None

    def on_buffer(self):
        try:
            buffer_distance = float(self.ui.buffer_distance_entry.get_value())
        except ValueError:
            # try to convert comma to decimal point. if it's still not working error message and return
            try:
                buffer_distance = float(self.ui.buffer_distance_entry.get_value().replace(',', '.'))
                self.ui.buffer_distance_entry.set_value(buffer_distance)
            except ValueError:
                self.app.inform.emit('[WARNING_NOTCL] %s' %
                                     _("Buffer distance value is missing or wrong format. Add it and retry."))
                return
        # the cb index start from 0 but the join styles for the buffer start from 1 therefore the adjustment
        # I populated the combobox such that the index coincide with the join styles value (which is really an INT)
        join_style = {1: 'round', 2: 'mitre', 3: 'bevel'}.get(self.ui.buffer_corner_cb.currentIndex() + 1)
        self.buffer(buffer_distance, join_style)

    def on_buffer_int(self):
        try:
            buffer_distance = float(self.ui.buffer_distance_entry.get_value())
        except ValueError:
            # try to convert comma to decimal point. if it's still not working error message and return
            try:
                buffer_distance = float(self.ui.buffer_distance_entry.get_value().replace(',', '.'))
                self.ui.buffer_distance_entry.set_value(buffer_distance)
            except ValueError:
                self.app.inform.emit('[WARNING_NOTCL] %s' %
                                     _("Buffer distance value is missing or wrong format. Add it and retry."))
                return
        # the cb index start from 0 but the join styles for the buffer start from 1 therefore the adjustment
        # I populated the combobox such that the index coincide with the join styles value (which is really an INT)
        join_style = {1: 'round', 2: 'mitre', 3: 'bevel'}.get(self.ui.buffer_corner_cb.currentIndex() + 1)
        self.buffer_int(buffer_distance, join_style)

    def on_buffer_ext(self):
        try:
            buffer_distance = float(self.ui.buffer_distance_entry.get_value())
        except ValueError:
            # try to convert comma to decimal point. if it's still not working error message and return
            try:
                buffer_distance = float(self.ui.buffer_distance_entry.get_value().replace(',', '.'))
                self.ui.buffer_distance_entry.set_value(buffer_distance)
            except ValueError:
                self.app.inform.emit('[WARNING_NOTCL] %s' %
                                     _("Buffer distance value is missing or wrong format. Add it and retry."))
                return
        # the cb index start from 0 but the join styles for the buffer start from 1 therefore the adjustment
        # I populated the combobox such that the index coincide with the join styles value (which is really an INT)
        join_style = {1: 'round', 2: 'mitre', 3: 'bevel'}.get(self.ui.buffer_corner_cb.currentIndex() + 1)
        self.buffer_ext(buffer_distance, join_style)

    @staticmethod
    def buffer_contours(geometry, distance, quad_segs, join_style):
        contours = []
        for geo in flatten_shapely_geometry(geometry):
            if geo.is_valid and geo.geom_type in ('Polygon', 'LineString', 'LinearRing'):
                if geo.geom_type != 'Polygon' and geo.is_ring:
                    geo = Polygon(geo)
                for part in flatten_shapely_geometry(geo.buffer(
                        distance, quad_segs=quad_segs, join_style=join_style)):
                    if part.geom_type == 'Polygon':
                        contours.extend([part.exterior, *part.interiors])
        return contours

    def buffer(self, buf_distance, join_style):
        def work_task(geo_editor):
            with geo_editor.app.proc_container.new(_("Working...")):
                selected = geo_editor.get_selected()

                if not isinstance(buf_distance, (int, float)) or not isfinite(buf_distance):
                    geo_editor.app.inform.emit('[WARNING_NOTCL] %s' % _("Invalid distance."))
                    return 'fail'
                if buf_distance < 0:
                    msg = '[ERROR_NOTCL] %s' % _("Negative buffer value is not accepted. "
                                                 "Use Buffer interior to generate an 'inside' shape")
                    geo_editor.app.inform.emit(msg)

                    # deselect everything
                    geo_editor.selected = []
                    geo_editor.plot_all()
                    return 'fail'

                if len(selected) == 0:
                    geo_editor.app.inform.emit('[WARNING_NOTCL] %s' % _("Nothing selected."))
                    return 'fail'

                # the round joins have the radius of the buffer distance
                quad_segs = object_quad_segs(geo_editor.app.options, 'geometry', buf_distance, geo_editor.app.app_units)
                results = []
                for t in selected:
                    for geo in flatten_shapely_geometry(t.geo):
                        if not geo.is_valid:
                            continue
                        if geo.geom_type == 'Polygon':
                            results.extend(flatten_shapely_geometry(geo.boundary.buffer(
                                buf_distance, quad_segs=quad_segs, join_style=join_style)))
                        else:
                            results.extend(BufferSelectionTool.buffer_contours(
                                geo, buf_distance, quad_segs, join_style))
                            results.extend(BufferSelectionTool.buffer_contours(
                                geo, -buf_distance, quad_segs, join_style))

                if not results:
                    geo_editor.app.inform.emit('[ERROR_NOTCL] %s' % _("Failed, the result is empty."))
                    # deselect everything
                    geo_editor.selected = []
                    geo_editor.plot_all()
                    return 'fail'

                if geo_editor.add_shape(results) == 'fail':
                    return 'fail'
                geo_editor.plot_changes()
                geo_editor.app.inform.emit('[success] %s' % _("Done."))

        self.draw_app.submit_worker(work_task, [self.draw_app])

    def buffer_int(self, buf_distance, join_style):
        def work_task(geo_editor):
            with geo_editor.app.proc_container.new(_("Working...")):
                selected = geo_editor.get_selected()

                if not isinstance(buf_distance, (int, float)) or not isfinite(buf_distance):
                    geo_editor.app.inform.emit('[WARNING_NOTCL] %s' % _("Invalid distance."))
                    return 'fail'
                if buf_distance < 0:
                    geo_editor.app.inform.emit('[ERROR_NOTCL] %s' % _("Negative buffer value is not accepted."))
                    # deselect everything
                    geo_editor.selected = []
                    geo_editor.plot_all()
                    return 'fail'

                if len(selected) == 0:
                    geo_editor.app.inform.emit('[WARNING_NOTCL] %s' % _("Nothing selected."))
                    return 'fail'

                # the round joins have the radius of the buffer distance
                quad_segs = object_quad_segs(geo_editor.app.options, 'geometry', buf_distance, geo_editor.app.app_units)
                results = []
                for t in selected:
                    results.extend(BufferSelectionTool.buffer_contours(
                        t.geo, -buf_distance, quad_segs, join_style))

                if not results:
                    geo_editor.app.inform.emit('[ERROR_NOTCL] %s' % _("Failed, the result is empty."))
                    # deselect everything
                    geo_editor.selected = []
                    geo_editor.plot_all()
                    return 'fail'

                if geo_editor.add_shape(results) == 'fail':
                    return 'fail'
                geo_editor.plot_changes()
                geo_editor.app.inform.emit('[success] %s' % _("Done."))

        self.draw_app.submit_worker(work_task, [self.draw_app])

    def buffer_ext(self, buf_distance, join_style):
        def work_task(geo_editor):
            with geo_editor.app.proc_container.new(_("Working...")):
                selected = geo_editor.get_selected()

                if not isinstance(buf_distance, (int, float)) or not isfinite(buf_distance):
                    geo_editor.app.inform.emit('[WARNING_NOTCL] %s' % _("Invalid distance."))
                    return 'fail'
                if buf_distance < 0:
                    msg = '[ERROR_NOTCL] %s' % _("Negative buffer value is not accepted. "
                                                 "Use Buffer interior to generate an 'inside' shape")
                    geo_editor.app.inform.emit(msg)
                    # deselect everything
                    geo_editor.selected = []
                    geo_editor.plot_all()
                    return 'fail'

                if len(selected) == 0:
                    geo_editor.app.inform.emit('[WARNING_NOTCL] %s' % _("Nothing selected."))
                    return 'fail'

                # the round joins have the radius of the buffer distance
                quad_segs = object_quad_segs(geo_editor.app.options, 'geometry', buf_distance, geo_editor.app.app_units)
                results = []
                for t in selected:
                    results.extend(BufferSelectionTool.buffer_contours(
                        t.geo, buf_distance, quad_segs, join_style))

                if not results:
                    geo_editor.app.inform.emit('[ERROR_NOTCL] %s' % _("Failed, the result is empty."))
                    # deselect everything
                    geo_editor.selected = []
                    geo_editor.plot_all()
                    return 'fail'

                if geo_editor.add_shape(results) == 'fail':
                    return 'fail'
                geo_editor.plot_changes()
                geo_editor.app.inform.emit('[success] %s' % _("Done."))

        self.draw_app.submit_worker(work_task, [self.draw_app])

    def hide_tool(self):
        self.ui.buffer_tool_frame.hide()
        self.app.ui.notebook.setCurrentWidget(self.app.ui.properties_tab)


class BufferEditorUI:
    pluginName = _("Buffer")

    def __init__(self, layout, buffer_class):
        self.buffer_class = buffer_class
        self.decimals = self.buffer_class.app.decimals
        self.layout = layout

        # Title
        title_label = FCLabel("%s" % ('Editor ' + self.pluginName), size=16, bold=True)
        self.layout.addWidget(title_label)

        self.param_label = FCLabel('%s' % _("Parameters"), color='blue', bold=True)
        self.layout.addWidget(self.param_label)

        # this way I can hide/show the frame
        self.buffer_tool_frame = QtWidgets.QFrame()
        self.buffer_tool_frame.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.buffer_tool_frame)

        self.buffer_tools_box = QtWidgets.QVBoxLayout()
        self.buffer_tools_box.setContentsMargins(0, 0, 0, 0)
        self.buffer_tool_frame.setLayout(self.buffer_tools_box)

        # #############################################################################################################
        # Tool Params Frame
        # #############################################################################################################
        tool_par_frame = FCFrame()
        self.buffer_tools_box.addWidget(tool_par_frame)

        # Grid Layout
        param_grid = GLay(v_spacing=5, h_spacing=3)
        tool_par_frame.setLayout(param_grid)

        # Buffer distance
        self.buffer_distance_entry = FCDoubleSpinner()
        self.buffer_distance_entry.set_precision(self.decimals)
        self.buffer_distance_entry.set_range(0.0000, 10000.0000)
        param_grid.addWidget(FCLabel('%s:' % _("Buffer distance")), 0, 0)
        param_grid.addWidget(self.buffer_distance_entry, 0, 1)

        self.buffer_corner_lbl = FCLabel('%s:' % _("Buffer corner"))
        self.buffer_corner_lbl.setToolTip(
            _("There are 3 types of corners:\n"
              " - 'Round': the corner is rounded for exterior buffer.\n"
              " - 'Square': the corner is met in a sharp angle for exterior buffer.\n"
              " - 'Beveled': the corner is a line that directly connects the features meeting in the corner")
        )
        self.buffer_corner_cb = FCComboBox()
        self.buffer_corner_cb.addItem(_("Round"))
        self.buffer_corner_cb.addItem(_("Square"))
        self.buffer_corner_cb.addItem(_("Beveled"))
        param_grid.addWidget(self.buffer_corner_lbl, 2, 0)
        param_grid.addWidget(self.buffer_corner_cb, 2, 1)

        # Buttons
        hlay = QtWidgets.QHBoxLayout()
        self.buffer_tools_box.addLayout(hlay)

        self.buffer_int_button = FCButton(_("Buffer Interior"))
        hlay.addWidget(self.buffer_int_button)
        self.buffer_ext_button = FCButton(_("Buffer Exterior"))
        hlay.addWidget(self.buffer_ext_button)

        hlay1 = QtWidgets.QHBoxLayout()
        self.buffer_tools_box.addLayout(hlay1)

        self.buffer_button = FCButton(_("Full Buffer"))
        hlay1.addWidget(self.buffer_button)

        self.layout.addStretch(1)
