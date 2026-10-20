import struct

import pytest

from appPlugins.Common.ecut import ecut_protocol as p


def test_crc_vectors():
    assert p.ecut_crc60(bytes(60)) == 0x37DB79C2
    assert p.ecut_crc60(bytes(range(60))) == 0x981F1FA6
    assert p.ecut_crc60(b'\xff' * 60) == 0x0A4B5383
    assert p.ecut_crc60(b'123456789' + bytes(51)) == 0xA8AA2C92


def test_crc_rejects_wrong_length():
    with pytest.raises(ValueError):
        p.ecut_crc60(bytes(59))


def _rx_report(subtype=2):
    body = bytearray(60)
    struct.pack_into('>6I', body, 0, 1, 2, 3, 4, 5, 6)
    struct.pack_into('>3H', body, 28, 0, 0x00FF, 0x0008)
    body[40] = subtype
    struct.pack_into('>H', body, 41, 0x1234)
    return b'\x00' + bytes(body) + struct.pack('>I', p.ecut_crc60(bytes(body)))


def test_rx_decode_round_trip():
    f = p.decode_rx_report(_rx_report())
    assert f.crc_valid
    assert f.axis_positions == (1, 2, 3, 4, 5, 6)
    assert f.inputs_0_15 == 0x00FF
    assert f.estop_active
    assert f.subtype == 2 and f.subtype_values == (0x1234,)


def test_rx_bad_crc_flagged():
    r = bytearray(_rx_report())
    r[10] ^= 0xFF
    assert not p.decode_rx_report(bytes(r)).crc_valid


def test_rx_wrong_size():
    with pytest.raises(ValueError):
        p.decode_rx_report(bytes(64))


def test_tx_packet_framing():
    pkt = p.build_tx_packet(p.Cmd.STOP, b'\x00\x00\x03\xe8')
    assert len(pkt) == p.REPORT_SIZE
    assert pkt[:6] == bytes([0, p.Cmd.STOP, 0, 0, 3, 0xE8])
    assert pkt[6:] == bytes(p.REPORT_SIZE - 6)


def test_tx_params_limit():
    assert p.MAX_TX_PARAMS_SIZE == 63
    pkt = p.build_tx_packet(0x10, b'\x07' * p.MAX_TX_PARAMS_SIZE)
    assert pkt[2:] == b'\x07' * 63
    with pytest.raises(ValueError):
        p.build_tx_packet(0x10, bytes(p.MAX_TX_PARAMS_SIZE + 1))
    with pytest.raises(ValueError):
        p.build_tx_packet(0x10, bytes(430))
    with pytest.raises(ValueError):
        p.build_tx_packet(0x100)


def _recs(n):
    return [p.encode_motion_record(i + 1, (i, -i, 2 * i, 0, 0, 0)) for i in range(n)]


def test_motion_limit_and_no_truncation():
    assert p.MAX_MOTION_RECORDS_PER_PACKET == 4
    recs = _recs(4)
    pkt = p.build_motion_packet(recs)
    assert len(pkt) == p.REPORT_SIZE
    assert pkt[0] == 0
    assert pkt[1:] == b''.join(recs)  # 4th record fully present, no cmd byte, no crc
    assert pkt[49:65] == recs[3]


def test_motion_partial_batch_padded():
    recs = _recs(2)
    pkt = p.build_motion_packet(recs)
    assert pkt[1:33] == b''.join(recs)
    assert pkt[33:] == bytes(32)


def test_motion_batch_rejections():
    with pytest.raises(ValueError):
        p.build_motion_packet([])
    with pytest.raises(ValueError):
        p.build_motion_packet(_recs(5))
    with pytest.raises(ValueError):
        p.build_motion_packet([b'\x69' * 15])
    with pytest.raises(ValueError):
        p.build_motion_packet([b'\x69' * 17])
    with pytest.raises(ValueError):
        p.build_motion_packet([b'\x00' * 16])


def test_record_encoding():
    r = p.encode_motion_record(0x010203, (1, -1, 32767, -32768, 0, 5))
    assert r[0] == 0x69 and r[1:4] == b'\x01\x02\x03'
    assert struct.unpack('>6h', r[4:]) == (1, -1, 32767, -32768, 0, 5)
    assert len(r) == 16


@pytest.mark.parametrize('axes', [
    (32768, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, -32769), (0, 0, 0), (0,) * 7])
def test_record_axis_range(axes):
    with pytest.raises(ValueError):
        p.encode_motion_record(1, axes)


@pytest.mark.parametrize('tid', [-1, 0x1000000])
def test_record_trajectory_range(tid):
    with pytest.raises(ValueError):
        p.encode_motion_record(tid, (0,) * 6)


def test_record_trajectory_bounds_ok():
    assert p.encode_motion_record(0, (0,) * 6)[1:4] == b'\0\0\0'
    assert p.encode_motion_record(0xFFFFFF, (0,) * 6)[1:4] == b'\xff\xff\xff'
