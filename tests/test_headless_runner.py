"""HeadlessRunner on a real Tcl interpreter and a fake app."""

import io
import tkinter
from types import SimpleNamespace
from unittest.mock import Mock

from appCommon.Headless import HeadlessExit, HeadlessRunner


def _app(**options):
    tcl = tkinter.Tcl()
    app = SimpleNamespace(
        shell=SimpleNamespace(tcl=tcl), headless_console=False, headless_exit_code=None,
        cmd_line_shellfile=options.get('shellfile', ''), cmd_line_command=options.get('command', ''),
        shellvar_commands=lambda: options.get('shellvar', []),
        workers=Mock(pending_count=Mock(return_value=0)), pool=Mock(),
    )
    return app


def _run(app, stdin=''):
    out, err = io.StringIO(), io.StringIO()
    code = HeadlessRunner(app, stdin=io.StringIO(stdin), out=out, err=err).run()
    return code, out.getvalue(), err.getvalue()


def test_a_command_runs_and_its_result_is_written():
    code, out, err = _run(_app(command='set a 5; expr {$a * 2}'))
    assert (code, out, err) == (0, '10\n', '')


def test_a_tcl_error_gives_exit_code_1_and_the_report_on_stderr():
    code, out, err = _run(_app(command='no_such_command'))
    assert code == 1
    assert 'invalid command name "no_such_command"' in err


def test_exit_n_gives_exit_code_n_and_stops_the_script():
    code, out, err = _run(_app(command='exit 3; set never 1'))
    assert code == 3
    assert err == ''


def test_quit_app_raising_headless_exit_in_a_callback_ends_the_run():
    app = _app(command='fake_quit; set never 1')

    def fake_quit():
        app.headless_exit_code = 0
        raise HeadlessExit(0)

    app.shell.tcl.createcommand('fake_quit', fake_quit)
    code, out, err = _run(app)
    assert code == 0
    assert app.shell.tcl.eval('info exists never') == '0'


def test_shellvar_then_shellfile_then_command(tmp_path):
    script = tmp_path / 'job.FlatScript'
    # the last command of the file gives an empty result, so only the result of --command is written
    script.write_text('set b "$shellvar_0-file"\nset unused ""\n')
    app = _app(shellvar=['set shellvar_0 "var"'], shellfile=str(script), command='set b')
    code, out, err = _run(app)
    assert (code, out) == (0, 'var-file\n')


def test_the_prompt_reads_complete_commands_from_stdin():
    stdin = 'set x {\n1 2\n}\nllength $x\nno_such_command\nset y 1\n'
    code, out, err = _run(_app(), stdin=stdin)
    assert '2\n' in out
    assert 'invalid command name' in err
    assert code == 1   # a command failed; the prompt went on with the next one


def test_the_prompt_ends_at_exit():
    code, out, err = _run(_app(), stdin='exit 4\nset never 1\n')
    assert code == 4


def test_the_console_is_switched_on_and_the_pool_stopped():
    app = _app(command='set a 1')
    _run(app)
    assert app.headless_console is True
    app.pool.terminate.assert_called_once_with()
    app.workers.quit.assert_called_once_with()
