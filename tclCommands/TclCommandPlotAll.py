from tclCommands.TclCommand import TclCommandSignaled

import collections

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class TclCommandPlotAll(TclCommandSignaled):
    """
    Tcl shell command to update the plot on the user interface.

    example:
        plot
    """

    # List of all command aliases, to be able use old names for backward compatibility (add_poly, add_polygon)
    aliases = ['plot_all']
    valueless_options = frozenset({'plot_status'})

    description = '%s %s' % ("--", "Plots all objects on appGUI.")

    # Dictionary of types from Tcl command, needs to be ordered
    arg_names = collections.OrderedDict([

    ])

    # Dictionary of types from Tcl command, needs to be ordered , this  is  for options  like -optionname value
    option_types = collections.OrderedDict([
        ('plot_status', str),
        ('use_thread', str)
    ])

    # array of mandatory options for current Tcl command: required = {'name','outname'}
    required = []

    # structured help for current command, args needs to be ordered
    help = {
        'main': "Plots all objects on appGUI.",
        'args': collections.OrderedDict([
            ('plot_status', 'Display objects: True (1) or False (0). Bare -plot_status means True; '
                            'if omitted, objects are plotted by default.'),
            ('use_thread', 'Accepts True (1) or False (0); a value is required. '
                           'Plotting runs in the command worker regardless of this value.')
        ]),
        'examples': ['plot_all', 'plot_all -plot_status False']
    }

    def execute(self, args, unnamed_args):
        """

        :param args:
        :param unnamed_args:
        :return:
        """

        if getattr(self.app, 'headless', False) is True:
            # headless mode: there is no canvas, and a Tcl command makes no plot anyway
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Headless mode: nothing is plotted."))
            return

        if 'use_thread' in args:
            try:
                par = args['use_thread'].capitalize()
            except AttributeError:
                par = args['use_thread']
            threaded = self.parse_bool(par)
        else:
            threaded = False

        plot_status = True
        if 'plot_status' in args:
            try:
                if args['plot_status'] is None:
                    plot_status = True
                else:
                    try:
                        par = args['plot_status'].capitalize()
                    except AttributeError:
                        par = args['plot_status']
                    plot_status = self.parse_bool(par)
            except KeyError:
                plot_status = True

        for obj in self.app.collection.get_list():
            obj.obj_options["plot"] = True if plot_status is True else False

        # Already executed by TclCommandSignaled's worker; don't finish before a nested worker plots.
        return self.app.plot_all(use_thread=False)
