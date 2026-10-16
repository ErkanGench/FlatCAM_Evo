# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     10/16/2026                                     #
# License:  MIT Licence                                    #
# ##########################################################
"""
The GRBL serial client of the GRBL Sender Plugin: 1 operation owns the port at
a time, every reply is classified, and an uncertain motion latches recovery.

The class that uses GrblClientMixin must have self.app and must call
self._grbl_init_state() in __init__. It must also have the hook
_grbl_set_ui_connected(connected) and the signal grbl_port_closed_sig.
"""

import time
import threading

import serial
import serial.tools.list_ports

import gettext
import appTranslation as fcTranslate
import builtins

from appPlugins.Common.grbl_protocol import (
    parse_grbl_probe_output,
    parse_grbl_active_wcs,
    parse_grbl_work_offset,
    grbl_reply_error,
    probe_timeout_s,
    grbl_report_scale,
    parse_grbl_setting,
    parse_grbl_status_state,
    grbl_modes_confirmed,
)
from appPlugins.Common.levelling_interp import match_nearest_point

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class _GrblProbeAbort(Exception):
    """
    Stops a GRBL probing run.

    status: 'error', 'timeout', 'cancelled', 'port_error', 'not_idle',
    'unknown_units', 'modes_not_confirmed', 'probe_failed' or 'probe_invalid'.
    """

    def __init__(self, command, text, status):
        super().__init__(status)
        self.command = command
        self.text = text
        self.status = status


class _GrblOperation:
    """
    1 operation that sends commands to GRBL and reads the replies. While it
    exists, it owns the serial port: no other operation can start.

    :param name:   short name for messages, for example 'probe' or 'jog'.
    :param motion: True if the operation can move the machine; it then needs
                   a machine that is not in recovery.
    """

    def __init__(self, name, motion=False):
        self.name = name
        self.motion = motion
        self.cancel = threading.Event()
        self.failed = False
        self.safety_generation = 0
        self.port = None


class GrblClientMixin:

    def _grbl_init_state(self):
        self.grbl_probe_result = ''
        self.grbl_work_offset = (0.0, 0.0, 0.0)

        # serial session: 1 operation that reads GRBL replies at a time
        self._grbl_op_lock = threading.Lock()
        self._grbl_op = None
        # None, 'needs_reset' or 'needs_home'; motion is blocked until it is None again
        self._grbl_recovery = None
        # True if a disconnect waits for the running operation to stop
        self._grbl_close_pending = False
        self._grbl_connected = False
        self._grbl_connect_attempt = None
        self._grbl_safety_generation = 0
        self._grbl_rx_port = None
        self._grbl_rx_buffer = b''
        self._grbl_reply_pending = False
        # True after the user was told that an earlier command never got its reply
        self._grbl_stale_notified = False
        self._grbl_reset_pending = False
        # True from the first write of a stream until a confirmed completion or the reset banner:
        # GRBL can still hold lines (and their ok replies) of the stopped job
        self._grbl_stream_dirty = False

        self.grbl_ser_port = None

    @staticmethod
    def on_grbl_list_serial_ports():
        """
        List the serial ports of the system. The ports are not opened, so this
        is fast and does not reset a board through DTR.

        :returns: a list of port names
        """
        return [port_info.device for port_info in serial.tools.list_ports.comports()]

    def _grbl_close_port(self, port=None, attempt=None):
        """Close the serial port now. Safe in a worker thread (the UI changes through a signal)."""
        with self._grbl_op_lock:
            if attempt is not None and (self._grbl_connect_attempt is not attempt or (
                    port is not None and self.grbl_ser_port is not port)):
                return False
            port = self.grbl_ser_port
            self.grbl_ser_port = None
            self._grbl_connected = False
            self._grbl_connect_attempt = None
            self._grbl_close_pending = False
            if port is not None:
                self._grbl_rx_port = None
                self._grbl_rx_buffer = b''
                self._grbl_reply_pending = False
        if port is not None:
            try:
                port.close()
            except (serial.SerialException, OSError) as err:
                self.app.log.debug("ToolLevelling._grbl_close_port() -> %s" % str(err))
        self.grbl_port_closed_sig.emit()
        return True

    def _grbl_disconnect(self):
        """
        Close the port. During an operation: stop the operation (feed hold if it
        can move the machine) and close the port when the operation releases it.
        """
        with self._grbl_op_lock:
            self._grbl_safety_generation += 1
            self._grbl_reset_pending = False
            op = self._grbl_op
            if op is not None:
                op.cancel.set()
                if op.motion:
                    self._grbl_write_realtime_locked(b'!')
                    self._grbl_recovery = 'needs_reset'
                self._grbl_close_pending = True

        if op is not None:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("The port closes when the running operation stops."))
            return

        self._grbl_close_port()
        self.app.inform.emit("%s" % _("Port disconnected."))

    def _grbl_force_close(self):
        """Close the port now, also during an operation (the application ends)."""
        with self._grbl_op_lock:
            self._grbl_safety_generation += 1
            self._grbl_reset_pending = False
            op = self._grbl_op
            if op is not None:
                op.cancel.set()
                if op.motion:
                    self._grbl_write_realtime_locked(b'!')
                    self._grbl_recovery = 'needs_reset'
        self._grbl_close_port()

    def _grbl_port_ready(self):
        """:return: True only after an open port has completed the GRBL handshake."""
        port = getattr(self, 'grbl_ser_port', None)
        return self._grbl_connected and port is not None and bool(getattr(port, 'is_open', False))

    def _grbl_recovery_text(self):
        if self._grbl_recovery == 'needs_reset':
            return _("GRBL needs recovery. Press Reset, then Home.")
        return _("GRBL needs recovery. Press Home.")

    def _grbl_reserve(self, name, motion=False, allow_in_recovery=False):
        """
        Reserve the serial port for 1 operation. Call it in the GUI thread,
        before the worker task is scheduled.

        :param name:              short name of the operation.
        :param motion:            True if the operation can move the machine.
        :param allow_in_recovery: True only for the home cycle, which ends the recovery.
        :return: a _GrblOperation, or None (the user was told why).
        """
        if not self._grbl_port_ready() or self._grbl_close_pending:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Not connected to a GRBL controller."))
            return None

        with self._grbl_op_lock:
            if self._grbl_op is not None:
                self.app.inform.emit('[WARNING_NOTCL] %s: %s. %s' % (
                    _("GRBL is busy"), self._grbl_op.name, _("Wait, or press Stop.")))
                return None
            if self._grbl_stream_dirty and not (name == 'home' and allow_in_recovery):
                self.app.inform.emit('[ERROR_NOTCL] %s' % _(
                    "GRBL can still have lines of the stopped job. Press Reset, then Home."))
                return None
            if motion and self._grbl_recovery is not None and not (
                    allow_in_recovery and (self._grbl_recovery == 'needs_home' or (
                        name == 'home' and self._grbl_recovery == 'needs_reset' and self._grbl_reset_pending))):
                self.app.inform.emit('[ERROR_NOTCL] %s' % self._grbl_recovery_text())
                return None
            op = _GrblOperation(name, motion)
            op.safety_generation = self._grbl_safety_generation
            op.port = self.grbl_ser_port
            self._grbl_op = op
            return op

    def _grbl_release(self, op):
        """Free the serial port after the operation `op` ended; close it if a disconnect waits."""
        close_now = False
        with self._grbl_op_lock:
            if self._grbl_op is op:
                self._grbl_op = None
                close_now = self._grbl_close_pending
        if close_now:
            self._grbl_close_port()

    def _grbl_start_op(self, name, fn, motion=False, allow_in_recovery=False):
        """
        Reserve the port now (GUI thread) and run fn(op) in a worker thread.
        The port is released when fn ends, also after an exception.

        :return: True if the worker task was scheduled.
        """
        op = self._grbl_reserve(name, motion=motion, allow_in_recovery=allow_in_recovery)
        if op is None:
            return False

        def worker_task():
            try:
                result = fn(op)
                if motion and not allow_in_recovery and result is not False:
                    self._grbl_wait_idle(op)
            except (serial.SerialException, OSError) as err:
                with self._grbl_op_lock:
                    self._grbl_failure_locked(op, 'port_error')
                self.app.log.error("ToolLevelling._grbl_start_op(%s) -> %s" % (name, str(err)))
                self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("The serial port failed"), str(err)))
            finally:
                self._grbl_release(op)

        self.app.worker_task.emit({'fcn': worker_task, 'params': []})
        return True

    def _grbl_active_locked(self, op, port=None):
        """The caller holds the operation lock; a cancelled reply is never success."""
        if self._grbl_op is op and not op.cancel.is_set() and (
                not self._grbl_port_ready() or self.grbl_ser_port is not op.port):
            self._grbl_failure_locked(op, 'port_error')
        return (self._grbl_op is op and not op.cancel.is_set() and not op.failed
                and self._grbl_port_ready() and (port is None or self.grbl_ser_port is port))

    def _grbl_failure_locked(self, op, status, text=''):
        """Latch alarm/uncertain motion before attempting hold. Caller holds the lock."""
        alarm = any(line.lower().startswith('alarm:') or parse_grbl_status_state(line) == 'Alarm'
                    for line in (text or '').splitlines())
        uncertain = status in ('timeout', 'port_error', 'probe_invalid')
        if op is not None and (self._grbl_op is not op or op.cancel.is_set() or op.failed):
            return
        if alarm or status == 'probe_failed' or (uncertain and (op is None or op.motion)):
            self._grbl_recovery = 'needs_reset'
            self._grbl_reset_pending = False
            self._grbl_safety_generation += 1
            if op is not None:
                op.failed = True
            if uncertain and not alarm:
                if op is None or self.grbl_ser_port is op.port:
                    self._grbl_write_realtime_locked(b'!')
                else:
                    # Never send the old operation's hold to a replacement controller.
                    try:
                        op.port.write(b'!')
                    except (serial.SerialException, OSError) as err:
                        self.app.log.error("ToolLevelling._grbl_failure_locked() -> %s" % str(err))

    def _grbl_read_more_locked(self, op, port):
        """
        Buffer 1 more readline() of `port`; the operation lock is free during the read.
        The caller holds the lock and must treat everything it checked before as stale.

        :return: None if the data was buffered, else 'port_error' or 'cancelled'.
        """
        error = None
        chunk = b''
        self._grbl_op_lock.release()
        try:
            try:
                chunk = port.readline()
            except (serial.SerialException, OSError) as err:
                error = err
            if not chunk:
                time.sleep(0.01)
        finally:
            self._grbl_op_lock.acquire()
        if error is not None:
            self.app.log.error("ToolLevelling._grbl_read_more_locked() -> %s" % str(error))
            self._grbl_failure_locked(op, 'port_error')
            return 'port_error'
        if not self._grbl_active_locked(op, port):
            return 'cancelled'
        self._grbl_rx_buffer += chunk or b''
        return None

    def _grbl_prepare_locked(self, op, port):
        """
        Classify buffered async data before writing; old ok is not a new acknowledgement.

        A partial line is read to its end (up to 0.5 s) before it is classified. A reply that is
        still pending from an earlier command gets 1 s to arrive; it is consumed, never reused.
        """
        if self._grbl_rx_port is not port:
            self._grbl_rx_port = port
            self._grbl_rx_buffer = b''
            self._grbl_reply_pending = False
        try:
            waiting = port.in_waiting
            if waiting:
                self._grbl_rx_buffer += port.read(waiting)
        except (serial.SerialException, OSError) as err:
            self.app.log.error("ToolLevelling._grbl_prepare_locked() -> %s" % str(err))
            self._grbl_failure_locked(op, 'port_error')
            return '', 'port_error'
        partial_until = pending_until = None
        while True:
            lines = self._grbl_rx_buffer.split(b'\n')
            self._grbl_rx_buffer = lines.pop()
            text = '\n'.join(line.decode('utf-8', errors='replace').strip() for line in lines)
            self._grbl_failure_locked(op, 'error', text)
            if op.failed:
                return text, 'error'
            if any(line.strip().lower() == 'ok' or line.strip().lower().startswith('error:')
                   for line in text.splitlines()):
                self._grbl_reply_pending = False
            if op.motion and any(line.strip().startswith('[PRB:') for line in text.splitlines()):
                self._grbl_failure_locked(op, 'probe_invalid')
                return text, 'error'
            if self._grbl_rx_buffer:
                # A line is still arriving: wait for its end before it is classified.
                if partial_until is None:
                    partial_until = time.monotonic() + 0.5
                elif time.monotonic() >= partial_until:
                    self._grbl_failure_locked(op, 'probe_invalid')
                    return text, 'error'
            else:
                partial_until = None
                if not self._grbl_reply_pending:
                    return '', None
                if getattr(self, '_grbl_stale_notified', False):
                    self._grbl_failure_locked(op, 'timeout')
                    return text, 'timeout'
                if pending_until is None:
                    pending_until = time.monotonic() + 1.0
                elif time.monotonic() >= pending_until:
                    self._grbl_stale_notified = True
                    self.app.inform.emit('[ERROR_NOTCL] %s' % _(
                        "GRBL did not answer an earlier command. Press Reset, then Home."))
                    self._grbl_failure_locked(op, 'timeout')
                    return text, 'timeout'
            status = self._grbl_read_more_locked(op, port)
            if status is not None:
                return text, status

    def _grbl_wait_idle(self, op):
        """
        Keep motion ownership while the controller reports a busy state; acceptance is not completion.
        There is no overall deadline: a long move, a feed hold or an open door ends with Stop, Idle
        or a failure. An unanswered status query already latches a timeout.
        """
        while True:
            with self._grbl_op_lock:
                if not self._grbl_active_locked(op):
                    return False
            state = parse_grbl_status_state(self._grbl_query_status(op))
            with self._grbl_op_lock:
                if not self._grbl_active_locked(op):
                    return False
                if state == 'Idle':
                    return True
                if state not in ('Run', 'Jog', 'Hold', 'Door', 'Home'):
                    self._grbl_failure_locked(op, 'probe_invalid')
                    return False
            time.sleep(0.05)

    def _grbl_write_realtime_locked(self, data):
        """
        Write a GRBL real-time command (1 byte, no newline, no reply read).
        The caller must hold self._grbl_op_lock.

        :return: True if the byte was written.
        """
        if not self._grbl_port_ready():
            return False
        try:
            self.grbl_ser_port.write(data)
        except (serial.SerialException, OSError) as err:
            self.app.log.error("ToolLevelling._grbl_write_realtime_locked() -> %s" % str(err))
            return False
        return True

    def _grbl_transact(self, op, command, timeout=10.0, echo=True):
        """
        Send 1 line to GRBL for the operation `op`, and read the reply until
        'ok', 'error:N' or 'ALARM:N', the time limit, a stop of `op`, or a port error.

        Cancellation and operation identity are checked before writes and after
        reads under the Stop lock. Buffered asynchronous alarms are classified,
        and residual acknowledgements are consumed before the next write.
        The read uses the port that was written to, never a replacement port.

        :return: (text, status). text: the decoded reply lines joined by '\\n'.
            status: 'ok', 'error', 'timeout', 'cancelled' or 'port_error'.
        """
        cmd = command.strip()
        with self._grbl_op_lock:
            if not self._grbl_active_locked(op) or self._grbl_reset_pending:
                return '', 'cancelled'
            port = self.grbl_ser_port
            text, status = self._grbl_prepare_locked(op, port)
            if status is not None:
                return text, status
            try:
                self._grbl_reply_pending = True
                self._grbl_stale_notified = False
                port.write((cmd + '\n').encode('utf-8'))
            except (serial.SerialException, OSError) as err:
                self.app.log.error("ToolLevelling._grbl_transact() -> %s" % str(err))
                self._grbl_failure_locked(op, 'port_error')
                return '', 'port_error'

        if echo:
            self.console_line_sig.emit(cmd)

        decoded_lines = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._grbl_op_lock:
                if not self._grbl_active_locked(op, port):
                    return '\n'.join(decoded_lines), 'cancelled'
            try:
                chunk = b'' if b'\n' in self._grbl_rx_buffer else port.readline()
            except (serial.SerialException, OSError) as err:
                self.app.log.error("ToolLevelling._grbl_transact() -> %s" % str(err))
                with self._grbl_op_lock:
                    self._grbl_failure_locked(op, 'port_error')
                return '\n'.join(decoded_lines), 'port_error'
            with self._grbl_op_lock:
                if not self._grbl_active_locked(op, port):
                    return '\n'.join(decoded_lines), 'cancelled'
                self._grbl_rx_buffer += chunk
                complete = self._grbl_rx_buffer.rsplit(b'\n', 1)[0] if b'\n' in self._grbl_rx_buffer else b''
                self._grbl_failure_locked(op, 'error', complete.decode('utf-8', errors='replace'))
                if op.failed:
                    self._grbl_rx_buffer = self._grbl_rx_buffer.rsplit(b'\n', 1)[-1]
                    return '\n'.join(decoded_lines + [complete.decode('utf-8', errors='replace').strip()]), 'error'
                while b'\n' in self._grbl_rx_buffer:
                    raw_line, self._grbl_rx_buffer = self._grbl_rx_buffer.split(b'\n', 1)
                    decoded_line = raw_line.decode('utf-8', errors='replace').strip()
                    if not decoded_line:
                        continue
                    decoded_lines.append(decoded_line)
                    if echo:
                        self.console_line_sig.emit('\t\t\t: ' + decoded_line.upper())
                    lowered = decoded_line.lower()
                    if lowered == 'ok':
                        self._grbl_reply_pending = False
                        text, status = self._grbl_prepare_locked(op, port)
                        if status is not None:
                            return '\n'.join(decoded_lines + [text]), status
                        return '\n'.join(decoded_lines), 'ok'
                    if lowered.startswith('error:'):
                        self._grbl_reply_pending = False
                        return '\n'.join(decoded_lines), 'error'

        with self._grbl_op_lock:
            if not self._grbl_active_locked(op, port):
                return '\n'.join(decoded_lines), 'cancelled'
            self._grbl_failure_locked(op, 'timeout')
        return '\n'.join(decoded_lines), 'timeout'

    def _grbl_query_status(self, op, timeout=2.0):
        """Request a fresh status report, preserving async alarm and cancellation evidence."""
        with self._grbl_op_lock:
            if not self._grbl_active_locked(op) or self._grbl_reset_pending:
                return None
            port = self.grbl_ser_port
            text, status = self._grbl_prepare_locked(op, port)
            if status is not None:
                return None
            try:
                port.write(b'?')
            except (serial.SerialException, OSError) as err:
                self.app.log.error("ToolLevelling._grbl_query_status() -> %s" % str(err))
                self._grbl_failure_locked(op, 'port_error')
                return None

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._grbl_op_lock:
                if not self._grbl_active_locked(op, port):
                    return None
            try:
                chunk = b'' if b'\n' in self._grbl_rx_buffer else port.readline()
            except (serial.SerialException, OSError):
                with self._grbl_op_lock:
                    self._grbl_failure_locked(op, 'port_error')
                return None
            with self._grbl_op_lock:
                if not self._grbl_active_locked(op, port):
                    return None
                self._grbl_rx_buffer += chunk or b''
                complete = self._grbl_rx_buffer.rsplit(b'\n', 1)[0] if b'\n' in self._grbl_rx_buffer else b''
                text = complete.decode('utf-8', errors='replace')
                self._grbl_failure_locked(op, 'error', text)
                while b'\n' in self._grbl_rx_buffer:
                    raw_line, self._grbl_rx_buffer = self._grbl_rx_buffer.split(b'\n', 1)
                    line = raw_line.decode('utf-8', errors='replace').strip()
                    if line.startswith('<'):
                        state = parse_grbl_status_state(line)
                        if state is None:
                            self._grbl_failure_locked(op, 'probe_invalid')
                            return None
                        text, status = self._grbl_prepare_locked(op, port)
                        if status is not None and state != 'Alarm':
                            return None
                        return line
                if op.failed:
                    return None
        with self._grbl_op_lock:
            if self._grbl_active_locked(op, port):
                self._grbl_failure_locked(op, 'timeout')
        return None

    def _grbl_confirm_reset(self, op, timeout=10.0):
        """The home worker ignores old replies until this reset epoch's startup banner."""
        port = op.port
        with self._grbl_op_lock:
            if not self._grbl_active_locked(op, port) or op.safety_generation != self._grbl_safety_generation:
                return False
            if self._grbl_rx_port is not port:
                self._grbl_rx_port = port
                self._grbl_rx_buffer = b''

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._grbl_op_lock:
                if (not self._grbl_active_locked(op, port) or not self._grbl_reset_pending
                        or op.safety_generation != self._grbl_safety_generation):
                    return False
            try:
                chunk = b'' if b'\n' in self._grbl_rx_buffer else port.readline()
            except (serial.SerialException, OSError) as err:
                self.app.log.error("ToolLevelling._grbl_confirm_reset() -> %s" % str(err))
                with self._grbl_op_lock:
                    self._grbl_failure_locked(op, 'port_error')
                return False
            with self._grbl_op_lock:
                if (not self._grbl_active_locked(op, port) or not self._grbl_reset_pending
                        or op.safety_generation != self._grbl_safety_generation):
                    return False
                self._grbl_rx_buffer += chunk or b''
                while b'\n' in self._grbl_rx_buffer:
                    raw_line, self._grbl_rx_buffer = self._grbl_rx_buffer.split(b'\n', 1)
                    line = raw_line.decode('utf-8', errors='replace').strip()
                    if line.lower().startswith('grbl '):
                        # Only the same uncancelled reset epoch can retire old reply evidence.
                        self._grbl_reply_pending = False
                        self._grbl_reset_pending = False
                        self._grbl_stream_dirty = False
                        self._grbl_recovery = 'needs_home'
                        text, status = self._grbl_prepare_locked(op, port)
                        return status is None
                    # Pre-banner ok/error/ALARM/MSG lines belong to the previous controller epoch
                    # (GRBL 1.1 prints ALARM:3 before the banner when the reset hits a moving machine).

        with self._grbl_op_lock:
            if self._grbl_active_locked(op, port) and op.safety_generation == self._grbl_safety_generation:
                self._grbl_failure_locked(op, 'timeout')
        return False

    def _grbl_probe_run(self, op, context, points, tol, travel_z, depth, probe_fr, units_cmd, probe_timeout):
        """
        Probe every point. Runs in a worker thread and reads no widgets.

        Preconditions before any motion: GRBL is Idle, setting $13 is known,
        the units, G90 and G94 are acknowledged and confirmed by $G.
        Each probe must give 1 valid record for its point before the next move.
        A complete result goes to the GUI thread through al_result_ready_sig.
        """
        modes_ok = False
        staged = {}
        evidence = {'context': context, 'operation': op, 'safety_generation': op.safety_generation}
        precision = getattr(op, 'precision_inputs', ())

        def step(command, timeout=10.0):
            text, status = self._grbl_transact(op, command, timeout=timeout)
            if status != 'ok':
                raise _GrblProbeAbort(command, text, status)
            return text

        def check_frame():
            # A changed/unknown coordinate frame must not produce a guessed lift.
            try:
                text = step('$G')
                if not grbl_modes_confirmed(text, units_cmd) or parse_grbl_active_wcs(text) != active_wcs:
                    raise ValueError('distance mode, units or active WCS changed')
                if parse_grbl_work_offset(step('$#'), active_wcs) != offset:
                    raise ValueError('work offset changed')
                if parse_grbl_status_state(self._grbl_query_status(op)) != 'Idle':
                    raise ValueError('GRBL is not Idle')
            except ValueError as err:
                raise _GrblProbeAbort('$G / $# / ?', str(err), 'probe_invalid')
            except _GrblProbeAbort as abort:
                if abort.status == 'error':
                    raise _GrblProbeAbort(abort.command, abort.text, 'probe_invalid')
                raise

        try:
            state = parse_grbl_status_state(self._grbl_query_status(op))
            if state != 'Idle':
                raise _GrblProbeAbort('?', state or _("no answer"), 'not_idle')

            report_setting = parse_grbl_setting(step('$$'), 13)
            if report_setting is None:
                raise _GrblProbeAbort('$$', '', 'unknown_units')
            if precision and report_setting not in (0.0, 1.0):
                raise _GrblProbeAbort('$$', _('GRBL $13 must report 0 or 1 before precision probing.'), 'error')
            scale = grbl_report_scale(context.units, report_setting == 1.0)
            if precision and precision[1] <= 0.0001 * scale:
                raise _GrblProbeAbort('precision retract', _(
                    'Increase the precision retract above the GRBL position report resolution.'), 'error')

            step(units_cmd)
            step('G90')
            step('G94')
            gc_text = step('$G')
            if not grbl_modes_confirmed(gc_text, units_cmd):
                raise _GrblProbeAbort('$G', gc_text, 'modes_not_confirmed')
            modes_ok = True

            active_wcs = parse_grbl_active_wcs(gc_text)
            offset = parse_grbl_work_offset(step('$#'), active_wcs)
            self.grbl_work_offset = offset

            probe_cmd = 'G38.2 Z{0:.4f} F{1:.4f}'.format(depth, probe_fr)
            for key, (x, y) in points.items():
                step('G0 Z{0:.4f}'.format(travel_z))
                step('G0 X{0:.4f} Y{1:.4f}'.format(x, y))
                # GRBL answers 'ok' to G4 P0 only when all queued moves are done,
                # so the probe time limit starts when the probe move starts
                step('G4 P0', timeout=120.0)
                text = step(probe_cmd, timeout=probe_timeout)
                height = self._al_check_probe_reply(probe_cmd, text, key, points, tol, offset, scale)
                if precision:
                    fine_feed, retract = precision
                    retract_z = round(height + retract, 4)
                    if not depth <= height < retract_z <= travel_z:
                        raise _GrblProbeAbort(probe_cmd, _(
                            'Contact or precision retract is outside the depth/clearance limits.'), 'probe_invalid')
                    check_frame()
                    # PRB is machine position in report units. height is already
                    # converted to the active work frame and job units. Stay G90
                    # so every normal/error recovery lift uses the same frame.
                    step('G0 Z{0:.4f}'.format(retract_z))
                    step('G4 P0', timeout=120.0)
                    check_frame()
                    step('G4 P0', timeout=120.0)
                    fine_cmd = 'G38.2 Z{0:.4f} F{1:.4f}'.format(depth, fine_feed)
                    text = step(fine_cmd, timeout=probe_timeout_s(retract_z, depth, fine_feed))
                    height = self._al_check_probe_reply(fine_cmd, text, key, points, tol, offset, scale)
                    if not depth <= height < retract_z:
                        raise _GrblProbeAbort(fine_cmd, text, 'probe_invalid')
                    check_frame()
                    step('G0 Z{0:.4f}'.format(travel_z))
                    step('G4 P0', timeout=120.0)
                staged[key] = height

            step('G0 Z{0:.4f}'.format(travel_z))
            step('G4 P0', timeout=120.0)
            with self._grbl_op_lock:
                if not self._grbl_active_locked(op) or self._grbl_safety_generation != op.safety_generation:
                    raise _GrblProbeAbort('G4 P0', '', 'cancelled')
        except _GrblProbeAbort as abort:
            self._grbl_handle_abort(op, abort, travel_z, modes_ok)
            self.al_result_ready_sig.emit(dict(evidence, kind='failed'))
            return False
        except ValueError as err:
            # the $G or $# reply could not be read; the modes are confirmed, so lift Z
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not read the GRBL work offset"), str(err)))
            if precision:
                self._grbl_hold_for_recovery()
                self.app.inform.emit('[ERROR_NOTCL] %s' % self._grbl_recovery_text())
            else:
                self._grbl_retract(op, travel_z)
            self.al_result_ready_sig.emit(dict(evidence, kind='failed'))
            return False

        self.app.inform.emit('%s' % _("Finished probing. Doing the autolevelling."))
        self.al_result_ready_sig.emit(dict(evidence, kind='probe', heights=staged))
        return True

    def _al_check_probe_reply(self, command, text, expected_key, points, tol, offset, scale):
        """
        Check the reply of 1 G38.2 move.

        :return: the height (app units) for expected_key.
        :raises _GrblProbeAbort: 'probe_failed' if a finite record proves no contact;
            'probe_invalid' if the record is malformed/nonfinite or not unique,
            or if the record is not at the commanded point.
        """
        try:
            results = parse_grbl_probe_output(text)
        except ValueError:
            # Validate the numeric record separately from its contact flag. A bad
            # number is uncertainty, not evidence that GRBL entered Alarm.
            records = [line.strip() for line in text.splitlines() if line.strip().startswith('[PRB:')]
            if len(records) == 1 and records[0].endswith(':0]'):
                try:
                    valid = parse_grbl_probe_output(records[0][:-3] + ':1]')
                except ValueError:
                    valid = []
                if len(valid) == 1:
                    raise _GrblProbeAbort(command, text, 'probe_failed')
            raise _GrblProbeAbort(command, text, 'probe_invalid')
        if len(results) != 1:
            raise _GrblProbeAbort(command, text, 'probe_invalid')

        mx, my, mz = results[0]
        ox, oy, oz = offset
        x = (mx - ox) * scale
        y = (my - oy) * scale
        z = (mz - oz) * scale
        if match_nearest_point(points, x, y, tol) != expected_key:
            raise _GrblProbeAbort(command, text, 'probe_invalid')
        return z

    def _grbl_hold_for_recovery(self):
        """Feed hold now; the machine needs a reset and a home cycle."""
        with self._grbl_op_lock:
            self._grbl_failure_locked(self._grbl_op, 'probe_invalid')

    def _grbl_retract(self, op, travel_z):
        """
        Lift Z to travel_z. Call it only after the units and G90 are confirmed.

        :return: True only after the accepted move physically completed.
        """
        text, status = self._grbl_transact(op, 'G0 Z{0:.4f}'.format(travel_z), timeout=30.0)
        if status == 'ok':
            text, status = self._grbl_transact(op, 'G4 P0', timeout=120.0)
            if status == 'ok':
                return True
        if status == 'cancelled':
            return False
        self._grbl_hold_for_recovery()
        self.app.inform.emit('[ERROR_NOTCL] %s: %s. %s' % (
            _("The Z retract failed"), grbl_reply_error(text) or status, self._grbl_recovery_text()))
        return False

    def _grbl_handle_abort(self, op, abort, travel_z, modes_ok):
        """Tell the user why the probing run stopped, and make the machine safe."""
        status = abort.status
        if status == 'cancelled':
            # Stop, Reset or a disconnect already sent the hold or the reset
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Probing was stopped."))
            return

        if status == 'not_idle':
            self.app.inform.emit('[ERROR_NOTCL] %s: %s. %s' % (
                _("GRBL state"), abort.text, _("GRBL must be Idle before probing. Reset or home GRBL.")))
            return

        if status == 'unknown_units':
            self.app.inform.emit('[ERROR_NOTCL] %s' % _(
                "GRBL did not report setting $13 (report units). Probing was not started."))
            return

        if status in ('timeout', 'probe_invalid', 'port_error'):
            # the machine state is not known: stop the motion now
            self._grbl_hold_for_recovery()
            self.app.inform.emit('[ERROR_NOTCL] %s: %s (%s). %s' % (
                _("Probing stopped"), abort.command, status, self._grbl_recovery_text()))
            if status == 'probe_invalid' and abort.text:
                self.app.inform.emit('[ERROR_NOTCL] %s' % abort.text)
            return

        if status == 'probe_failed' or 'alarm' in (abort.text or '').lower():
            # GRBL is in alarm: it accepts no motion until a reset
            with self._grbl_op_lock:
                self._grbl_failure_locked(op, status, abort.text)
            self.app.inform.emit('[ERROR_NOTCL] %s: %s. %s' % (
                _("The probe did not touch the surface or GRBL is in alarm"), abort.command,
                self._grbl_recovery_text()))
            return

        # 'error' or 'modes_not_confirmed': GRBL refused a command
        self.app.inform.emit('[ERROR_NOTCL] %s: %s -> %s' % (
            _("GRBL refused a command"), abort.command, grbl_reply_error(abort.text) or abort.text))
        if modes_ok:
            self._grbl_retract(op, travel_z)
        else:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _(
                "No Z retract was sent, because the units and the distance mode were not confirmed."))
