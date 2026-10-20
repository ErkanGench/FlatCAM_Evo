#!/usr/bin/env python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

import serial

from appPlugins.Common.grbl.grbl_client import (
    stream_lines, validate_stream_lines, dwell_seconds, GRBL_RX_BUFFER, GRBL_MAX_LINE)


class FakeStreamPort:
    """Each written line gets 'ok' after 1 readline(); the receive buffer must never overflow."""

    def __init__(self, rx_size=127, errors=None, alarm_at=None):
        self.rx_size = rx_size
        self.pending = []           # byte counts in the GRBL buffer
        self.replies = []
        self.written = []
        self.polls = 0
        self.max_used = 0
        self.errors = errors or {}  # line index -> 'error:N'
        self.alarm_at = alarm_at
        self.count = 0
        self.status_sent = False

    def write(self, data):
        if data == b'?':
            self.polls += 1
            # answer the first '?' only; more answers would keep readline() busy for ever
            if not self.status_sent:
                self.status_sent = True
                self.replies.append(b'<Run|MPos:0.000,0.000,0.000|FS:0,0>\r\n')
            return 'ok'
        self.written.append(data)
        self.pending.append(len(data))
        used = sum(self.pending)
        self.max_used = max(self.max_used, used)
        assert used <= self.rx_size, "GRBL receive buffer overflow"
        return 'ok'

    def readline(self):
        if self.replies:
            return self.replies.pop(0)
        if not self.pending:
            return b''
        self.pending.pop(0)
        index = self.count
        self.count += 1
        if self.alarm_at == index:
            return b'ALARM:1\r\n'
        return (self.errors.get(index, 'ok') + '\r\n').encode()


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class TimedPort(FakeStreamPort):
    """
    A GRBL fake with a fake clock. Each readline() advances the clock by `step` s, so no test sleeps.
    The oldest line gets 'ok' when the clock reaches `ack_at` (never if None). Each '?' is answered with
    report(now). A test that never times out fails at `limit` s instead of looping for ever.
    """

    def __init__(self, clock, ack_at=None, report=None, step=1.0, limit=1000.0, **kwargs):
        super().__init__(**kwargs)
        self.clock = clock
        self.ack_at = ack_at
        self.report = report
        self.step = step
        self.limit = limit
        self.queue = []

    def write(self, data):
        if data == b'?':
            self.polls += 1
            if self.report is not None:
                self.queue.append((self.report(self.clock.now) + '\r\n').encode())
            return 'ok'
        return super().write(data)

    def readline(self):
        self.clock.now += self.step
        assert self.clock.now <= self.limit, "the streamer did not time out"
        if self.ack_at is not None and self.clock.now >= self.ack_at and self.pending:
            self.pending.pop(0)
            return b'ok\r\n'
        if self.queue:
            return self.queue.pop(0)
        return b''


def run(port, lines, **kwargs):
    return stream_lines(lines, port.write, port.readline, **kwargs)


class TestStream(unittest.TestCase):
    def test_all_lines_sent_in_order(self):
        lines = ['G1 X%d Y%d F100' % (i, i) for i in range(200)]
        port = FakeStreamPort()
        res = run(port, lines)
        self.assertEqual(res['status'], 'finished')
        self.assertEqual(res['done'], 200)
        self.assertEqual(res['in_flight'], 0)
        self.assertEqual([d.decode().strip() for d in port.written], lines)

    def test_buffer_never_overflows_and_is_used(self):
        lines = ['G1 X%d.123456 Y%d.654321 F1000' % (i, i) for i in range(100)]
        port = FakeStreamPort()
        run(port, lines)
        self.assertLessEqual(port.max_used, 127)
        self.assertGreater(port.max_used, 60)

    def test_buffer_fills_to_the_last_byte(self):
        # 2 lines of 10 bytes fit in 20 bytes: the fill condition is 'used + len > rx_size'
        port = FakeStreamPort(rx_size=20)
        res = run(port, ['G1 X1 Y12'] * 6, rx_size=20)
        self.assertEqual(res['status'], 'finished')
        self.assertEqual(port.max_used, 20)

    def test_error_stops(self):
        port = FakeStreamPort(errors={5: 'error:20', 8: 'error:33'})
        res = run(port, ['G1 X%d' % i for i in range(20)])
        self.assertEqual(res['status'], 'error')
        self.assertEqual(res['errors'], [(5, 'error:20')])

    def test_error_reports_in_flight(self):
        port = FakeStreamPort(errors={2: 'error:20'})
        res = run(port, ['G1 X%d' % i for i in range(10)])
        self.assertEqual(res['status'], 'error')
        self.assertEqual(res['errors'], [(2, 'error:20')])
        self.assertGreaterEqual(res['in_flight'], 1)

    def test_check_mode_counts_errors(self):
        port = FakeStreamPort(errors={2: 'error:20', 7: 'error:33'})
        res = run(port, ['G1 X%d' % i for i in range(10)], check_mode=True)
        self.assertEqual(res['status'], 'finished')
        self.assertEqual([e[0] for e in res['errors']], [2, 7])

    def test_alarm_stops(self):
        port = FakeStreamPort(alarm_at=3)
        res = run(port, ['G1 X%d' % i for i in range(10)])
        self.assertEqual(res['status'], 'alarm')

    def test_stop_request(self):
        port = FakeStreamPort()
        calls = []

        def write(data):
            calls.append(data)
            if len(calls) > 3:
                return 'cancelled'
            return port.write(data)

        res = stream_lines(['G1 X%d' % i for i in range(500)], write, port.readline)
        self.assertEqual(res['status'], 'cancelled')
        # nothing is written after the status 'cancelled'
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(port.written), 3)

    def test_stale_at_the_first_write(self):
        calls = []

        def write(data):
            calls.append(data)
            return 'stale'

        def readline():
            raise AssertionError("nothing was written, so nothing is read")

        res = stream_lines(['G1 X1', 'G1 X2'], write, readline, poll_status=True)
        self.assertEqual(res['status'], 'stale')
        self.assertEqual(res['done'], 0)
        self.assertEqual(res['in_flight'], 0)
        self.assertEqual(len(calls), 1)

    def test_port_error_after_writes(self):
        port = FakeStreamPort()
        calls = []

        def write(data):
            calls.append(data)
            if len(calls) == 4:
                return 'port_error'
            return port.write(data)

        res = stream_lines(['G1 X%d' % i for i in range(20)], write, port.readline)
        self.assertEqual(res['status'], 'port_error')
        self.assertEqual(len(calls), 4)
        self.assertEqual(res['in_flight'], 3)

    def test_port_error_on_poll_write(self):
        port = FakeStreamPort()

        def write(data):
            return 'port_error' if data == b'?' else port.write(data)

        res = stream_lines(['G1 X1'], write, port.readline, poll_status=True)
        self.assertEqual(res['status'], 'port_error')

    def test_readline_exception_is_port_error(self):
        port = FakeStreamPort()

        def readline():
            raise serial.SerialException("device lost")

        self.assertEqual(stream_lines(['G1 X1'], port.write, readline)['status'], 'port_error')

        def readline_os():
            raise OSError("device lost")

        self.assertEqual(stream_lines(['G1 X1'], port.write, readline_os)['status'], 'port_error')

    def test_progress_and_status(self):
        progress, status = [], []
        port = FakeStreamPort()
        run(port, ['G1 X1', 'G1 X2'], on_progress=lambda d, t: progress.append((d, t)),
            poll_status=True, poll_interval=0.0, on_status=status.append)
        self.assertEqual(progress[-1], (2, 2))
        self.assertTrue(status)
        self.assertGreaterEqual(port.polls, 1)

    def test_on_line_has_job_lines_and_replies_only(self):
        seen = []
        port = FakeStreamPort()
        run(port, ['G1 X1', 'G1 X2'], on_line=seen.append, poll_status=True, poll_interval=0.0)
        self.assertEqual(seen.count('G1 X1'), 1)
        self.assertEqual(seen.count('G1 X2'), 1)
        self.assertEqual(seen.count('ok'), 2)
        self.assertEqual(len(seen), 4)

    def test_long_line_rejected(self):
        lines = ['G1 X%d' % i for i in range(10)]
        lines[5] = 'G1 X1 ' + 'Y' * 80
        port = FakeStreamPort()
        res = run(port, lines)
        self.assertEqual(res['status'], 'line_too_long')
        self.assertEqual(res['line_index'], 5)
        # the check is before the first write
        self.assertEqual(port.written, [])
        self.assertEqual(port.polls, 0)

    def test_line_limit_counts_the_line_end(self):
        port = FakeStreamPort()
        self.assertEqual(run(port, ['G' * 79])['status'], 'finished')
        self.assertEqual(run(FakeStreamPort(), ['G' * 80])['status'], 'line_too_long')

    def test_validate_stream_lines(self):
        self.assertIsNone(validate_stream_lines(['G1 X1', 'G' * 79]))
        self.assertEqual(validate_stream_lines(['G1 X1', 'G' * 80, 'G' * 90]), 1)
        # the limit is min(rx_size, GRBL_MAX_LINE)
        self.assertEqual(validate_stream_lines(['G1 X1 Y1'], rx_size=8), 0)
        self.assertIsNone(validate_stream_lines(['G1 X1 Y1'], rx_size=9))
        self.assertEqual(validate_stream_lines(['G' * 80], rx_size=500), 0)
        # encoded bytes, not characters
        self.assertEqual(validate_stream_lines(['(' + '\u00e9' * 40 + ')']), 0)
        self.assertEqual((GRBL_RX_BUFFER, GRBL_MAX_LINE), (127, 80))

    def test_dwell_seconds(self):
        self.assertEqual(dwell_seconds('G4 P60'), 60.0)
        self.assertEqual(dwell_seconds('G04 P0.5'), 0.5)
        self.assertEqual(dwell_seconds('g4p2.5 (wait)'), 2.5)
        self.assertEqual(dwell_seconds('G4'), 0.0)
        self.assertEqual(dwell_seconds('G1 X1 P60'), 0.0)
        self.assertEqual(dwell_seconds('G41 P60'), 0.0)
        self.assertEqual(dwell_seconds('M3 S1000'), 0.0)
        self.assertEqual(dwell_seconds('(G4 P60)'), 0.0)

    def test_timeout(self):
        clock = FakeClock()
        port = TimedPort(clock)
        res = run(port, ['G1 X1'], clock=clock, stall_timeout=30.0)
        self.assertEqual(res['status'], 'timeout')
        self.assertEqual(res['in_flight'], 1)
        self.assertGreater(clock.now, 30.0)
        self.assertLessEqual(clock.now, 32.0)

    def test_status_does_not_refresh_stall(self):
        # an Idle report and an unchanged Run report are not progress
        for report in (lambda now: '<Idle|MPos:0.000,0.000,0.000|FS:0,0>',
                       lambda now: '<Run|MPos:5.000,0.000,0.000|FS:500,0>'):
            clock = FakeClock()
            port = TimedPort(clock, report=report)
            res = run(port, ['G1 X1'], clock=clock, stall_timeout=30.0, poll_status=True)
            self.assertEqual(res['status'], 'timeout')
            self.assertLessEqual(clock.now, 33.0)

    def test_moving_run_refreshes_stall(self):
        clock = FakeClock()
        port = TimedPort(clock, ack_at=100.0, report=lambda now: '<Run|MPos:%.3f,0.000,0.000|FS:500,0>' % now)
        res = run(port, ['G1 X500'], clock=clock, stall_timeout=30.0, poll_status=True)
        self.assertEqual(res['status'], 'finished')

    def test_work_position_run_refreshes_stall(self):
        clock = FakeClock()
        port = TimedPort(clock, ack_at=100.0, report=lambda now: '<Run|WPos:%.3f,0.000,0.000|FS:500,0>' % now)
        res = run(port, ['G1 X500'], clock=clock, stall_timeout=30.0, poll_status=True)
        self.assertEqual(res['status'], 'finished')

    def test_hold_refreshes_stall(self):
        for state in ('Hold:0', 'Door:1', 'Jog', 'Home'):
            clock = FakeClock()
            port = TimedPort(clock, ack_at=100.0, report=lambda now, s=state: '<%s|MPos:0.000,0.000,0.000>' % s)
            res = run(port, ['G1 X1'], clock=clock, stall_timeout=30.0, poll_status=True)
            self.assertEqual(res['status'], 'finished', state)

    def test_long_dwell_polled(self):
        clock = FakeClock()
        port = TimedPort(clock, ack_at=70.0, report=lambda now: '<Idle|MPos:0.000,0.000,0.000|FS:0,0>')
        res = run(port, ['G4 P60'], clock=clock, stall_timeout=30.0, poll_status=True)
        self.assertEqual(res['status'], 'finished')

    def test_dwell_extension_is_set_once_when_polled(self):
        clock = FakeClock()
        port = TimedPort(clock, report=lambda now: '<Idle|MPos:0.000,0.000,0.000|FS:0,0>')
        res = run(port, ['G4 P60'], clock=clock, stall_timeout=30.0, poll_status=True)
        self.assertEqual(res['status'], 'timeout')
        self.assertGreater(clock.now, 90.0)
        self.assertLessEqual(clock.now, 93.0)

    def test_long_dwell_not_polled(self):
        clock = FakeClock()
        port = TimedPort(clock, ack_at=70.0)
        res = run(port, ['G4 P60'], clock=clock, stall_timeout=30.0, poll_status=False)
        self.assertEqual(res['status'], 'finished')
        self.assertEqual(port.polls, 0)
        clock = FakeClock()
        port = TimedPort(clock, ack_at=100.0)
        res = run(port, ['G4 P60'], clock=clock, stall_timeout=30.0, poll_status=False)
        self.assertEqual(res['status'], 'timeout')
        self.assertGreater(clock.now, 90.0)
        self.assertLessEqual(clock.now, 92.0)

    def test_dwell_starts_when_the_g4_is_the_oldest_line(self):
        # not polled: line 0 is acknowledged at 20 s, then the G4 gets its 60 s from that time
        clock = FakeClock()

        class Port(TimedPort):
            def readline(self):
                self.clock.now += self.step
                assert self.clock.now <= self.limit, "the streamer did not time out"
                if self.pending and self.clock.now in (20.0, 100.0):
                    self.pending.pop(0)
                    return b'ok\r\n'
                return b''

        res = run(Port(clock), ['G1 X1', 'G4 P60'], clock=clock, stall_timeout=30.0, poll_status=False)
        self.assertEqual(res['status'], 'finished')


if __name__ == '__main__':
    unittest.main()
