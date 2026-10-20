import pytest

from appPlugins.Common.ecut import ecut_protocol as p


def test_axis_config_matches_captured_800_step_64x_profile():
    packet = p.build_axis_config_packet([800] * 6, 100, 64, [0] * 6)
    assert packet == bytes.fromhex(
        '00 9f 00000000 '
        '00000320 00000320 00000320 00000320 00000320 00000320 '
        '00000000 0064 03f0801f '
        '00000000 00000000 00000000 00000000 00000000 00000000 00')


def test_axis_config_encodes_signed_offsets_and_smallest_smoothing():
    packet = p.build_axis_config_packet([1, 2, 3, 4, 5, 6], 65535, 2,
                                        [-1, -2147483648, 2147483647, 0, 1, 2])
    assert packet[34:40] == bytes.fromhex('ffff 00100400')
    assert packet[40:64] == bytes.fromhex(
        'ffffffff 80000000 7fffffff 00000000 00000001 00000002')
    assert len(packet) == 65 and packet[64] == 0


def test_pin_config_reverses_channel_pairs_and_packs_seventh_axis_separately():
    settings = [(1, 2, 3, 4, True, False, True)] + [(0,) * 7] * 5
    settings.append((7, 8, 9, 10, False, True, True))
    packet = p.build_pin_config_packet(list(range(8)), list(range(10, 18)), settings)
    assert packet[:6] == bytes.fromhex('00 cd 00000000')
    assert packet[6:22] == bytes.fromhex('0b010a00 0d030c02 0f050e04 11071006')
    assert packet[22:36] == bytes(14)
    assert packet[36:44] == bytes.fromhex('18a90807 14430201')
    assert packet[44:] == bytes(21)


def test_input_config_preserves_shared_pins_and_native_duplicate_bitmap():
    signals = [(i in (0, 20, 21, 31), i, i in (1, 20, 31)) for i in range(32)]
    packet = p.build_input_config_packet(signals, 0x1234)
    assert packet[:6] == bytes.fromhex('00 a2 00000000')
    assert packet[6:22] == bytes.fromhex('80300001 00100001 80100002 00100002')
    assert packet[22:30] == bytes.fromhex('1b1a1918 1f1e1d1c')
    assert packet[30:40] == bytes.fromhex('00000000 1234 00000000')
    assert packet[40:64] == bytes.fromhex(
        '03020100 07060504 0b0a0908 0f0e0d0c 13121110 17161514')
    assert packet[64] == 0
    shared = p.build_input_config_packet([(True, 4, True)] * 32, 0)
    assert shared[40:64] == bytes([4]) * 24


@pytest.mark.parametrize('builder,first,second,want', [
    ('build_motion_limits_packet', [0, 1, 2, 3, 4, 4294967295], [6, 7, 8, 9, 10, 11],
     '4b 00000000 00000000 00000001 00000002 00000003 00000004 ffffffff'),
    ('build_soft_limits_packet', [0, -1, 2, 3, 4, 2147483647], [-2147483648, 7, 8, 9, 10, 11],
     'b5 00000000 00000000 ffffffff 00000002 00000003 00000004 7fffffff'),
])
def test_limits_keep_axis_arrays_separated(builder, first, second, want):
    packet = getattr(p, builder)(first, second)
    assert packet[1:30] == bytes.fromhex(want)
    assert packet[30:40] == bytes(10)
    assert packet[40:44] == bytes.fromhex('00000006' if builder.endswith('motion_limits_packet') else '80000000')
    assert packet[44:64] == bytes.fromhex('00000007 00000008 00000009 0000000a 0000000b')
    assert len(packet) == 65 and packet[64] == 0


@pytest.mark.parametrize('opcode,axis_code,flags', [(0xae, 7, 0), (0xa6, 2, 0x5555), (0xb4, 5, 0x5554)])
def test_target_packets_use_low_word_first_for_both_axis_groups(opcode, axis_code, flags):
    packet = p.build_target_packet(opcode, [0x1122334455667788, -1, -9223372036854775808,
                                          9223372036854775807, 65536, -65536], axis_code, flags)
    assert packet[:6] == bytes([0, opcode, 0, 0, 0, 0])
    assert packet[6:30] == bytes.fromhex('55667788 11223344 ffffffff ffffffff 00000000 80000000')
    assert packet[30:34] == bytes(4)
    assert packet[34:40] == axis_code.to_bytes(2, 'big') + flags.to_bytes(4, 'big')
    assert packet[40:64] == bytes.fromhex('ffffffff 7fffffff 00010000 00000000 ffff0000 ffffffff')
    assert packet[64] == 0


@pytest.mark.parametrize('builder,args', [
    ('build_axis_config_packet', ([800] * 5, 100, 64, [0] * 6)),
    ('build_axis_config_packet', ([800] * 6, -1, 64, [0] * 6)),
    ('build_axis_config_packet', ([800] * 6, 100, 3, [0] * 6)),
    ('build_axis_config_packet', ([800] * 6, 100, 64, [2147483648] * 6)),
    ('build_axis_config_packet', ([800.0] * 6, 100, 64, [0] * 6)),
    ('build_pin_config_packet', ([64] * 8, [0] * 8, [(0,) * 7] * 7)),
    ('build_pin_config_packet', ([0] * 8, [0] * 8, [(0, 0, 16, 0, 0, 0, 0)] * 7)),
    ('build_pin_config_packet', ([0] * 8, [0] * 8, [(0, 0, 0, 64, 0, 0, 0)] * 7)),
    ('build_pin_config_packet', ([0] * 8, [0] * 8, [(0, 0, 0, 0, 2, 0, 0)] * 7)),
    ('build_input_config_packet', ([(False, -1, False)] * 32, 0)),
    ('build_input_config_packet', ([(False, 0, False)] * 31, 0)),
    ('build_input_config_packet', ([(False, 0, False)] * 32, 65536)),
    ('build_motion_limits_packet', ([-1] * 6, [0] * 6)),
    ('build_motion_limits_packet', ([4294967296] * 6, [0] * 6)),
    ('build_soft_limits_packet', ([0] * 6, [-2147483649] * 6)),
    ('build_target_packet', (0xaf, [0] * 6, 0, 0)),
    ('build_target_packet', (0xae, [9223372036854775808] * 6, 7, 0)),
    ('build_target_packet', (0xae, [0] * 6, -1, 0)),
    ('build_target_packet', (0xae, [0] * 6, 7, 4294967296)),
])
def test_builders_refuse_malformed_or_out_of_range_values(builder, args):
    with pytest.raises(ValueError):
        getattr(p, builder)(*args)
