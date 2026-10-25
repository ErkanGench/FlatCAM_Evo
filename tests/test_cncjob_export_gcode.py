"""
CNCJobObject.export_gcode() must keep the G-code of every tool of a multi-tool job, whatever the preprocessor
and whatever the kind of the source object (Excellon or Geometry).

The preprocessors Roland_MDX_20, Roland_MDX_540 and ISEL_ICP_CNC have ``include_header = False``. For them the
per-tool G-code was added only for Geometry jobs, so the file of an Excellon (drill) job held the start and the end
code and no drill moves at all.
"""

import importlib
import pkgutil
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import appPreProcessor
import preprocessors
from appObjects.CNCJobObject import CNCJobObject

for _module in pkgutil.iter_modules(preprocessors.__path__):
    importlib.import_module('preprocessors.' + _module.name)
# a copy: other tests of the same worker change the global registry
PREPROCESSORS = dict(appPreProcessor.preprocessors)

HEADERLESS = ('ISEL_ICP_CNC', 'Roland_MDX_20', 'Roland_MDX_540')

# the key of the preprocessor name inside the tool's options depends on the kind of the source object
PP_KEY = {'Excellon': 'tools_drill_ppname_e', 'Geometry': 'tools_mill_ppname_g'}


class _Log:
    def debug(self, *args, **kwargs):
        pass

    info = warning = error = debug


def _job(kind, ppname):
    app = SimpleNamespace(preprocessors=PREPROCESSORS, log=_Log())
    job = SimpleNamespace(
        app=app,
        obj_options={'type': kind, 'name': 'job'},
        multitool=True,
        tools={uid: {'data': {PP_KEY[kind]: ppname}, 'gcode': code}
               for uid, code in enumerate(('BODY_TOOL_1\n', 'BODY_TOOL_2\n'), 1)},
        gcode='', gc_start='START_CODE\n', gc_header='HEADER\n',
    )
    options = {'cncjob_footer': False, 'cncjob_prepend': '', 'cncjob_append': '', 'cncjob_line_ending': False}
    job._app_option = lambda key, fallback=None: options.get(key, fallback)
    job.gcode_footer = lambda: ''
    return job


def _export(job):
    return CNCJobObject.export_gcode(job, to_file=True).getvalue()


@pytest.mark.parametrize('kind', ['Excellon', 'Geometry'])
def test_every_preprocessor_keeps_the_code_of_every_tool(kind):
    dropped = []
    for ppname in sorted(appPreProcessor.preprocessors):
        text = _export(_job(kind, ppname))
        if not ('BODY_TOOL_1' in text and 'BODY_TOOL_2' in text
                and text.index('BODY_TOOL_1') < text.index('BODY_TOOL_2')):
            dropped.append(ppname)

    assert dropped == []


@pytest.mark.parametrize('ppname', HEADERLESS)
def test_headerless_drill_job_has_start_code_tool_code_and_no_page_header(ppname):
    text = _export(_job('Excellon', ppname))

    assert text.startswith('START_CODE')
    assert text.index('START_CODE') < text.index('BODY_TOOL_1') < text.index('BODY_TOOL_2')
    # include_header = False: the gc_header block is not written
    assert 'HEADER' not in text


def test_hpgl_drill_job_is_detected_from_tools_drill_ppname_e():
    job = _job('Excellon', 'hpgl')
    job.tools = {1: {'data': {'tools_drill_ppname_e': 'hpgl'}, 'gcode': 'PA12.7,3.5;\n'}}

    text = _export(job)

    # HPGL output rounds the PA coordinates to whole units
    assert 'PA12,3;' in text
    assert 'PA12.7' not in text


def test_gcode_header_of_drill_job_reads_legacy_ppname_e():
    app = SimpleNamespace(log=_Log(), version='1', version_date='2')
    job = SimpleNamespace(
        app=app, units='mm', tools={},
        obj_options={'type': 'Excellon', 'name': 'job', 'ppname_e': 'marlin'},
    )

    assert ';Marlin(Repetier) G-code' in CNCJobObject.gcode_header(job)


@pytest.mark.parametrize('kind', ['Excellon', 'Geometry'])
def test_unknown_preprocessor_of_a_saved_job_exports_with_the_default_one(kind):
    job = _job(kind, 'Gone_Machine')
    job.app.inform = Mock()
    job.app.options = {}

    text = _export(job)

    assert 'BODY_TOOL_1' in text and 'BODY_TOOL_2' in text
    assert 'Gone_Machine' in job.app.inform.emit.call_args[0][0]


def test_unknown_preprocessor_of_a_saved_tool_generates_with_the_default_one():
    from camlib import get_preprocessor
    app = SimpleNamespace(preprocessors={'default': 'DEFAULT_PP'}, inform=Mock())

    assert get_preprocessor(app, 'Gone_Machine') == 'DEFAULT_PP'
    assert 'Gone_Machine' in app.inform.emit.call_args[0][0]
