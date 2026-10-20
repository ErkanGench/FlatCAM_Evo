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

import pytest

import appPreProcessor
import preprocessors
from appObjects.CNCJobObject import CNCJobObject

for _module in pkgutil.iter_modules(preprocessors.__path__):
    importlib.import_module('preprocessors.' + _module.name)

HEADERLESS = ('ISEL_ICP_CNC', 'Roland_MDX_20', 'Roland_MDX_540')

# the key of the preprocessor name inside the tool's options depends on the kind of the source object
PP_KEY = {'Excellon': 'tools_drill_ppname_e', 'Geometry': 'tools_mill_ppname_g'}


class _Log:
    def debug(self, *args, **kwargs):
        pass

    info = warning = error = debug


def _job(kind, ppname):
    app = SimpleNamespace(preprocessors=appPreProcessor.preprocessors, log=_Log())
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


def test_the_headerless_preprocessors_are_the_ones_this_test_is_about():
    assert {name for name, pp in appPreProcessor.preprocessors.items() if pp.include_header is False} \
        == set(HEADERLESS)


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


@pytest.mark.parametrize('ppname', HEADERLESS)
def test_headerless_geometry_job_is_written_as_before(ppname):
    text = _export(_job('Geometry', ppname))

    assert text.startswith('START_CODE')
    assert 'BODY_TOOL_1' in text and 'BODY_TOOL_2' in text
    assert 'HEADER' not in text
