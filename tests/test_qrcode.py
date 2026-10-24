"""QR Code plugin: the Qt-free model (QRCodeGen)."""

import datetime
import io
import math

import pytest
from shapely import box
from shapely.affinity import translate
from shapely.ops import unary_union

from appPlugins.ToolQRCode import QRCodeGen as gen

MM = 25.4


def _qr(text='HELLO', version=1, error='L', box_size=10, border=2, units='MM', **kw):
    return gen.qr_geometry(text, version, error, box_size, border, units, **kw)


def _solid(*polys):
    return list(polys)


# --- sizes ---------------------------------------------------------------------------------------------------------
def test_module_size_follows_units():
    assert gen.module_size(10, 'MM') == pytest.approx(1.0)
    assert gen.module_size(10, 'IN') == pytest.approx(1.0 / MM)


@pytest.mark.parametrize('units, div', [('MM', 1.0), ('IN', MM)])
def test_qr_geometry_size_in_project_units(units, div):
    modules, utility, info = _qr(units=units)
    assert info['version'] == 1 and info['modules'] == 21
    a, b, c, d = utility.bounds
    assert (c - a) == pytest.approx(21 / div, rel=1e-3) and (d - b) == pytest.approx(21 / div, rel=1e-3)
    assert info['width'] == pytest.approx(25 / div, rel=1e-3)
    assert unary_union(modules).area == pytest.approx(utility.area, rel=1e-3)


def test_qr_geometry_empty_text_raises():
    with pytest.raises(ValueError):
        _qr(text='')


def test_border_zero_and_mask_pattern_change_modules():
    _, util0, info0 = _qr(border=0)
    assert info0['width'] == pytest.approx(21)
    assert util0.bounds[0] == pytest.approx(0, abs=1e-3)
    _, util_a, _ = _qr(mask_pattern=0)
    _, util_b, _ = _qr(mask_pattern=3)
    assert not util_a.equals(util_b)


# --- version -------------------------------------------------------------------------------------------------------
def test_fixed_version_overflow_raises_and_auto_grows():
    long_text = 'X' * 60
    with pytest.raises(gen.QRDataOverflow):
        _qr(text=long_text, version=1)
    _, _, info = _qr(text=long_text, version=None)
    assert info['version'] > 1
    assert gen.qr_info(long_text, None, 'L')['version'] == info['version']
    assert gen.qr_info('A', 3, 'M') == {'version': 3, 'modules': 29}


# --- insert_geometry -----------------------------------------------------------------------------------------------
def _insert(solid, tools, pos=(0.0, 0.0), units='MM', **kw):
    modules, utility, _ = _qr(units=units)
    kwargs = dict(border_size=2, box_size=10, rounded='s', polarity='pos', units=units)
    kwargs.update(kw)
    return gen.insert_geometry(solid, tools, modules, utility, pos, **kwargs), modules, utility


def test_partial_overlap_is_cut_and_far_copper_is_kept():
    big = box(-50, -50, 12, 12)         # QR mask (25 x 25 at pos 0,0) overlaps its corner only partly
    far = box(100, 100, 110, 110)
    ((solid, tools), modules, utility) = _insert(_solid(big, far), {})
    mask = box(*utility.bounds).buffer(2.0, join_style='mitre')
    kept = [g for g in solid if g.intersects(far)]
    assert kept and kept[0].equals(far)
    others = unary_union([g for g in solid if not g.intersects(far)])
    assert others.intersection(mask).area == pytest.approx(utility.area, rel=1e-3)   # only the QR is in the mask
    assert others.area > utility.area                                              # the cut copper remains


def test_fully_covered_poly_is_dropped_and_multi_result_is_split():
    inner = box(2.5, 2.5, 3.5, 3.5)    # inside the mask: removed entirely
    strip = box(-30, 10, 60, 11)        # crossing the mask: becomes two pieces
    (solid, _), _, utility = _insert(_solid(inner, strip), {})
    mask = box(*utility.bounds).buffer(2.0, join_style='mitre')
    assert not any(g.equals(inner) or g.equals(strip) for g in solid)
    pieces = [g for g in solid if g.bounds[1] >= 10 - 1e-6 and g.bounds[3] <= 11 + 1e-6 and g.bounds[2] - g.bounds[0] > 5]
    assert len(pieces) == 2 and sum(p.area for p in pieces) == pytest.approx(strip.area - 25.0)
    assert all(not p.intersects(mask.buffer(-1e-6)) for p in pieces)


def test_units_inch_scale_mask_and_aperture():
    big = box(-5, -5, 5, 5)
    (solid, tools), modules, utility = _insert(_solid(big), {}, units='IN')
    mod = 1.0 / MM
    aid = [k for k in tools if k != 0][0]
    assert tools[aid]['width'] == pytest.approx(mod * 1.01)
    mask = tools[0]['geometry'][0]['clear']
    assert mask.bounds[2] - mask.bounds[0] == pytest.approx(21 * mod + 4 * mod, rel=1e-3)


def test_aperture_key_types_and_ids():
    modules, utility, _ = _qr()
    args = (modules, utility, (0, 0), 2, 10, 's', 'pos')
    ints = {0: {'type': 'REG', 'size': 0.0, 'geometry': []}, 10: {'type': 'C', 'size': 1.0, 'geometry': []}}
    _, t = gen.insert_geometry([], ints, *args)
    assert sorted(t) == [0, 10, 11] and all(isinstance(k, int) for k in t)
    strs = {'0': {'type': 'REG', 'size': 0.0, 'geometry': []}, '12': {'type': 'C', 'size': 1.0, 'geometry': []}}
    _, t = gen.insert_geometry([], strs, *args)
    assert sorted(t) == ['0', '12', '13'] and len(t['0']['geometry']) == 1
    low = {1: {'type': 'C', 'size': 1.0, 'geometry': []}}
    _, t = gen.insert_geometry([], low, *args)
    assert sorted(t, key=str) == [0, 1, 10]
    _, t = gen.insert_geometry([], {}, *args)
    assert sorted(t) == [0, 10]


def test_source_inputs_are_not_modified():
    big = box(-50, -50, 12, 12)
    ap0 = {'type': 'REG', 'size': 0.0, 'geometry': [{'clear': box(0, 0, 1, 1)}]}
    ap1 = {'type': 'C', 'size': 1.0, 'geometry': [{'solid': big}]}
    tools = {0: ap0, 1: ap1}
    solid = [big]
    modules, utility, _ = _qr()
    new_solid, new_tools = gen.insert_geometry(solid, tools, modules, utility, (0, 0), 2, 10, 's', 'pos')
    assert solid == [big] and set(tools) == {0, 1}
    assert len(ap0['geometry']) == 1 and len(ap1['geometry']) == 1
    assert new_tools is not tools and len(new_tools[0]['geometry']) == 2 and len(new_tools[10]['geometry']) == len(
        modules)
    assert new_solid is not solid


def test_margin_overrides_border_rule():
    modules, utility, _ = _qr()
    base = dict(border_size=2, box_size=10, rounded='s', polarity='pos', units='MM')
    _, t_rule = gen.insert_geometry([], {}, modules, utility, (0, 0), **base)
    _, t_margin = gen.insert_geometry([], {}, modules, utility, (0, 0), margin=5.0, **base)
    w_rule = t_rule[0]['geometry'][0]['clear'].bounds
    w_margin = t_margin[0]['geometry'][0]['clear'].bounds
    assert (w_rule[2] - w_rule[0]) == pytest.approx(21 + 4)
    assert (w_margin[2] - w_margin[0]) == pytest.approx(21 + 10)


def test_negative_polarity_and_outline():
    modules, utility, _ = _qr()
    base = dict(border_size=2, box_size=10, rounded='s', units='MM')
    (solid, _tools, outline) = gen.insert_geometry([], {}, modules, utility, (5, 5), polarity='neg',
                                                   with_outline=True, **base)
    mask = translate(box(*utility.bounds).buffer(2.0, join_style='mitre'), 5, 5)
    assert unary_union(solid).area == pytest.approx(mask.area - utility.area, rel=1e-3)
    assert unary_union(outline).equals_exact(translate(utility, 5, 5), 1e-6) or \
        unary_union(outline).symmetric_difference(translate(utility, 5, 5)).area < 1e-6


def test_new_gerber_geometry_and_mask_opening():
    modules, utility, _ = _qr()
    base = dict(border_size=2, box_size=10, rounded='s', units='MM')
    solid, tools = gen.new_gerber_geometry(modules, utility, (3, 4), polarity='pos', **base)
    assert unary_union(solid).symmetric_difference(translate(utility, 3, 4)).area < 1e-6
    assert sorted(tools) == [10] and len(tools[10]['geometry']) == len(modules)
    solid, tools = gen.new_gerber_geometry(modules, utility, (3, 4), polarity='neg', **base)
    mask = gen.mask_opening(utility, (3, 4), **base)
    assert unary_union(solid).area == pytest.approx(mask.area - utility.area, rel=1e-3)
    assert mask.bounds[0] == pytest.approx(utility.bounds[0] - 2 + 3)


def test_add_region_keeps_the_other_openings():
    # a soldermask opening must not cut the openings that are already there (dark = opening)
    opening = box(0, 0, 10, 10).buffer(2)                  # rounded corners
    corner = box(-1.9, -1.9, -1.5, -1.5)                    # inside the bbox, outside the rounded opening
    old = {10: {'type': 'C', 'size': 0.4, 'geometry': [{'solid': corner}]}}
    solid, tools = gen.add_region([corner], old, opening)
    assert unary_union(solid).area == pytest.approx(opening.area + corner.area)
    assert old[10]['geometry'] == [{'solid': corner}] and 0 not in old
    regions = [g['solid'] for g in tools[0]['geometry']]
    assert len(regions) == 1 and regions[0].equals(opening)


# --- utility geometry ----------------------------------------------------------------------------------------------
def test_row_merge_equals_plain_union():
    modules, _, _ = _qr(text='ROW MERGE TEST 0123456789', version=None)
    merged = gen.utility_geometry(modules)
    plain = unary_union(modules).buffer(1e-7).buffer(-1e-7)
    assert merged.symmetric_difference(plain).area < 1e-6 * merged.area
    assert merged.bounds == pytest.approx(plain.bounds, abs=1e-6)


def test_row_merge_large_code_is_fast():
    squares = [box(x * 0.1, y * 0.1, x * 0.1 + 0.1, y * 0.1 + 0.1) for x in range(100) for y in range(100)
               if (x * y) % 3]
    out = gen.utility_geometry(squares)
    assert out.area == pytest.approx(sum(s.area for s in squares), rel=1e-6)


# --- transforms ----------------------------------------------------------------------------------------------------
def test_mirror_rotate_and_anchor():
    asym = box(0, 0, 4, 2).union(box(0, 2, 1, 4))          # L shape, bbox 4 x 4
    other = box(10, 0, 12, 1)
    ref = unary_union([asym, other])
    # no transform, anchor bl: bbox lower-left goes to the origin
    out = gen.transform_geometry([asym, [other]], 0, False, 'bl')
    assert unary_union([out[0]] + out[1]).bounds == pytest.approx((0, 0, 12, 4))
    # mirror about the vertical axis keeps the bbox centre and flips x
    m = gen.transform_geometry([asym, [other]], 0, True, 'bl')
    assert m[1][0].bounds == pytest.approx((0, 0, 2, 1))
    assert m[0].bounds[0] == pytest.approx(8)
    # rotation 90 CCW swaps width and height, anchor c puts the bbox centre at the origin
    r = gen.transform_geometry([asym, [other]], 90, False, 'c')
    b = unary_union([r[0]] + r[1]).bounds
    assert (b[2] - b[0], b[3] - b[1]) == pytest.approx((4, 12))
    assert (b[0] + b[2]) / 2 == pytest.approx(0, abs=1e-9) and (b[1] + b[3]) / 2 == pytest.approx(0, abs=1e-9)
    # top-right anchor with margin: the margin-expanded bbox corner is the origin
    t = gen.transform_geometry([asym, [other]], 0, False, 'tr', margin=1.0)
    assert unary_union([t[0]] + t[1]).bounds[2] == pytest.approx(-1.0) and \
        unary_union([t[0]] + t[1]).bounds[3] == pytest.approx(-1.0)
    assert ref.area == pytest.approx(unary_union([asym, other]).area)
    with pytest.raises(ValueError):
        gen.transform_geometry([asym], 45, False, 'bl')


def test_transformed_qr_is_still_inserted_exactly():
    modules, utility, _ = _qr()
    modules, utility = gen.transform_geometry([modules, utility], 90, True, 'bl', margin=2.0)
    base = dict(border_size=2, box_size=10, rounded='s', units='MM')
    mask = gen.mask_opening(utility, (7, 8), **base)
    assert mask.bounds[:2] == pytest.approx((7, 8), abs=1e-6)
    solid, tools = gen.new_gerber_geometry(modules, utility, (7, 8), polarity='pos', **base)
    assert unary_union(solid).bounds[0] == pytest.approx(7 + 2)


# --- preview -------------------------------------------------------------------------------------------------------
def test_preview_rings_under_limit_and_box_over_limit():
    modules, utility, _ = _qr()
    rings = gen.preview_geometry(modules, utility, None, (1, 1), len(modules) + 1)
    assert rings and all(r.geom_type == 'LinearRing' for r in rings)
    boxes = gen.preview_geometry(modules, utility, box(*utility.bounds), (1, 1), 5)
    assert len(boxes) == 1 and boxes[0].bounds == pytest.approx(translate(box(*utility.bounds), 1, 1).bounds)


# --- images --------------------------------------------------------------------------------------------------------
def _svg_text(**kw):
    img = gen.make_qr_image('HELLO', 1, 'L', 10, 2, 'svg', **kw)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


def test_svg_colors_fill_and_background():
    text = _svg_text(fill_color='#ff0000', back_color='#00ff00')
    assert 'fill_color' not in text and 'back_color' not in text
    assert '<path fill="#ff0000"' in text
    assert text.index('<rect') < text.index('<path') and '#00ff00' in text


@pytest.mark.parametrize('back', ['transparent', None])
def test_svg_transparent_or_missing_colors_do_not_crash(back):
    text = _svg_text(fill_color=None, back_color=back)
    assert '<rect' not in text and '<path' in text


def test_png_and_fixed_version_image():
    img = gen.make_qr_image('HELLO', 1, 'L', 10, 2, 'png', '#000000', '#ffffff')
    assert img.size == (250, 250)
    with pytest.raises(gen.QRDataOverflow):
        gen.make_qr_image('X' * 60, 1, 'L', 10, 2, 'png')
    img = gen.make_qr_image('HELLO', 1, 'L', 10, 2, 'png', '#000000', 'transparent')
    assert img.size == (250, 250)


def test_valid_color():
    assert gen.valid_color('#ff00aa') and gen.valid_color('red')
    assert not gen.valid_color('') and not gen.valid_color('notacolor') and not gen.valid_color(None)
    assert not gen.valid_color('transparent')
    assert gen.valid_color('transparent', allow_transparent=True)


# --- tokens and warnings -------------------------------------------------------------------------------------------
def test_expand_tokens():
    ctx = {'date': datetime.date(2026, 10, 24), 'time': datetime.time(9, 5, 7), 'project': 'P1', 'object': 'top',
           'serial': 7}
    assert gen.expand_tokens('{date} {time} {project}/{object} #{serial}', ctx, serial_pad=4) == \
        '2026-10-24 09:05 P1/top #0007'
    assert gen.expand_tokens('{unknown}-{serial}', {'serial': 12}) == '{unknown}-12'
    assert gen.expand_tokens('{date}', {'date': '2026-01-02'}) == '2026-01-02'
    assert gen.expand_tokens('{project}', {}) == '{project}'


def test_size_warnings():
    assert gen.size_warnings(0.1, 'MM', 0.15, 4) == ['module_below_min']
    assert gen.size_warnings(0.1 / MM, 'IN', 0.15, 4) == ['module_below_min']
    assert gen.size_warnings(0.2, 'MM', 0.15, 4) == []
    assert gen.size_warnings(0.2, 'MM', 0.15, 2) == ['quiet_zone']
    assert gen.size_warnings(0.1, 'MM', 0.15, 0) == ['module_below_min', 'quiet_zone']


# --- the plugin controller (headless App) --------------------------------------------------------------------------
import os
import sys
import time
from types import SimpleNamespace

from PyQt6 import QtWidgets

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import appHandlers.appHistory as appHistory
from appMain import App
from appObjects.AppObjectTemplate import FlatCAMObj
from appGUI.GUIElements import FCFileSaveDialog

FIX = os.path.join(os.path.dirname(__file__), 'fixtures', 'unify')


@pytest.fixture(scope='module')
def fc():
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app = App(qapp=qapp, headless=True)
    appHistory.RECORD_IN_HEADLESS = True
    yield app
    appHistory.RECORD_IN_HEADLESS = False


@pytest.fixture
def tool(fc, monkeypatch):
    monkeypatch.setattr(FlatCAMObj, 'plot', lambda *a, **k: None)
    monkeypatch.setattr(FlatCAMObj, 'plot_transformed', lambda *a, **k: True)
    qr = fc.qrcode_tool
    qr.set_tool_ui()
    # the canvas of a headless App has no coordinates: the event position is the canvas position
    monkeypatch.setattr(qr, 'event_position', lambda pos: pos)
    messages = []
    fc.inform.connect(messages.append)
    qr.messages = messages
    yield qr
    fc.inform.disconnect(messages.append)
    qr.on_exit()
    fc.event_is_dragging = False
    for obj in list(fc.collection.get_list()):
        fc.collection.delete_by_name(obj.obj_options['name'], select_project=False)


def _settle(cond, timeout=5.0):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.01)
    QtWidgets.QApplication.processEvents()


def _gerber(fc, name='top'):
    def init(obj, _app):
        obj.parse_file(os.path.join(FIX, 'unify_rect.gbr'))
    return fc.app_obj.new_object('gerber', name, init, plot=False)


def _area(obj):
    geo = obj.solid_geometry
    return unary_union(geo if isinstance(geo, list) else [geo]).area


def _setup(tool, obj, text='HELLO', **widgets):
    ui = tool.ui
    ui.grb_object_combo.set_value(obj.obj_options['name'])
    ui.text_data.set_value(text)
    ui.version_auto_cb.set_value(False)
    ui.version_entry.set_value(1)
    ui.border_size_entry.set_value(2)
    ui.bsize_entry.set_value(10)
    ui.pol_radio.set_value('pos')
    for key, value in widgets.items():
        getattr(ui, key).set_value(value)
    tool.update_enabled()


def _arm(tool):
    tool.execute()
    _settle(lambda: tool.armed or any('ERROR' in m for m in tool.messages))


def _click(tool, x, y, button=1):
    tool.on_mouse_release(SimpleNamespace(pos=(x, y), button=button))


@pytest.mark.slow
@pytest.mark.parametrize('level', ['b', 'a'])
def test_insert_button_is_visible_in_both_modes(tool, level):
    tool.change_level(level)
    assert not tool.ui.qrcode_button.isHidden()


@pytest.mark.slow
def test_export_keeps_undo_available_and_rejects_bad_colors(fc, tool, tmp_path, monkeypatch):
    png, svg = str(tmp_path / 'a.png'), str(tmp_path / 'a.svg')
    paths = iter([png, svg])
    monkeypatch.setattr(FCFileSaveDialog, 'get_saved_filename', lambda **k: (next(paths), ''))
    tool.ui.text_data.set_value('HELLO')
    tool.ui.fill_color_entry.set_value('#112233')
    tool.ui.back_color_entry.set_value('transparent')
    tool.export_png_file()
    tool.export_svg_file()
    _settle(lambda: os.path.exists(png) and os.path.exists(svg))
    assert os.path.getsize(png) > 0 and '#112233' in open(svg).read()
    assert fc.call_source == 'app'
    assert any('[success]' in m for m in tool.messages)
    tool.ui.fill_color_entry.set_value('notacolor')
    assert tool.export_png_file() == 'fail'
    assert any('ERROR' in m for m in tool.messages)


@pytest.mark.slow
def test_overflow_is_reported_and_the_tool_is_not_armed(fc, tool):
    obj = _gerber(fc)
    _setup(tool, obj, text='X' * 200)
    _arm(tool)
    assert not tool.armed and fc.call_source == 'app'
    assert any('ERROR' in m for m in tool.messages)


@pytest.mark.slow
def test_reset_disarms_and_restores_the_call_source(fc, tool):
    _setup(tool, _gerber(fc))
    _arm(tool)
    assert tool.armed and fc.call_source == 'qrcode_tool'
    tool.set_tool_ui()
    assert not tool.armed and fc.call_source == 'app'


@pytest.mark.slow
def test_drag_release_does_not_insert_and_a_click_does(fc, tool):
    obj = _gerber(fc)
    _setup(tool, obj)
    before = _area(obj)
    _arm(tool)
    fc.event_is_dragging = True
    _click(tool, 30, 30)
    assert tool.armed and _area(obj) == before
    fc.event_is_dragging = False
    _click(tool, 30, 30)
    assert not tool.armed and fc.call_source == 'app' and _area(obj) != before


@pytest.mark.slow
def test_deleted_target_is_refused(fc, tool):
    obj = _gerber(fc)
    _setup(tool, obj)
    _arm(tool)
    fc.collection.delete_by_name('top', select_project=False)
    _click(tool, 30, 30)
    assert not tool.armed and fc.call_source == 'app'
    assert any('ERROR' in m for m in tool.messages)


@pytest.mark.slow
def test_inch_project_inserts_the_qr_in_inches(fc, tool, monkeypatch):
    monkeypatch.setattr(fc, 'app_units', 'IN')
    obj = _gerber(fc)
    _setup(tool, obj, placement_radio='coords', x_entry=0.0, y_entry=0.0)
    before = obj.solid_geometry
    tool.execute()
    _settle(lambda: obj.solid_geometry is not before)
    added = unary_union([g for g in obj.solid_geometry if g not in before])
    # version 1 = 21 modules of box_size / 10 mm
    assert added.bounds[2] - added.bounds[0] == pytest.approx(21 * 1.0 / MM, rel=0.02)


@pytest.mark.slow
def test_keep_placing_increments_the_serial_and_stays_armed(fc, tool):
    obj = _gerber(fc)
    _setup(tool, obj, text='S{serial}', multi_cb=True, serial_start_entry=5, serial_step_entry=2,
           serial_pad_entry=3)
    tool.on_serial_start_changed(5)
    _arm(tool)
    assert tool.plan.text == 'S005'
    _click(tool, 30, 30)
    assert tool.armed and tool.serial == 7 and tool.plan.text == 'S007'
    _click(tool, 60, 30)
    assert tool.armed and tool.serial == 9
    _click(tool, 0, 0, button=2)
    assert not tool.armed and fc.call_source == 'app'


@pytest.mark.slow
def test_new_object_output_keeps_the_source(fc, tool):
    obj = _gerber(fc)
    _setup(tool, obj, output_radio='new')
    before = _area(obj)
    _arm(tool)
    _click(tool, 30, 30)
    _settle(lambda: fc.collection.get_by_name('top_qrcode') is not None)
    new = fc.collection.get_by_name('top_qrcode')
    assert new is not None and _area(obj) == before
    assert new.bounds()[0] >= 30 - 1e-6 and _area(new) > 0


@pytest.mark.slow
def test_coordinates_placement_puts_the_anchor_at_the_point(fc, tool):
    obj = _gerber(fc)
    _setup(tool, obj, placement_radio='coords', x_entry=50.0, y_entry=40.0, anchor_radio='bl')
    before = obj.solid_geometry
    tool.execute()
    _settle(lambda: obj.solid_geometry is not before)
    assert not tool.armed
    added = unary_union([g for g in obj.solid_geometry if g not in before])
    # border 2 modules (1 mm each) of clearance sit between the anchor and the code
    assert added.bounds[0] == pytest.approx(50.0 + 2.0, abs=1e-3)
    assert added.bounds[1] == pytest.approx(40.0 + 2.0, abs=1e-3)


@pytest.mark.slow
def test_soldermask_opening_is_added_to_the_other_gerber(fc, tool):
    obj, mask = _gerber(fc, 'top'), _gerber(fc, 'mask')
    _setup(tool, obj, placement_radio='coords', x_entry=50.0, y_entry=40.0, anchor_radio='bl', mask_cb=True)
    tool.ui.mask_object_combo.set_value('mask')
    before = mask.solid_geometry
    tool.execute()
    _settle(lambda: mask.solid_geometry is not before)
    assert mask.bounds()[2] >= 50.0 + 25 and mask.bounds()[3] >= 40.0 + 25


@pytest.mark.slow
def test_undo_of_an_insert_restores_the_gerber(fc, tool):
    obj = _gerber(fc)
    _setup(tool, obj)
    area, keys = _area(obj), sorted(obj.tools)
    _arm(tool)
    _click(tool, 30, 30)
    assert _area(obj) != area
    _settle(lambda: not fc.projects.is_busy())
    assert fc.history.undo(), fc.history.blocked_reason()
    _settle(lambda: not fc.projects.is_busy())
    assert _area(obj) == pytest.approx(area) and sorted(obj.tools) == keys

