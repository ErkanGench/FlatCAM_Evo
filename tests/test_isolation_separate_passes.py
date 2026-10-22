"""Isolation plugin: isolate() with the passes not combined and no specific geometry.

With 'Combine' off and the selection 'All' or 'Area Selection', ToolIsolation.isolate() gets geometry=None. It called
flatten_shapely_geometry(None), which raises NotImplementedError, so no Geometry object was made. The tests build the
real ToolIsolation headless and isolate a parsed Gerber object (fixtures of tests.helpers_objects).
"""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from shapely.geometry import box
from shapely.ops import unary_union

from defaults import AppDefaults
from appObjects.GeometryObject import GeometryObject
from appPlugins.ToolIsolation import ToolIsolation

from test_plugin_geometry_bases import make_tool_app
from tests.helpers_objects import app, _headless_qt, make_gerber  # noqa: F401,E402

DIA = 0.2


def tools_storage(passes):
    data = {k: deepcopy(v) for k, v in AppDefaults().defaults.items() if k.startswith('tools_')}
    data.update(tools_iso_passes=passes, tools_iso_overlap=10, tools_iso_isotype='full',
                tools_iso_milling_type='cl')
    return {1: {'tooldia': DIA, 'data': data, 'solid_geometry': []}}


@pytest.fixture(scope='module')
def tool(_headless_qt):  # noqa: F811
    return ToolIsolation(make_tool_app())


def run_isolate(tool, app, gerber, passes, **kwargs):
    """Calls the plugin isolate() with combine off; returns {object name: Geometry object built by the init callback}."""
    created = {}

    def new_object(kind, name, initialize, plot=True, **kw):
        assert kind == 'geometry'
        obj = GeometryObject(name, app)
        assert initialize(obj, app) != 'fail'
        created[name] = obj
        return 'ok'

    tool.app.app_obj.new_object = Mock(side_effect=new_object)
    tool.isolate(isolated_obj=gerber, sel_tools=[1], tools_storage=tools_storage(passes), plot=False,
                 combine=False, iso_except=False, e_passes=0, area_except=False, area_shape='square', rest=False,
                 sel_type=0, tip_shape='C1', iso_simplification=False, simplification_tol=0.001, **kwargs)
    return created


def wkb_set(geometries):
    return sorted(g.wkb_hex for g in geometries if not g.is_empty)


@pytest.mark.parametrize('passes', [1, 3])
def test_whole_object_makes_one_geometry_per_pass(tool, app, passes):
    created = run_isolate(tool, app, make_gerber(app, name='g'), passes)

    names = ['g_0.2000_iso'] if passes == 1 else ['g_0.2000_iso%d' % (i + 1) for i in range(passes)]
    assert sorted(created) == names
    for obj in created.values():
        assert len(obj.solid_geometry) > 0
        assert obj.tools[1]['tooldia'] == DIA
        assert obj.tools[1]['solid_geometry'] == obj.solid_geometry


def test_area_selection_with_separate_passes(tool, app):
    gerber = make_gerber(app, name='g')
    xmin, ymin, xmax, ymax = unary_union(gerber.solid_geometry).bounds
    area = box(xmin - 1, ymin - 1, (xmin + xmax) / 2, ymax + 1)

    created = run_isolate(tool, app, gerber, 2, limited_area=area)

    assert sorted(created) == ['g_0.2000_iso1', 'g_0.2000_iso2']
    for obj in created.values():
        assert len(obj.solid_geometry) > 0
        assert unary_union(obj.solid_geometry).within(area.buffer(1e-6))
