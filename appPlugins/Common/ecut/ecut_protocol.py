# ##########################################################
# FlatCAM Evo: E-Cut USB HID Motion Controller Protocol    #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     10/19/2026                                     #
# License:  MIT Licence                                    #
# ##########################################################
"""E-Cut HID protocol verified against USB captures 01..06, firmware 2.4.8.288.

Windows writes: zero report ID plus 64 wire bytes. hidapi reads may omit the ID.
IN: six signed big-endian positions, trajectory, outputs, inputs, status,
10 kHz counter, free FIFO units, subtype data, custom CRC over 60 bytes.
OUT: ordinary opcode reports or four 16-byte 0x69 motion records; no TX CRC.
Each motion record spans 1 ms. E5 is an empty end-of-stream compatibility
marker; finite motion completion does not depend on it on the tested board.
See docs/mach3/AF_E5_FINDINGS.txt and PROTOCOL_REPORT.txt for evidence.
"""
from __future__ import annotations

import struct
import logging
import errno
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

log = logging.getLogger(__name__)

VID = 0x0483
PID = 0x5750

REPORT_SIZE = 65
PAYLOAD_SIZE = 64
CRC_DATA_SIZE = 60
MOTION_RECORD_SIZE = 16
MOTION_RECORDS_PER_PAYLOAD = 4
MOTION_PAYLOAD_SIZE = 64
# Motion report = [report id][4 x 16-byte records], no command byte, no CRC (see note above).
MAX_MOTION_RECORDS_PER_PACKET = MOTION_PAYLOAD_SIZE // MOTION_RECORD_SIZE
# Command report = [report id][cmd][params], zero padded, no CRC.
MAX_TX_PARAMS_SIZE = PAYLOAD_SIZE - 1

POLY = 0x04C11DB7


def _build_crc_table() -> tuple[int, ...]:
    result = []
    for b in range(256):
        x = b << 24
        for _ in range(8):
            x = ((x << 1) ^ (POLY if x & 0x80000000 else 0)) & 0xFFFFFFFF
        result.append(x)
    return tuple(result)


CRC_TABLE = _build_crc_table()


def ecut_crc60(payload: bytes) -> int:
    if len(payload) != CRC_DATA_SIZE:
        raise ValueError(f'Expected {CRC_DATA_SIZE} bytes, got {len(payload)}')
    crc = 0xFFFFFFFF
    for b in payload:
        crc ^= b
        for _ in range(4):
            crc = ((crc << 8) & 0xFFFFFFFF) ^ CRC_TABLE[crc >> 24]
    return crc


class Cmd(IntEnum):
    STOP = 0xC8
    ESTOP = 0xC8  # software stop, not a verified physical safety interlock
    CONFIG = 0xCA
    SET_POSITION = 0xA0
    MPG_CONFIG = 0x9B
    AXIS_ENABLE = 0x9B  # compatibility alias; native builder also configures MPG
    AXIS_CONFIG = 0x9F
    IO_CONFIG = 0xA2
    PIN_CONFIG = 0xCD
    MODE = 0x1A
    SET_OUTPUTS = 0xAF
    END_STREAM = 0xE5
    MOTION_LIMITS = 0x4B
    SOFT_LIMITS = 0xB5
    PROBE = 0xAE
    HOME = 0xA6
    JOG_ON = 0xB4
    JOG_OFF = 0xC9
    PROBE_FINISH = 0xAC
    SPINDLE = 0xB0


class RxSubtype(IntEnum):
    POSITION = 0
    AUX_8H = 1
    SINGLE_H = 2
    HI = 3
    EXPAND_IO = 4
    IIIH = 5


SUBTYPE_FORMATS = {
    0: '>HHIHHHH',
    1: '>8H',
    2: '>H',
    3: '>HI',
    4: '>5H',
    5: '>IIIH',
}

AXIS_NAMES = ('X', 'Y', 'Z', 'A', 'B', 'C')

INTERPOLATION_FACTORS = (2, 4, 8, 16, 32, 64, 128, 256, 512, 1024)


@dataclass(frozen=True)
class EcutRxFrame:
    report_id: int
    axis_positions: tuple[int, ...]
    aux_u32: int
    field_778: int
    inputs_0_15: int
    status: int
    field_78c: int
    field_790: int
    subtype: int
    subtype_values: tuple[int, ...]
    crc_wire: int
    crc_valid: bool

    @property
    def configured(self) -> bool:
        return bool(self.status & 0x0001)

    @property
    def motion_busy(self) -> bool:
        return bool(self.status & 0x0080)

    @property
    def outputs(self) -> int:
        return self.field_778

    @property
    def fifo_free(self) -> int:
        """Firmware units; this is not a count of motion record slots."""
        return self.field_790

    @property
    def estop_active(self) -> bool:
        # e-Cut.dll 0x10017FF7..0x1001803D: status bit 0x0008 puts Mach3 in its stop state and sends c8.
        # The host does the same. No capture shows the bit set, so its electrical cause is unknown.
        return bool(self.status & 0x0008)

    @property
    def input_bits(self) -> tuple[bool, ...]:
        return tuple(bool(self.inputs_0_15 & (1 << b)) for b in range(16))


def decode_rx_report(report: bytes) -> EcutRxFrame:
    if len(report) != REPORT_SIZE:
        raise ValueError(f'Expected {REPORT_SIZE}-byte report, got {len(report)}')
    crc_wire, = struct.unpack_from('>I', report, 61)
    crc_calc = ecut_crc60(report[1:61])
    axes = struct.unpack_from('>6i', report, 1)
    aux, = struct.unpack_from('>I', report, 25)
    f778, inputs, status = struct.unpack_from('>3H', report, 29)
    f78c, = struct.unpack_from('>I', report, 35)
    f790, = struct.unpack_from('>H', report, 39)
    subtype = report[41]
    fmt = SUBTYPE_FORMATS.get(subtype)
    if fmt is None:
        vals = ()
    else:
        vals = struct.unpack_from(fmt, report, 42)
    return EcutRxFrame(
        report_id=report[0],
        axis_positions=axes,
        aux_u32=aux,
        field_778=f778,
        inputs_0_15=inputs,
        status=status,
        field_78c=f78c,
        field_790=f790,
        subtype=subtype,
        subtype_values=vals,
        crc_wire=crc_wire,
        crc_valid=(crc_calc == crc_wire),
    )


def encode_motion_record(trajectory_id: int, axes: tuple[int, ...]) -> bytes:
    if not (0 <= trajectory_id <= 0xFFFFFF):
        raise ValueError('trajectory_id must fit in 24 bits')
    if len(axes) != 6 or any(not (-32768 <= v <= 32767) for v in axes):
        raise ValueError('Expected 6 signed 16-bit axis values')
    return bytes([0x69]) + (trajectory_id & 0xFFFFFF).to_bytes(3, 'big') + struct.pack('>6h', *axes)


def pack_motion_payload(records: list[bytes]) -> bytes:
    if len(records) > MOTION_RECORDS_PER_PAYLOAD:
        raise ValueError(f'Max {MOTION_RECORDS_PER_PAYLOAD} records per payload')
    for r in records:
        if len(r) != MOTION_RECORD_SIZE or r[0] != 0x69:
            raise ValueError('Each record must be 16 bytes starting with 0x69')
    return b''.join(records).ljust(MOTION_PAYLOAD_SIZE, b'\0')


def build_tx_packet(cmd: int, params: bytes = b'') -> bytes:
    """[report id 0][cmd][params...] zero padded to REPORT_SIZE. No CRC (none on the TX path)."""
    if not (0 <= cmd <= 0xFF):
        raise ValueError('cmd must fit in one byte')
    if len(params) > MAX_TX_PARAMS_SIZE:
        raise ValueError(f'params too large: {len(params)} > {MAX_TX_PARAMS_SIZE} bytes')
    return (bytes([0, cmd]) + bytes(params)).ljust(REPORT_SIZE, b'\0')


def _packet_int(value: int, low: int, high: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise ValueError(f'{name} must be an integer in {low}..{high}')
    return value


def _packet_values(values, count: int, low: int, high: int, name: str) -> tuple[int, ...]:
    if len(values) != count:
        raise ValueError(f'{name} requires {count} values')
    return tuple(_packet_int(value, low, high, name) for value in values)


def _packet_flag(value, name: str) -> int:
    if not isinstance(value, (bool, int)) or value not in (0, 1):
        raise ValueError(f'{name} must be boolean or 0/1')
    return int(value)


def build_spindle_pwm_packet(period_counts: int, duty_counts: int) -> bytes:
    """B0 PWM/DAC mode; raw timer counts, with step-drive fields zero."""
    _packet_int(period_counts, 1, 0xffff, 'period_counts')
    _packet_int(duty_counts, 0, period_counts, 'duty_counts')
    packet = bytearray(build_tx_packet(Cmd.SPINDLE))
    struct.pack_into('>I', packet, 2, 1)
    struct.pack_into('>I', packet, 30, period_counts)
    struct.pack_into('>H', packet, 34, duty_counts)
    return bytes(packet)


def build_axis_config_packet(steps_per_unit, delay_us: int, smoothing: int,
                             work_offset_steps) -> bytes:
    """9F calibration and offsets, matching native FUN_100246f0/10024500."""
    steps = _packet_values(steps_per_unit, 6, -0x80000000, 0x7fffffff, 'steps_per_unit')
    offsets = _packet_values(work_offset_steps, 6, -0x80000000, 0x7fffffff, 'work_offset_steps')
    _packet_int(delay_us, 0, 0xffff, 'delay_us')
    _packet_int(smoothing, 2, 1024, 'smoothing')
    if smoothing not in INTERPOLATION_FACTORS:
        raise ValueError('smoothing must be a supported interpolation factor')
    packet = bytearray(build_tx_packet(Cmd.AXIS_CONFIG))
    struct.pack_into('>6i', packet, 6, *steps)
    struct.pack_into('>HI', packet, 34, delay_us,
                     (smoothing // 2) * 0x401 - 1 + (smoothing - 1) * 0x100000)
    struct.pack_into('>6i', packet, 40, *offsets)
    return bytes(packet)


def build_pin_config_packet(step_functions, dir_functions, axis_settings) -> bytes:
    """CD channel functions and seven axis pin words (FUN_10024180)."""
    steps = _packet_values(step_functions, 8, 0, 63, 'step_functions')
    dirs = _packet_values(dir_functions, 8, 0, 63, 'dir_functions')
    if len(axis_settings) != 7:
        raise ValueError('axis_settings requires seven axes')
    words = []
    for settings in axis_settings:
        if len(settings) != 7:
            raise ValueError('axis settings require pin, port, polarity and enabled values')
        sp, dp, sport, dport, slow, dlow, enabled = settings
        sp = _packet_int(sp, 0, 255, 'step_pin')
        dp = _packet_int(dp, 0, 255, 'dir_pin')
        sport = _packet_int(sport, 0, 15, 'step_port')
        dport = _packet_int(dport, 0, 63, 'dir_port')
        words.append(sp + (dp << 8) + (sport << 16) + (dport << 20)
                     + (_packet_flag(slow, 'step_low') << 26)
                     + (_packet_flag(dlow, 'dir_low') << 27)
                     + (_packet_flag(enabled, 'enabled') << 28))
    packet = bytearray(build_tx_packet(Cmd.PIN_CONFIG))
    for i in range(0, 8, 2):
        packet[6 + i * 2:10 + i * 2] = bytes((dirs[i + 1], steps[i + 1], dirs[i], steps[i]))
    struct.pack_into('>I', packet, 36, words[6])
    struct.pack_into('>6I', packet, 40, *words[:6])
    return bytes(packet)


def build_input_config_packet(signals, axis_flags: int) -> bytes:
    """A2 native 32 logical input mappings; shared physical pins are allowed."""
    if len(signals) != 32:
        raise ValueError('signals requires 32 logical inputs')
    _packet_int(axis_flags, 0, 0xffff, 'axis_flags')
    enabled = polarity = 0
    pins = []
    for i, signal in enumerate(signals):
        if len(signal) != 3:
            raise ValueError('Each input requires enabled, pin and active_low')
        on, pin, active_low = signal
        enabled |= _packet_flag(on, 'enabled') << i
        polarity |= _packet_flag(active_low, 'active_low') << i
        pins.append(_packet_int(pin, 0, 255, 'input pin'))
    packet = bytearray(build_tx_packet(Cmd.IO_CONFIG))
    # The native loops duplicate the first 21 enabled/polarity bits separately.
    struct.pack_into('>4I', packet, 6, enabled, enabled & 0x1fffff,
                     polarity, polarity & 0x1fffff)
    struct.pack_into('>H', packet, 34, axis_flags)
    for i in range(0, 32, 4):
        offset = 40 + i if i < 24 else 22 + i - 24
        packet[offset:offset + 4] = bytes(reversed(pins[i:i + 4]))
    return bytes(packet)


def build_motion_limits_packet(accel, velocity) -> bytes:
    """4B raw unsigned acceleration/velocity arrays; caller supplies firmware units."""
    accel = _packet_values(accel, 6, 0, 0xffffffff, 'accel')
    velocity = _packet_values(velocity, 6, 0, 0xffffffff, 'velocity')
    packet = bytearray(build_tx_packet(Cmd.MOTION_LIMITS))
    struct.pack_into('>6I', packet, 6, *accel)
    struct.pack_into('>6I', packet, 40, *velocity)
    return bytes(packet)


def build_soft_limits_packet(maximum, minimum) -> bytes:
    """B5 signed raw maximum/minimum arrays (FUN_100244b0)."""
    maximum = _packet_values(maximum, 6, -0x80000000, 0x7fffffff, 'maximum')
    minimum = _packet_values(minimum, 6, -0x80000000, 0x7fffffff, 'minimum')
    packet = bytearray(build_tx_packet(Cmd.SOFT_LIMITS))
    struct.pack_into('>6i', packet, 6, *maximum)
    struct.pack_into('>6i', packet, 40, *minimum)
    return bytes(packet)


def build_target_packet(opcode: int, targets_q16, axis_code: int, flags: int) -> bytes:
    """AE/A6/B4 Q16 target words: low32 first, each word big-endian."""
    if opcode not in (Cmd.PROBE, Cmd.HOME, Cmd.JOG_ON):
        raise ValueError('target opcode must be PROBE, HOME or JOG_ON')
    targets = _packet_values(targets_q16, 6, -0x8000000000000000, 0x7fffffffffffffff, 'targets_q16')
    _packet_int(axis_code, 0, 0xffff, 'axis_code')
    _packet_int(flags, 0, 0xffffffff, 'flags')
    packet = bytearray(build_tx_packet(opcode))
    struct.pack_into('>HI', packet, 34, axis_code, flags)
    for i, target in enumerate(targets):
        offset = 6 + i * 8 if i < 3 else 40 + (i - 3) * 8
        struct.pack_into('>II', packet, offset, target & 0xffffffff, (target >> 32) & 0xffffffff)
    return bytes(packet)


def build_motion_packet(records: list[bytes]) -> bytes:
    """[report id 0][up to 4 x 16-byte records], zero padded. No command byte, no CRC."""
    if not records:
        raise ValueError('at least one motion record is required')
    if len(records) > MAX_MOTION_RECORDS_PER_PACKET:
        raise ValueError(f'Max {MAX_MOTION_RECORDS_PER_PACKET} records per packet')
    return bytes([0]) + pack_motion_payload(records)


class EcutError(Exception):
    """Base error of the package: refusals, unverified features, failed transport."""


def find_boards(vid: int = VID, pid: int = PID) -> list:
    """List the E-Cut boards on the USB bus (no device is opened).

    :return: a list of dicts from hid.enumerate(), at least with 'serial_number' and 'path'
    :raises EcutUsbError: if hidapi is not installed
    """
    try:
        import hid
    except ImportError:
        raise EcutUsbError('hidapi is not installed')
    return [dict(info) for info in hid.enumerate(vid, pid)]


class EcutUsbError(EcutError):
    pass


class EcutUsb:
    """Minimal USB HID transport for the E-Cut motion controller.

    ponytail: no reconnect, no thread, no safety interlocks.
    Caller owns threading and E-stop supervision.
    """

    _READ_ATTEMPTS = 3
    _READ_RECOVERY_SECONDS = 0.05
    _READ_RETRY_DELAY = 0.005

    def __init__(self, vid: int = VID, pid: int = PID):
        self.vid = vid
        self.pid = pid
        self._dev = None
        self.read_errors = 0
        self.read_recoveries = 0

    def open(self) -> None:
        """Open the first HID interface with interface_number 0 or -1 (-1 = not reported by the OS).

        Only these two values are accepted: the DLL evidence does not say which interface of a composite device
        carries the reports, so any other interface is not opened.
        """
        try:
            import hid
        except ImportError:
            raise EcutUsbError('hidapi not installed. pip install hidapi')
        if self.is_open:
            raise EcutUsbError('Device already open')
        matches = [info for info in hid.enumerate(self.vid, self.pid)
                   if info['interface_number'] in (0, -1)]
        if len(matches) != 1:
            raise EcutUsbError(f'Expected one E-Cut HID interface, found {len(matches)}')
        dev = hid.device()
        try:
            dev.open_path(matches[0]['path'])
            dev.set_nonblocking(True)
        except OSError as exc:
            dev.close()
            raise EcutUsbError(str(exc)) from exc
        self._dev = dev
        log.info('E-Cut opened: VID=%04X PID=%04X serial=%s',
                 self.vid, self.pid, matches[0].get('serial_number'))

    def close(self) -> None:
        if self._dev:
            self._dev.close()
            self._dev = None

    def send(self, report: bytes) -> None:
        if not self._dev:
            raise EcutUsbError('Device not open')
        if len(report) != REPORT_SIZE:
            raise ValueError(f'Report must be {REPORT_SIZE} bytes')
        try:
            written = self._dev.write(report)
        except OSError as exc:
            raise EcutUsbError(str(exc)) from exc
        if not isinstance(written, int) or written != len(report):
            raise EcutUsbError(f'HID write failed or short: {written!r} of {len(report)} bytes')

    def recv(self, timeout_ms: int = 100) -> Optional[EcutRxFrame]:
        """Read status; after a bad read, require a fresh valid frame within a bounded retry budget."""
        if not self._dev:
            raise EcutUsbError('Device not open')
        failure = cause = None
        deadline = None
        for attempt in range(self._READ_ATTEMPTS):
            if attempt:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(self._READ_RETRY_DELAY, remaining))
                if time.monotonic() >= deadline:
                    break
            try:
                data = self._dev.read(REPORT_SIZE, timeout_ms if attempt == 0 else 0)
            except OSError as exc:
                self.read_errors += 1
                if (exc.errno in (errno.ENODEV, errno.ENXIO, errno.EBADF, errno.ENOENT)
                        or getattr(exc, 'winerror', None) in (6, 1167)):
                    raise EcutUsbError(str(exc)) from exc
                failure, cause = EcutUsbError(str(exc)), exc
            else:
                if deadline is not None and time.monotonic() >= deadline:
                    break
                if not data:
                    if failure is None:
                        return None
                    continue
                try:
                    report = bytes(data)
                    if len(report) == PAYLOAD_SIZE:
                        report = b'\0' + report
                    frame = decode_rx_report(report)
                    if frame.report_id != 0 or not frame.crc_valid:
                        raise EcutUsbError('Invalid HID report ID or CRC')
                except (ValueError, struct.error, EcutUsbError) as exc:
                    self.read_errors += 1
                    if isinstance(exc, EcutUsbError):
                        failure, cause = exc, None
                    else:
                        failure, cause = EcutUsbError(f'Malformed HID report: {exc}'), exc
                else:
                    if failure is not None:
                        self.read_recoveries += 1
                        log.warning('E-Cut status read recovered after %d retries', attempt)
                    return frame
            if deadline is None:
                deadline = time.monotonic() + self._READ_RECOVERY_SECONDS
        raise failure from cause

    def cmd(self, opcode: int, params: bytes = b'') -> None:
        self.send(build_tx_packet(opcode, params))

    def stop(self) -> None:
        self.cmd(Cmd.STOP)

    def reset(self) -> None:
        raise EcutError('Reset requires EcutAPI.reset() initialization sequence')

    def estop(self) -> None:
        self.cmd(Cmd.ESTOP)

    def home(self) -> None:
        raise EcutError('Command parameters are not verified')

    def jog_on(self, axis: int = 0, direction: int = 0) -> None:
        raise EcutError('Command parameters are not verified')

    def jog_off(self) -> None:
        raise EcutError('Command parameters are not verified')

    def probe(self) -> None:
        raise EcutError('Command parameters are not verified')

    def dwell(self, ms: int) -> None:
        raise EcutError('Command parameters are not verified')

    def send_motion(self, records: list[bytes]) -> None:
        self.send(build_motion_packet(records))

    def poll(self) -> Optional[EcutRxFrame]:
        return self.recv(timeout_ms=0)

    @property
    def is_open(self) -> bool:
        return self._dev is not None
