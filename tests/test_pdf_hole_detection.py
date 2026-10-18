#!/usr/bin/env python
"""Minimal regression tests for PDF import geometry and stream extraction."""

import os
import sys
import zlib
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from shapely import Point, Polygon
from shapely.ops import unary_union

from appParsers.ParsePDF import PdfParser
from appParsers.PdfStreamParser import PurePythonPdfParser, PdfParserError

# ponytail: tiny synthetic inputs cover the import path without full-board scans.


def test_hole_detection_modes():
    assert PdfParser(units='MM', resolution=10, abort=False).hole_detection_mode == 'both'
    for mode in ('both', 'fill_only', 'stroke_only'):
        parser = PdfParser(units='MM', resolution=10, abort=False, hole_detection_mode=mode)
        assert parser.hole_detection_mode == mode
    with pytest.raises(ValueError, match='Invalid hole_detection_mode'):
        PdfParser(units='MM', resolution=10, abort=False, hole_detection_mode='invalid')


def _parse(stream, units='INCH'):
    return PdfParser(units=units, resolution=64, abort=False).parse_pdf(stream)


def _all_solids(data):
    geometries = [element['solid'] for layer_nr, layer in data.items() if layer_nr != 0
                  for aperture in layer.values() for element in aperture.get('geometry', [])
                  if 'solid' in element]
    return unary_union(geometries) if geometries else Polygon()


def _make_tool(units='MM'):
    from PyQt6 import QtWidgets

    global _QT_APP
    _QT_APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    from appPlugins.ToolPdf.PdfImport import ToolPDF

    tool = ToolPDF.__new__(ToolPDF)
    rendered = []

    class Sink:
        def emit(self, *args):
            pass

    class Progress:
        def new(self, *args):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def new_object(kind, name, init, **kwargs):
        obj = SimpleNamespace(
            regenerate_source=lambda **kwargs: None,
            app=tool.app,
        )
        if kind == 'excellon':
            def add_tool(dia, drills, tool_id):
                obj.tools[tool_id] = {
                    'tooldia': dia,
                    'drills': drills,
                    'solid_geometry': [point.buffer(dia / 2) for point in drills],
                }

            obj.add_tool = add_tool
            obj.create_geometry = lambda: None

        init(obj, tool.app)
        rendered.append(obj)
        return obj

    tool.app = SimpleNamespace(
        app_obj=SimpleNamespace(new_object=new_object),
        proc_container=Progress(),
        file_opened=Sink(),
        inform=Sink(),
        app_units=units,
        log=SimpleNamespace(debug=lambda *args: None, error=lambda *args: None),
    )
    return tool, rendered


def test_parser_even_odd_and_nonzero_winding():
    for operator, area in (('f*', 300.0), ('f', 400.0)):
        data = _parse('0 0 20 20 re 5 5 10 10 re ' + operator)
        assert _all_solids(data).area * 72 ** 2 == pytest.approx(area, abs=1e-6)


def test_parser_nested_q_q_transforms():
    stream = ('q 2 0 0 1 0 0 cm '
              'q 1 0 0 1 10 0 cm 0 0 5 5 re f Q '
              '0 0 5 5 re f Q')
    solid = _all_solids(_parse(stream))
    assert tuple(value * 72 for value in solid.bounds) == \
        pytest.approx((0.0, 0.0, 30.0, 5.0), abs=1e-6)
    assert solid.area * 72 ** 2 == pytest.approx(100.0, abs=1e-6)


def test_gerber_export_roundtrip_keeps_holes_and_islands():
    from appObjects.GerberObject import GerberObject
    from appParsers.ParseGerber import Gerber
    from test_gerber_parser import MockApp

    stream = ('0 1 0 rg 0 0 20 20 re f '
              '1 1 1 rg 5 5 10 10 re f '
              '0 1 0 rg 7 7 6 6 re f '
              '1 1 1 RG 2 w 0 18 m 20 18 l S')
    data = _parse(stream, units='MM')
    assert [layer for layer in data if layer != 0] == [1]
    tool, rendered = _make_tool()
    tool.layer_rendering_as_gerber('test.pdf', data[1], 1)
    expected = unary_union(rendered[-1].solid_geometry)

    body = GerberObject.export_gerber(rendered[-1], 4, 6)
    text = '%FSLAX46Y46*%\n%MOMM*%\nG01*\n%LPD*%\n' + body + 'M02*\n'
    parser = Gerber(MockApp())
    parser.parse_lines(text.splitlines())
    parsed = unary_union(parser.solid_geometry) if parser.solid_geometry else Polygon()

    assert parsed.symmetric_difference(expected).area == pytest.approx(0.0, abs=5e-3)
    assert parsed.covers(Point(1.0, 1.0))
    assert not parsed.covers(Point(2.0, 2.0))
    assert parsed.covers(Point(3.0, 3.0))
    assert not parsed.covers(Point(10 * 25.4 / 72, 18 * 25.4 / 72))


def test_excellon_filters_and_deduplicates_drills():
    tool, rendered = _make_tool()
    tool.layer_rendering_as_excellon('test.pdf', {0: {'geometry': [
        {'clear': Point(0, 0).buffer(5.0)},
        {'clear': Point(0.002, 0).buffer(0.5)},
        {'clear': Point(0.002, 0).buffer(0.5)},
        {'clear': Point(20, 0).buffer(2.5)},
        {'clear': Point(30, 0).buffer(1.0).envelope},
    ]}}, 0)
    tools = rendered[-1].tools
    counts = {round(spec['tooldia'], 3): len(spec['drills']) for spec in tools.values()}
    assert counts == {1.0: 1, 5.0: 1}
    small = next(spec for spec in tools.values() if spec['tooldia'] < 2)
    assert small['drills'][0].x == pytest.approx(0.002)


def _make_pdf(contents_refs, stream_objects):
    parts = [b'%PDF-1.4\n']
    parts.append(b'1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')
    parts.append(b'2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n')
    if len(contents_refs) > 1:
        contents = b'[' + b' '.join(b'%d 0 R' % number for number in contents_refs) + b']'
    else:
        contents = b'%d 0 R' % contents_refs[0]
    parts.append(b'3 0 obj\n<< /Type /Page /Parent 2 0 R /Contents ' +
                 contents + b' >>\nendobj\n')
    for number, dictionary, data in stream_objects:
        parts.append(b'%d 0 obj\n<< ' % number + dictionary + b' /Length ' +
                     str(len(data)).encode() + b' >>\nstream\n' + data +
                     b'\nendstream\nendobj\n')
    parts.append(b'%%EOF\n')
    return b''.join(parts)


def test_first_page_contents_are_extracted_in_order(tmp_path):
    first = b'0 0 10 10 re f'
    second = b'100 100 10 10 re f\n(endobj endstream 5 0 obj) Tj'
    pdf = _make_pdf([5, 4], [
        (4, b'/Filter /FlateDecode', zlib.compress(first)),
        (5, b'', second),
        (6, b'', b'unreferenced stream'),
    ])
    path = tmp_path / 'ordered.pdf'
    path.write_bytes(pdf)
    assert PurePythonPdfParser().extract_content_streams(str(path)) == \
        (second + b'\n' + first).decode('ascii')


def test_unsupported_pdf_filter_is_reported(tmp_path):
    pdf = _make_pdf([4], [(4, b'/Filter /LZWDecode', b'not-lzw')])
    path = tmp_path / 'unsupported.pdf'
    path.write_bytes(pdf)
    with pytest.raises(PdfParserError, match='Unsupported PDF filter'):
        PurePythonPdfParser().extract_content_streams(str(path))


def test_encrypted_pdf_is_rejected(tmp_path):
    pdf = _make_pdf([4], [(4, b'', b'0 0 10 10 re\nf')])
    pdf = pdf.replace(b'%%EOF', b'trailer\n<< /Encrypt 9 0 R >>\n%%EOF')
    path = tmp_path / 'encrypted.pdf'
    path.write_bytes(pdf)
    with pytest.raises(PdfParserError, match='Encrypted'):
        PurePythonPdfParser().extract_content_streams(str(path))


if __name__ == '__main__':
    sys.exit(pytest.main([__file__]))
