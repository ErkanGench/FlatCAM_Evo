"""Native expectations, deliberately independent of the later CAM exports."""

import struct
import zipfile
from pathlib import Path

import pytest
from shapely import Point
from shapely.ops import unary_union

from appParsers.ParseProteus import ProteusParser, ProteusParseError


PROJECT = Path(__file__).parent / 'fixtures' / 'Proteus' / 'TP1_G1.pdsprj'
PROJECT9 = Path(__file__).parent / 'fixtures' / 'Proteus9' / 'pcb 1.pdsprj'


@pytest.fixture(scope='module')
def parsed():
    return ProteusParser().parse_file(PROJECT)


def rewrite_project(path, change):
    with zipfile.ZipFile(PROJECT) as source, zipfile.ZipFile(path, 'w') as target:
        for item in source.infolist():
            target.writestr(item.filename, change(item.filename, source.read(item)))
    return path


def test_all_embedded_boards_have_native_names_and_exportable_geometry(parsed):
    assert parsed.major_version == 8
    assert [(board.member_name, board.name) for board in parsed.boards] == [
        ('BOARD1.LYT', 'PCB0-Power-USB'), ('BOARD2.LYT', 'PCB01-FPGA'),
        ('BOARD3.LYT', 'PCB2-Sensores'), ('BOARD4.LYT', 'PCB3-Wireless')]
    for board in parsed.boards:
        assert {'Top Copper.GTL', 'Bottom Copper.GBL'} <= board.layers.keys()
        assert board.default_layers[:2] == ['Top Copper.GTL', 'Bottom Copper.GBL']
        assert all('unverified' not in name.lower() for name in board.default_layers)
        assert board.layers['Top Copper.GTL']['name'] == 'Top Copper'
        assert board.layers['Bottom Copper.GBL']['name'] == 'Bottom Copper'
        for layer in board.layers.values():
            assert layer['solid_geometry']
            assert all(geo.is_valid and not geo.is_empty for geo in layer['solid_geometry'])
            assert layer['tools'][0]['type'] == 'REG'
            assert layer['tools'][0]['geometry']
        assert all('tooldia' in tool and 'drills' in tool and 'slots' in tool
                   for tools in board.drill_groups.values() for tool in tools.values())


def test_wireless_drills_are_native_not_the_later_export(parsed):
    board = parsed.boards[3]
    tools = list(board.drill_groups['PTH'].values())
    assert {round(tool['tooldia'], 6): len(tool['drills']) for tool in tools} == {
        0.381: 18, 0.508: 16, 0.762: 12, 1.016: 78}
    positions = {(round(p.x, 5), round(p.y, 5)) for tool in tools for p in tool['drills']}
    assert (56.7, 33.9) in positions       # M3 local (17.5,17), placed at (39.2,16.9)
    assert (71.42, 48.44) in positions    # connector reflected in both axes, not rotated twice
    assert sum(len(tool['drills']) for tool in tools) == 124


def test_native_board_cutouts_are_four_padless_three_mm_drills(parsed):
    for board, origin in zip(parsed.boards, [(49.8, 25.1), (49.85, 24.93),
                                            (50.15, 25.17), (49.85, 25.27)]):
        tools = [tool for tool in board.drill_groups.get('NPTH', {}).values() if tool['tooldia'] == 3]
        assert len(tools) == 1
        assert tools[0]['tooldia'] == 3
        expected = {(round(origin[0] + x, 5), round(origin[1] + y, 5))
                    for x in (-47, 47) for y in (-22, 22)}
        assert len(tools[0]['drills']) == 4
        assert {(round(p.x, 5), round(p.y, 5)) for p in tools[0]['drills']} == expected
        paths = board.layers['Board Outline.GKO']['follow_geometry']
        circles = [path for path in paths if path.is_ring and
                   path.bounds[2] - path.bounds[0] == pytest.approx(3)]
        assert len(circles) == 4
        assert {(round(path.centroid.x, 5), round(path.centroid.y, 5)) for path in circles} == expected


@pytest.mark.parametrize('layer,hollow', [(59, 1), (36, 1), (59, 0)])
def test_only_hollow_board_circles_become_drills_anywhere(layer, hollow):
    from appParsers.ParseProteus8 import Proteus8Parser, _Reader

    board = Proteus8Parser()
    # Native circle encoding; deliberately non-corner centre, rotated and reflected placement.
    primitive = struct.pack('<IBBIBiIBIIBB', 48, 2, 2, 32, 0, 10160, 0, hollow, 0, 0, 2, 127)
    primitive += b'DEFAULT\0' + struct.pack('<iii', 200000, 300000, 150000)
    for _ in range(2):
        board._primitive(_Reader(primitive, 'circle.LYT'), layer, board._matrix(40, 20, 900, 1))
    board._finish()
    if layer == 59 and hollow:
        tool, = board.drill_groups['NPTH'].values()
        assert tool['tooldia'] == 3
        assert len(tool['drills']) == 1
        assert tool['drills'][0].equals_exact(Point(37, 18), 1e-9)
        assert board.layers.keys() == {'Board Outline.GKO'}
        assert not unary_union(board.layers['Board Outline.GKO']['solid_geometry']).covers(Point(37, 18))
    else:
        assert not board.drill_groups


def test_wireless_custom_antenna_is_transformed_native_polygon(parsed):
    copper = unary_union(parsed.boards[3].layers['Top Copper.GTL']['solid_geometry'])
    assert copper.covers(Point(98.2, 10))
    assert copper.covers(Point(93.2, 10))
    assert not copper.covers(Point(95.7, 10))  # gap between the last two antenna fingers
    assert copper.bounds[2] == pytest.approx(99.2, abs=0.001)


def test_saved_pours_preserve_voids_islands_and_touching_holes(parsed):
    wireless = parsed.boards[3]
    polygons = wireless.layers['Bottom Copper.GBL']['solid_geometry']
    assert sum(len(polygon.interiors) for polygon in polygons) > 20
    assert unary_union(polygons).area > 2600
    # BOARD2 has a saved region with sixteen disconnected contours. They must not be envelopes.
    fpga = parsed.boards[1].layers['Top Copper.GTL']['solid_geometry']
    assert sum(len(polygon.interiors) for polygon in fpga) > 20
    assert any('touching' in warning.lower() for warning in wireless.warnings)
    saved = wireless.layers['Unassigned region on layer 0 (unverified)']['solid_geometry']
    assert len(saved) == 1
    assert len(saved[0].interiors) == 34
    assert saved[0].area == pytest.approx(49.093025, abs=1e-6)
    assert 'Unassigned region on layer 0 (unverified)' not in wireless.default_layers


def test_routes_use_style_widths_and_keep_millimetre_coordinates(parsed):
    layer = parsed.boards[3].layers['Top Copper.GTL']
    paths = layer['follow_geometry']
    rf = next(path for path in paths if list(path.coords)[0] == pytest.approx((62.91599, 24.484)))
    assert list(rf.coords)[-1] == pytest.approx((56.7, 33.9))
    copper = unary_union(layer['solid_geometry'])
    assert copper.covers(Point(60, 28.8))  # 2.98mm RF route, not a 0.2794mm header value
    assert any(list(path.coords)[0] == pytest.approx((65.9, 24.7)) for path in paths)


def test_fidelity_diagnostics_are_visible_on_boards_and_result(parsed):
    assert parsed.warnings
    assert any('bitmap' in warning.lower() for warning in parsed.boards[3].warnings)
    assert any('layer' in warning.lower() for warning in parsed.boards[3].warnings)
    assert any('tail' in warning.lower() for warning in parsed.boards[2].warnings)
    assert all(any(warning in message for message in parsed.warnings)
               for board in parsed.boards for warning in board.warnings)


def test_unknown_framed_graphic_is_warned_without_losing_native_drills(tmp_path):
    def change(name, data):
        if name != 'BOARD4.LYT':
            return data
        header = struct.pack('<IBBI', 56, 1, 2, 32)
        return data.replace(header, struct.pack('<IBBI', 56, 99, 2, 32), 1)
    result = ProteusParser().parse_file(rewrite_project(tmp_path / 'unknown.pdsprj', change))
    board = result.boards[3]
    assert any('graphic kind 99' in warning for warning in board.warnings)
    assert sum(len(tool['drills']) for tool in board.drill_groups['PTH'].values()) == 124


def test_unknown_pad_span_is_not_labelled_manufacturing_ready(tmp_path):
    def change(name, data):
        if name != 'BOARD4.LYT':
            return data
        pad = struct.pack('<QHBii', 0x800000000000ffff, 22, 3, 7396000, 4844000)
        replacement = struct.pack('<QHBii', 0x1000000000000000, 22, 3, 7396000, 4844000)
        return data.replace(pad, replacement, 1)
    board = ProteusParser().parse_file(rewrite_project(tmp_path / 'span.pdsprj', change)).boards[3]
    previews = [name for name in board.layers if 'Pad span' in name]
    assert previews and not set(previews).intersection(board.default_layers)
    assert any('unverified' in name.lower() for name in board.drill_groups)
    assert any('span 0x1000000000000000' in warning for warning in board.warnings)


def island_project(path, extra_stack=(), graphics=()):
    def number(value):
        return struct.pack('<I', value)

    def text(value):
        encoded = value.encode('cp1252')
        return bytes([len(encoded)]) + encoded

    def ring(points):
        return number(len(points)) + b''.join(struct.pack('<ii', int(x * 100000), int(y * 100000))
                                             for x, y in points)

    outer = [(0, 0), (10, 0), (10, 10), (0, 10)]
    hole = [(2, 2), (8, 2), (8, 8), (2, 8)]
    island = [(4, 4), (6, 4), (6, 6), (4, 6)]
    editable = ring(outer + [outer[0]])
    editable = editable[:4] + struct.pack('<iiii', 0, 0, 1000000, 1000000) + bytes(2) + editable[4:] + bytes(10)
    board = b'PCB LAYOUT FILE\x1a' + bytes(116) + b'LAYOUT TECHNOLOGY DATA\x1a'
    stack = [(1, 0, 'Top Copper')] + list(extra_stack) + [(1, 15, 'Bottom Copper')]
    board += b'\0' + number(1) + bytes(1088) + text('FR4') + bytes(24) + number(len(stack))
    for kind, layer, name in stack:
        board += bytes([kind]) + text('Copper' if kind == 1 else 'Resist')
        board += number(1800) + bytes([layer]) + text(name) + bytes(8)
    board += number(0) + bytes(4)  # no spans, graphic styles or text styles
    board += b';PS\nPAD,CPAD,1mm,1mm,0,0,0,0,0,0\n*\n;TS\nDEFAULT,10th\nRELIEF,10th\n*\n'
    board += bytes(8) + b'\xfe\xff\0\xfe\xff\0' + bytes(7)
    board += b'\0\1\0' + number(len(editable) + 4) + editable
    board += text('GND') + text('DEFAULT') + text('RELIEF') + bytes(26) + number(2)
    board += ring(outer) + number(1) + ring(hole) + ring(island) + number(0)
    board += bytes(16)
    for layer in graphics:
        primitive = struct.pack('<IBBIBiIBIIBB', 48, 2, 2, 32, 0, 1000, 0, 0, 0, 0, 2, 127)
        primitive += b'DEFAULT\0' + struct.pack('<iii', 0, 0, 100000)
        board += b'\0\3' + struct.pack('<IIiiiI', layer, 0, 0, 0, 0, len(primitive) + 4) + primitive
    board += b'\0\xff' + bytes(4 + 64 * 4 + 8)
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('PROJECT.XML', '<PROJECT><TIMESTAMP RELEASE="8.16"/></PROJECT>')
        archive.writestr('BOARD1.LYT', board)
    return path


def test_saved_pour_island_inside_a_hole_is_not_flooded_or_erased(tmp_path):
    result = ProteusParser().parse_file(island_project(tmp_path / 'island.pdsprj')).boards[0]
    polygons = result.layers['Top Copper.GTL']['solid_geometry']
    copper = unary_union(polygons)
    assert len(polygons) == 2
    assert copper.area == pytest.approx(68)
    assert copper.covers(Point(1, 1))
    assert not copper.covers(Point(3, 3))
    assert copper.covers(Point(5, 5))


def test_identified_manufacturing_layers_are_default_but_unknown_graphics_are_not(tmp_path):
    # Native IDs/stack kinds carry identity; editable display labels do not.
    stack = ((0, 38, 'Front coating'), (1, 7, 'Internal signal'), (0, 39, 'Rear coating'))
    path = island_project(tmp_path / 'layers.pdsprj', extra_stack=stack,
                          graphics=(7, 38, 39, 59, 36, 37, 40, 41, 25))
    board = ProteusParser().parse_file(path).boards[0]
    assert {'Top Copper.GTL', 'Internal signal.G1', 'Front coating.GTS', 'Rear coating.GBS'} <= board.layers.keys()
    assert board.layers['Internal signal.G1']['name'] == 'Internal signal'
    assert board.default_layers[:2] == ['Top Copper.GTL', 'Internal signal.G1']
    expected = {'Front coating.GTS', 'Rear coating.GBS', 'Board Outline.GKO',
                'Top Silk Screen.GTO', 'Bottom Silk Screen.GBO', 'Top SMT Paste.GTP', 'Bottom SMT Paste.GBP'}
    assert expected <= set(board.default_layers)
    for name in expected:
        assert board.layers[name]['solid_geometry'][0].area == pytest.approx(Point(0, 0).buffer(1, quad_segs=32).area)
        assert board.layers[name]['name'] == name.rsplit('.', 1)[0]
    assert 'Layer 25 (unverified)' in board.layers
    assert 'Layer 25 (unverified)' not in board.default_layers


@pytest.mark.parametrize('span,kind,mask_extensions,paste_extension', [
    (0, 'RSMPAD', {'GTS'}, 'GTP'), (15, 'RSMPAD', {'GBS'}, 'GBP'),
    (0, 'CSMPAD', {'GTS'}, 'GTP'), (0x800000000000ffff, 'CPAD', {'GTS', 'GBS'}, None),
    (0x1000000000000000, 'RSMPAD', set(), None)])
def test_ordinary_native_pad_openings_follow_actual_side_and_radial_guard(span, kind, mask_extensions, paste_extension):
    from appParsers.ParseProteus8 import Proteus8Parser, _Reader

    board = Proteus8Parser()
    board._copper = [0, 15]
    board._remember_layer(0, 'Top Copper')
    board._remember_layer(15, 'Bottom Copper')
    board._pad_styles = [(['PAD', kind, '1mm', '2mm', '0', '5th', '0', '0', '0', '0'], [])]
    data = struct.pack('<QHBiihH', span, 0, 0, 1000000, 2000000, -900, 0) + bytes(15)
    board._pad(_Reader(data, 'pad.LYT'))
    board._finish()
    masks = {name.rsplit('.', 1)[1]: unary_union(layer['solid_geometry'])
             for name, layer in board.layers.items() if name.endswith(('.GTS', '.GBS'))}
    assert masks.keys() == mask_extensions
    for mask in masks.values():
        assert mask.bounds == pytest.approx((8.873, 19.373, 11.127, 20.627))
        assert mask.covers(Point(11.1, 20))
        if kind == 'RSMPAD':
            assert not mask.covers(Point(11.12, 20.62))  # rounded expansion, not a larger sharp box
    pastes = [name for name in board.layers if name.endswith(('.GTP', '.GBP'))]
    assert len(pastes) == (1 if paste_extension else 0)
    if paste_extension:
        assert pastes[0].endswith('.' + paste_extension)
        paste = unary_union(board.layers[pastes[0]]['solid_geometry'])
        assert paste.bounds == pytest.approx((9, 19.5, 11, 20.5))
        expected_area = 2 if kind == 'RSMPAD' else Point(0, 0).buffer(1, quad_segs=32).area / 2
        assert paste.area == pytest.approx(expected_area)


def test_custom_polygon_pad_is_not_guessed_as_paste():
    from appParsers.ParseProteus8 import Proteus8Parser, _Reader

    board = Proteus8Parser()
    board._copper = [0, 15]
    board._remember_layer(0, 'Top Copper')
    board._remember_layer(15, 'Bottom Copper')
    board._pad_styles = [(['ANTENNA', 'PSMPAD', '4', '0', '0', '0', '4', '0', '0'],
                          ['0,0', '1,0', '1,1', '0,1'])]
    data = struct.pack('<QHBiihH', 0, 0, 0, 0, 0, 0, 0) + bytes(15)
    board._pad(_Reader(data, 'pad.LYT'))
    board._finish()
    assert sum(poly.area for layer in board.layers.values() for poly in layer['solid_geometry']) == pytest.approx(1)
    assert not any(name.endswith(('.GTP', '.GBP', '.GTS', '.GBS')) for name in board.layers)


def test_native_wireless_openings_do_not_include_outline_or_custom_antenna(parsed):
    board = parsed.boards[3]
    mask = unary_union(board.layers['Top Resist.GTS']['solid_geometry'])
    bottom = unary_union(board.layers['Bottom Resist.GBS']['solid_geometry'])
    paste = unary_union(board.layers['Top SMT Paste.GTP']['solid_geometry'])
    assert mask.covers(Point(58.3, 12.5))
    assert not paste.covers(Point(58.3, 12.5))
    assert mask.covers(Point(71.42 + 1, 48.44))
    assert bottom.covers(Point(71.42 + 1, 48.44))
    assert paste.area == pytest.approx(10 * 1.016 * 1.27 + 2)
    assert not paste.covers(Point(98.2, 10))
    assert not mask.covers(Point(0, 0.27))
    assert not bottom.covers(Point(0, 0.27))
    assert unary_union(board.layers['Board Outline.GKO']['solid_geometry']).covers(Point(0, 0.27))


def test_duplicate_native_layer_names_do_not_merge_copper_identities(tmp_path):
    stack = ((1, 7, 'Top Copper'), (1, 3, 'Top Copper'))
    path = island_project(tmp_path / 'names.pdsprj', extra_stack=stack, graphics=(7, 3))
    board = ProteusParser().parse_file(path).boards[0]
    assert len(board.default_layers) == len(set(board.default_layers)) == 3
    assert {Path(name).suffix for name in board.default_layers} == {'.GTL', '.G1', '.G2'}
    assert all(board.layers[name]['name'] == 'Top Copper' for name in board.default_layers)
    assert board.layers['Top Copper.GTL']['solid_geometry'][0].area == pytest.approx(64)


def test_actual_version_nine_project_uses_its_native_schema():
    result = ProteusParser().parse_file(PROJECT9)
    assert result.major_version == result.detected_major_version == 9
    assert len(result.boards) == 1
    board = result.boards[0]
    assert board.member_name == 'ROOT.LYT'
    assert board.name == 'ROOT'  # don't promote the arbitrary "power supply to 5v" annotation to a board name
    assert {'Top Copper.GTL', 'Bottom Copper.GBL'} <= board.layers.keys()
    assert sum(len(tool['drills']) for group in board.drill_groups.values() for tool in group.values()) == 27
    assert {round(tool['tooldia'], 6): len(tool['drills']) for tool in board.drill_groups['PTH'].values()} == {
        0.762: 6, 1.016: 17}
    assert sum(len(tool['drills']) for name, group in board.drill_groups.items()
               if 'Unverified' in name for tool in group.values()) == 4
    assert sum(len(board.layers[name]['follow_geometry'])
               for name in ('Top Copper.GTL', 'Bottom Copper.GBL')) == 20
    assert any('907' in warning for warning in result.warnings)
    assert not any('fallback' in warning.lower() for warning in result.warnings)
    assert board.warnings and all(any(warning in message for message in result.warnings) for warning in board.warnings)


@pytest.mark.parametrize('label, extension', [('C1', '.GTO'), ('R1', '.GBO')])
def test_native_reference_text_changes_silkscreen_not_copper(tmp_path, label, extension):
    path = tmp_path / 'reference.pdsprj'
    original = ProteusParser().parse_file(PROJECT9).boards[0]
    with zipfile.ZipFile(PROJECT9) as source, zipfile.ZipFile(path, 'w') as target:
        for item in source.infolist():
            data = source.read(item)
            if item.filename == 'ROOT.LYT':
                # Change only the native reference, keeping its saved placement and font.
                reference = b'\xff' + struct.pack('<I', 2) + label.encode()
                assert data.count(reference) == 1
                data = data.replace(reference, reference[:-1] + b'9', 1)
            target.writestr(item.filename, data)
    changed = ProteusParser().parse_file(path).boards[0]
    different = []
    for name in original.layers.keys() | changed.layers.keys():
        before = unary_union(original.layers.get(name, {}).get('solid_geometry', []))
        after = unary_union(changed.layers.get(name, {}).get('solid_geometry', []))
        if not before.equals(after):
            different.append(name)
    # Equal-length text must produce different glyphs, not a substituted text box.
    assert len(different) == 1
    assert different[0].endswith(extension)
    assert different[0] in changed.default_layers


def test_native_capacitor_curved_outline_is_on_top_silk():
    board = ProteusParser().parse_file(PROJECT9).boards[0]
    silk = unary_union(board.layers['Top Silk Screen.GTO']['solid_geometry'])
    # C2's four native cubic segments form an oval, not a filled pad or a rectangle.
    assert silk.covers(Point(-98.81, 26.27))
    assert silk.covers(Point(-98.81, 23.73))
    assert silk.covers(Point(-101.35, 25))
    assert not silk.covers(Point(-98.81, 25))


@pytest.mark.parametrize('damage', ['truncated', 'string_length'])
def test_actual_version_nine_corruption_fails_without_partial_boards(tmp_path, damage):
    path = tmp_path / 'bad9.pdsprj'
    with zipfile.ZipFile(PROJECT9) as source, zipfile.ZipFile(path, 'w') as target:
        for item in source.infolist():
            data = source.read(item)
            if item.filename == 'ROOT.LYT':
                if damage == 'truncated':
                    data = data[:-1]
                else:
                    data = data.replace(b'\x03\0FR4', b'\xff\xffFR4', 1)
            target.writestr(item.filename, data)
    parser = ProteusParser()
    with pytest.raises(ProteusParseError, match='ROOT.LYT'):
        parser.parse_file(path)
    assert parser.boards == []


def test_version_nine_fallback_is_explicit(tmp_path):
    path = rewrite_project(tmp_path / 'nine.pdsprj', lambda name, data:
                           data.replace(b'RELEASE="816"', b'RELEASE="916"')
                           if name == 'PROJECT.XML' else data)
    result = ProteusParser().parse_file(path)
    assert result.major_version == 9
    assert len(result.boards) == 4
    assert any('9' in text and '8' in text and 'fallback' in text.lower() for text in result.warnings)


def test_variable_length_technology_and_bitmap_do_not_shift_decoding(tmp_path):
    def change(name, data):
        if not name.endswith('.LYT'):
            return data
        # Add an unused valid style; all later declared records move, existing ordinals don't.
        data = data.replace(b'*\n;TS\n', b'EXTRA,CPAD,1mm,1mm,0,0,0,0,0,0\n*\n;TS\n', 1)
        # Replace the native 273x273 DIB with a 1x1 DIB, changing its declared byte count.
        dib = struct.pack('<IiiHHIIiiII', 40, 1, 1, 1, 1, 0, 4, 2835, 2835, 2, 2)
        dib += bytes(4) + b'\xff\xff\xff\x00' + bytes(4)
        start = data.index(struct.pack('<IiiHH', 40, 273, 273, 1, 1))
        size = struct.unpack_from('<I', data, start - 4)[0]
        data = data[:start - 4] + struct.pack('<I', len(dib)) + dib + data[start + size:]
        return data
    result = ProteusParser().parse_file(rewrite_project(tmp_path / 'shifted.pdsprj', change))
    assert result.boards[3].name == 'PCB3-Wireless'
    assert sum(len(tool['drills']) for tool in result.boards[3].drill_groups['PTH'].values()) == 124


@pytest.mark.parametrize('damage', ['truncated', 'bad_signature', 'bad_extent'])
def test_damaged_board_fails_atomically(tmp_path, damage):
    def change(name, data):
        if name != 'BOARD4.LYT':
            return data
        if damage == 'truncated':
            return data[:-1]
        if damage == 'bad_signature':
            return b'NOT A PCB' + data[9:]
        # Corrupt a declared library extent, not an incidental coordinate byte.
        marker = data.index(b'\x04' + b'0805')
        offset = marker + 1 + 4 + 4
        return data[:offset] + struct.pack('<I', 0xffffffff) + data[offset + 4:]
    parser = ProteusParser()
    if damage == 'truncated':
        parser.parse_file(PROJECT)
    with pytest.raises(ProteusParseError, match='BOARD4.LYT'):
        parser.parse_file(rewrite_project(tmp_path / 'bad.pdsprj', change))
    assert parser.boards == []


def test_invalid_archive_and_unsupported_version_fail(tmp_path):
    path = tmp_path / 'invalid.pdsprj'
    path.write_bytes(b'not a zip archive')
    with pytest.raises(ProteusParseError):
        ProteusParser().parse_file(path)
    path = rewrite_project(tmp_path / 'future.pdsprj', lambda name, data:
                           data.replace(b'RELEASE="816"', b'RELEASE="1016"')
                           if name == 'PROJECT.XML' else data)
    with pytest.raises(ProteusParseError, match='version'):
        ProteusParser().parse_file(path)


@pytest.mark.parametrize('project', [PROJECT, PROJECT9], ids=['proteus8', 'proteus9'])
def test_native_tools_survive_existing_exports_and_reparse(parsed, project):
    from types import SimpleNamespace
    from typing import cast
    from unittest.mock import Mock

    from appObjects.GerberObject import GerberObject
    from appObjects.ExcellonObject import ExcellonObject
    from appParsers.ParseGerber import Gerber
    from appParsers.ParseExcellon import Excellon
    from defaults import AppDefaults

    app = SimpleNamespace(log=Mock(), inform=Mock(), abort_flag=False, decimals=5, app_units='MM',
                          plotcanvas=Mock(), options=dict(AppDefaults().defaults))
    board = parsed.boards[3] if project == PROJECT else ProteusParser().parse_file(project).boards[0]
    for name in board.default_layers:
        layer = board.layers[name]
        obj = SimpleNamespace(app=app, tools=layer['tools'])
        body = GerberObject.export_gerber(cast(GerberObject, obj), 3, 5)
        assert body and body != 'fail'
        code = '%FSLAX35Y35*%\n%MOMM*%\n' + body + 'M02*\n'
        gerber = Gerber(app)
        assert gerber.parse_lines(code.splitlines()) != 'fail'
        original = unary_union(layer['solid_geometry'])
        result = unary_union(gerber.solid_geometry)
        assert original.symmetric_difference(result).area < 0.02
    total = 0
    for tools in board.drill_groups.values():
        obj = SimpleNamespace(app=app, tools=tools)
        has_slots, body = ExcellonObject.export_excellon(cast(ExcellonObject, obj), 3, 5)
        assert not has_slots
        definitions = '\n'.join('T%02dC%.6f' % (number, tool['tooldia']) for number, tool in tools.items())
        code = 'M48\nMETRIC,TZ\n' + definitions + '\n%\n' + body + 'M30\n'
        excellon = Excellon(app)
        assert excellon.parse_lines(code.splitlines()) != 'fail'
        reimported_tools = cast(dict, excellon.tools)
        expected = sorted((round(tool['tooldia'], 6), round(point.x, 5), round(point.y, 5))
                          for tool in tools.values() for point in tool['drills'])
        actual = sorted((round(tool['tooldia'], 6), round(point.x, 5), round(point.y, 5))
                        for tool in reimported_tools.values() for point in tool['drills'])
        assert actual == expected
        total += len(actual)
    assert total == (128 if project == PROJECT else 27)
