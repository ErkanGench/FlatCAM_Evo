"""
Issue #40: with a Cut Z of 0 and a non-laser preprocessor, generate_from_geometry_2() and geometry_tool_gcode_gen()
return the bare string 'fail'. The Milling initializers unpacked it into (gcode, start_gcode) and the clean failure
became 'too many values to unpack'. Now the initializer returns 'fail' and no CNC job is made.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from appObjects.CNCJobObject import CNCJobObject
from test_milling_single_geometry_tools import MillingHarness, PATHS, make_app, preprocessor, tool_data


def run_milling(multigeo, n_tools=2):
    app = make_app()
    app.preprocessors = {'default': preprocessor('default')}
    app.dec_format = lambda value, decimals: round(value, decimals)
    app.exc_areas = SimpleNamespace(exclusion_areas_storage=[],
                                    travel_coordinates=lambda **kw: [(None, kw['end_point'])])
    app.regFK, app.ui = Mock(), Mock()
    tools = {}
    for uid in range(1, n_tools + 1):
        data = tool_data(app, uid, 'default')
        data['tools_mill_cutz'] = 0.0
        tools[uid] = {'tooldia': 0.1 * uid, 'solid_geometry': list(PATHS), 'data': data}
    source = SimpleNamespace(multigeo=multigeo, tools=tools, solid_geometry=list(PATHS),
                             obj_options=dict(tools[1]['data'], name='board', xmin=0, ymin=0, xmax=30, ymax=10))
    results = []

    def new_object(kind, name, initializer, **kwargs):
        with patch('appObjects.AppObjectTemplate.ShapeCollection', Mock()):
            job = CNCJobObject(name, app)
        results.append(initializer(job, app))
        return None if results[-1] == 'fail' else job

    milling = MillingHarness(app=app, target_obj=source, sel_tools=tools, units='MM', decimals=4, circle_steps=64,
                             new_object=new_object,
                             ui=SimpleNamespace(toolchange_cb=SimpleNamespace(get_value=lambda: False)))
    milling.generate_cnc_job_handler(from_tcl=True, use_thread=False, plot=False)
    return app, results


@pytest.mark.parametrize('multigeo', [False, True])
def test_cut_z_zero_fails_cleanly(multigeo):
    app, results = run_milling(multigeo)
    assert results and all(result == 'fail' for result in results)
    messages = ' '.join(str(call.args[0]) for call in app.inform.emit.call_args_list)
    assert 'unpack' not in messages
