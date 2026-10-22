"""
Issue #41: the Milling plugin took the general job settings of a multi-geometry job (preprocessor, End Z, toolchange,
exclusion areas) from whatever its form showed last. A job could be made with the settings of the previous target.
The form must show, for the selected target, the settings that the job will use: the general fields from the saved
values of the target and the per-tool fields from the saved data of the tool.
"""
import os
from copy import deepcopy
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PyQt6 import QtCore, QtWidgets
from shapely import LineString

from appPlugins.ToolMilling import ToolMilling
from test_milling_old_tool_data import (FormField, MILL_OPTIONS, PLUGIN_FORM, flatcam_8_994_cutout_tool,
                                        milling_harness)

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

PER_TOOL = ('tools_mill_cutz', 'tools_mill_multidepth', 'tools_mill_depthperpass', 'tools_mill_travelz',
            'tools_mill_feedrate', 'tools_mill_feedrate_z', 'tools_mill_spindlespeed')

LASER = dict(tools_mill_ppname_g='GRBL_laser', tools_mill_endz=20.0, tools_mill_toolchangez=30.0,
             tools_mill_cutz=0.0, tools_mill_feedrate=1000.0)
MILL = dict(tools_mill_ppname_g='default', tools_mill_endz=15.0, tools_mill_toolchangez=12.0,
            tools_mill_cutz=-1.8, tools_mill_feedrate=120.0)


class QtMilling(QtCore.QObject):
    """The real ToolMilling methods on a QObject: the form's signals reach form_to_storage() with their sender()."""
    def __getattr__(self, name):
        method = getattr(ToolMilling, name)
        return method.__get__(self, type(self))


@pytest.fixture(autouse=True)
def slot_errors(monkeypatch):
    """PyQt6 aborts the process on an exception in a slot: report it as a test failure instead."""
    import sys
    errors = []
    monkeypatch.setattr(sys, 'excepthook', lambda kind, value, tb: errors.append(value))
    yield
    assert not errors, errors


def saved_tool(**changes):
    geometry = [LineString([(0, 0), (10, 0)]), LineString([(0, 5), (10, 5)])]
    data = dict(deepcopy(MILL_OPTIONS), tools_mill_tooldia=1.0, tools_mill_offset_type=0, tools_mill_job_type=0,
                tools_mill_multidepth=False, tools_mill_optimization_type='R', tools_mill_toolchange=False,
                tools_mill_area_exclusion=False)
    data.update(changes)
    return {'tooldia': 1.0, 'solid_geometry': geometry, 'data': data}


def make_object(name, multigeo=True, tool=None, **changes):
    tool = tool or saved_tool(**changes)
    tool.setdefault('solid_geometry', [LineString([(0, 0), (10, 0)])])
    return SimpleNamespace(kind='geometry', multigeo=multigeo, tools={1: tool}, solid_geometry=tool.get('solid_geometry', []),
                           obj_options=dict(tool['data'], name=name, xmin=0, ymin=0, xmax=10, ymax=5))


def plugin(objects, multigeo=True, **options):
    """
    The Milling plugin with its real form and signals, and several Geometry targets. Selecting a target in the Target
    combo box runs on_object_changed(), as the project tree selection does.
    """
    from unittest.mock import MagicMock
    from PyQt6 import QtGui
    from appPlugins.ToolMilling import MillingUI

    harness, jobs = milling_harness(saved_tool(), multigeo, **options)
    milling = QtMilling()
    vars(milling).update(vars(harness))
    app = milling.app
    app.app_units = 'MM'
    app.resource_location = os.path.abspath('assets/resources')
    app.proj_selection_changed = MagicMock()
    app.exc_areas = MagicMock(exclusion_areas_storage=[], travel_coordinates=lambda **kw: [(None, kw['end_point'])])
    app.ui = SimpleNamespace(notebook=SimpleNamespace(tabText=lambda _index: 'Milling'))
    app.collection = QtGui.QStandardItemModel()
    app.collection.get_by_name = lambda name: objects[name]
    app.collection.set_all_inactive = lambda: None
    app.collection.set_active = lambda _name: None
    milling.ui = MillingUI(layout=QtWidgets.QVBoxLayout(), app=app, name='Milling')
    ui = milling.ui
    ui.object_combo = QtWidgets.QComboBox()      # the app's combo shows the project tree; this one the test targets
    ui.object_combo.addItems(list(objects))
    ui.target_radio.set_value('geo')
    ui.pp_geo_name_cb.clear()
    ui.pp_geo_name_cb.addItems(list(app.preprocessors))
    ui.pp_geo_name_cb.set_value(app.options['tools_mill_ppname_g'])
    milling.form_fields = {
        "tools_mill_offset_type": ui.offset_type_combo, "tools_mill_offset_value": ui.offset_entry,
        "tools_mill_tool_shape": ui.tool_shape_combo, "tools_mill_job_type": ui.job_type_combo,
        "tools_mill_cutz": ui.cutz_entry, "tools_mill_multidepth": ui.mpass_cb,
        "tools_mill_depthperpass": ui.maxdepth_entry, "tools_mill_travelz": ui.travelz_entry,
        "tools_mill_feedrate": ui.xyfeedrate_entry, "tools_mill_feedrate_z": ui.feedrate_z_entry,
        "tools_mill_feedrate_rapid": ui.feedrate_rapid_entry, "tools_mill_spindlespeed": ui.spindlespeed_entry,
    }
    milling.general_form_fields = {
        "tools_mill_toolchange": ui.toolchange_cb, "tools_mill_toolchangez": ui.toolchangez_entry,
        "tools_mill_toolchangexy": ui.toolchangexy_entry, "tools_mill_endz": ui.endz_entry,
        "tools_mill_endxy": ui.endxy_entry, "tools_mill_z_p_depth": ui.pdepth_entry,
        "tools_mill_feedrate_probe": ui.feedrate_probe_entry, "tools_mill_ppname_g": ui.pp_geo_name_cb,
        "tools_mill_area_exclusion": ui.exclusion_cb, "tools_mill_area_shape": ui.area_shape_radio,
        "tools_mill_area_strategy": ui.strategy_radio, "tools_mill_area_overz": ui.over_z_entry,
    }
    milling.name2option = {widget.objectName(): key for key, widget in
                           {**milling.form_fields, **milling.general_form_fields}.items() if widget.objectName()}
    milling.plot_cb_handler = lambda: None
    milling.jobs = jobs
    milling.ui_connect()
    return milling


def select(milling, name):
    milling.ui.object_combo.setCurrentText(name)
    milling.on_object_changed()


def generate(milling):
    """Generate CNCJob for the selected target: all its tools, as on_generate_cnc_from_geo() selects them."""
    milling.sel_tools.clear()
    milling.sel_tools.update(deepcopy(milling.target_obj.tools))
    milling.generate_cnc_job_handler(toolchange=False, plot=False, use_thread=False)
    return milling.jobs[-1]


def form_values(milling, keys):
    fields = {**milling.form_fields, **milling.general_form_fields}
    return {key: fields[key].get_value() for key in keys}


def test_multigeo_job_uses_the_settings_of_the_selected_target():
    objects = {'A': make_object('A', **LASER), 'B': make_object('B', **MILL)}
    milling = plugin(objects)
    select(milling, 'A')
    assert 'laser' in generate(milling).pp_geometry_name
    select(milling, 'B')
    job = generate(milling)
    assert job.pp_geometry_name == 'default'
    assert 'G01 Z-1.8000' in job.source_file


def test_single_geo_job_and_form_follow_the_selected_target():
    objects = {'A': make_object('A', multigeo=False, **LASER), 'B': make_object('B', multigeo=False, **MILL)}
    milling = plugin(objects, multigeo=False)
    select(milling, 'A')
    select(milling, 'B')
    assert form_values(milling, MILL) == MILL
    job = generate(milling)
    assert job.pp_geometry_name == 'default'
    assert 'G01 Z-1.8000' in job.source_file


def test_form_edit_goes_to_the_target_only():
    objects = {'A': make_object('A', **LASER), 'B': make_object('B', **MILL)}
    milling = plugin(objects)
    select(milling, 'B')
    milling.general_form_fields['tools_mill_endz'].set_value(33.0)
    field = milling.general_form_fields['tools_mill_endz']
    field.objectName = lambda: 'endz'
    milling.sender = lambda: field
    milling.name2option = {'endz': 'tools_mill_endz'}
    milling.form_to_storage()
    assert objects['B'].tools[1]['data']['tools_mill_endz'] == 33.0
    assert objects['A'].tools[1]['data']['tools_mill_endz'] == 20.0
    select(milling, 'A')
    assert form_values(milling, ['tools_mill_endz']) == {'tools_mill_endz': 20.0}
    assert generate(milling).pp_geometry_name == 'GRBL_laser'


def test_old_project_target_resets_the_general_fields():
    # the object saved by FlatCAM 8.994 keeps the settings under old names (ppname_g, endz): the form shows them
    old = make_object('cutout', tool=flatcam_8_994_cutout_tool())
    old.obj_options = dict(MILL_OPTIONS, name='cutout', xmin=0, ymin=0, xmax=10, ymax=5)
    objects = {'iso': make_object('iso', **LASER), 'cutout': old}
    milling = plugin(objects, tools_mill_ppname_g='GRBL_laser')
    select(milling, 'iso')
    select(milling, 'cutout')
    assert milling.ui.pp_geo_name_cb.get_value() == 'default'
    assert milling.ui.endz_entry.get_value() == 15.0
    assert generate(milling).pp_geometry_name == 'default'

