from tclCommands.TclCommand import TclCommandSignaled

import collections
import threading
from PyQt6 import QtCore
import builtins
import gettext

if '_' not in builtins.__dict__:
    _ = gettext.gettext


class TclCommandOpenProject(TclCommandSignaled):
    """
    Tcl shell command to open an application project.
    """

    # array of all command aliases, to be able use  old names for backward compatibility (add_poly, add_polygon)
    aliases = ['open_project']

    description = '%s %s' % ("--", "Opens an application project file, parse it and recreate all the objects.")

    # Dictionary of types from Tcl command, needs to be ordered.
    # For positional arguments
    arg_names = collections.OrderedDict([
        ('filename', str)
    ])

    # Dictionary of types from Tcl command, needs to be ordered.
    # For options like -optionname value
    option_types = collections.OrderedDict([

    ])

    # array of mandatory options for current Tcl command: required = {'name','outname'}
    required = ['filename']

    # structured help for current command, args needs to be ordered
    help = {
        'main': "Opens an application project file, parse it and recreate all the objects.",
        'args': collections.OrderedDict([
            ('filename', 'Absolute path to file to open. Required.\n'
                         'WARNING: no spaces are allowed. If unsure enclose the entire path with quotes.'),
        ]),
        'examples': ['open_project D:\\my_project_file.FlatPrj',
                     'open_project "D:\\my_project_file with spaces in the name.FlatPrj"']
    }

    def execute(self, args, unnamed_args):
        """
        execute current TCL shell command

        :param args: array of known named arguments and options
        :param unnamed_args: array of other values which were passed into command
            without -somename and  we do not have them in known arg_names
        :return: None or exception
        """
        filename = args['filename']
        # if ' ' in filename:
        #     return "The absolute path to the project file contain spaces which is not allowed.\n" \
        #            "Please enclose the path within quotes."

        handlers = self.app.f_handlers
        done = threading.Event()
        result = {}

        def on_done(success, loaded_name, skipped):
            if done.is_set():
                return
            result.update(success=success, skipped=skipped, reason=getattr(handlers, 'last_load_error', ''))
            done.set()

        # this runs in a worker: the load runs in the GUI thread and emits project_load_done once at its end
        # direct: this worker blocks below and could not run a queued call
        handlers.project_load_done.connect(on_done, QtCore.Qt.ConnectionType.DirectConnection)
        try:
            ret = handlers.open_project(filename, cli=True, plot=False, from_tcl=True)
            # only a queued request (True) emits project_load_done; an explicit result of the handler is the answer
            if ret is not True and not done.is_set():
                return ret
            timeout = self._app_option('global_background_timeout')
            if not done.wait(int(timeout) / 1000.0 if timeout else 600.0):
                self.raise_tcl_error(_("Timed out while opening the project file: %s") % filename)
        finally:
            handlers.project_load_done.disconnect(on_done)

        if not result['success']:
            text = '%s: %s' % (_("Failed to open project file"), filename)
            if result.get('reason'):
                text = '%s. %s' % (text, result['reason'])
            self.raise_tcl_error(text)
        if result['skipped']:
            return '%s %s' % (_("Project opened. These objects could not be loaded:"), ', '.join(result['skipped']))
        return None
