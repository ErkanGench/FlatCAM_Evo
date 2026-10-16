from unittest.mock import Mock

from tclCommands.TclCommandOpenGerber import TclCommandOpenGerber


def test_missing_filename_reports_error_without_crashing():
    command = TclCommandOpenGerber.__new__(TclCommandOpenGerber)
    command.raise_tcl_error = Mock()

    args, unnamed_args = command.check_args(())
    command.execute(args, unnamed_args)

    command.raise_tcl_error.assert_called_once_with("Missing required argument 'filename'.")
