"""Helpers of tests/test_grbl_stream_abort.py and tests/test_grbl_check_mode.py (no tests here)."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from types import SimpleNamespace
from unittest.mock import MagicMock

from tests.test_levelling_audit import make_audit_tool, FakeGrbl, emitted


def gcode(count):
    """`count` short G-code lines: 22 characters, 23 bytes with the line end (5 fit in the GRBL buffer)."""
    return '\n'.join('G1 X%02d.000 Y0.000 F100' % i for i in range(count)) + '\n'


def make_stream_tool(fake, source=None, check_mode=False):
    """A ToolGrblSender (make_audit_tool) on the fake port. The stream worker runs inline in on_start()."""
    tool = make_audit_tool()
    tool.grbl_ser_port = fake
    tool._grbl_connected = True
    tool.app.options = {'tools_grbl_status_ms': 20}
    tool.app.worker_task.emit.side_effect = lambda task: task['fcn']()
    tool.job_lines = []
    tool.job_line_numbers = []
    tool.job_target_name = None
    tool._last_wco = None
    tool._stream_result = {}
    target = SimpleNamespace(kind='cncjob', source_file=source if source is not None else gcode(10),
                             obj_options={'name': 'job'})
    tool.app.collection.get_by_name.return_value = target
    tool.ui.check_mode_cb.get_value.return_value = check_mode
    # the GUI slot runs at once, so the messages of the end of the job can be checked
    tool.stream_ended_sig.emit.side_effect = tool._on_stream_ended
    return tool


def ended_how(tool):
    """The `how` of the last stream_ended_sig.emit()."""
    return tool.stream_ended_sig.emit.call_args.args[0]


def has_success(tool):
    return any('[success]' in text for text in emitted(tool))


class CheckFake(FakeGrbl):
    """A FakeGrbl with the $C command of GRBL 1.1.

    $C enters check mode ([MSG:Enabled], state Check). In check mode, $C leaves it: GRBL resets and
    answers `exit_lines`; the state is then `after_exit_state`. `one_chunk`: the exit lines come in 1 chunk.
    `mute_status_after_exit`: no status report after the exit. `exiting`: True after the exit command."""

    def __init__(self, in_check=False, **kwargs):
        super().__init__(**kwargs)
        self.in_check = in_check
        if in_check:
            self.state = 'Check'
        self.after_exit_state = 'Idle'
        self.exit_lines = ['[MSG:Disabled]', 'ok', "Grbl 1.1h ['$' for help]"]
        self.one_chunk = False
        self.mute_status_after_exit = False
        self.exiting = False

    def _answer(self, cmd):
        if cmd == '$C':
            if not self.in_check:
                self.in_check = True
                self.state = 'Check'
                self._send('[MSG:Enabled]', 'ok')
                return
            self.in_check = False
            self.exiting = True
            self.state = self.after_exit_state
            if self.one_chunk:
                self.rx.append(b''.join(line.encode('utf-8') + b'\r\n' for line in self.exit_lines))
            else:
                self._send(*self.exit_lines)
            return
        if cmd == '?' and self.exiting and self.mute_status_after_exit:
            return
        super()._answer(cmd)
