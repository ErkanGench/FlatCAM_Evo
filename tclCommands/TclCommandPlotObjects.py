# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 8/17/2019                                          #
# MIT Licence                                              #
# ##########################################################

from tclCommands.TclCommand import TclCommand

import collections

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class TclCommandPlotObjects(TclCommand):
    """
    Tcl shell command to update the plot on the user interface.

    example:
        plot
    """

    # List of all command aliases, to be able use old names for backward compatibility (add_poly, add_polygon)
    aliases = ['plot_objects']
    valueless_options = frozenset({'plot_status'})

    description = '%s %s' % ("--", "Plot a specified list of objects in appGUI.")

    # Dictionary of types from Tcl command, needs to be ordered
    arg_names = collections.OrderedDict([
        ('names', str)
    ])

    # Dictionary of types from Tcl command, needs to be ordered , this  is  for options  like -optionname value
    option_types = collections.OrderedDict([
        ('plot_status', str)
    ])

    # array of mandatory options for current Tcl command: required = {'name','outname'}
    required = ['names']

    # structured help for current command, args needs to be ordered
    help = {
        'main': "Plot a specified list of objects in appGUI.",
        'args': collections.OrderedDict([
            ('names', "A list of object names to be plotted separated by comma. Required.\n"
                      "WARNING: no spaces are allowed. If unsure enclose the entire list with quotes."),
            ('plot_status', 'Display objects: True (1) or False (0). Bare -plot_status means True; '
                            'if omitted, objects are plotted by default.')
        ]),
        'examples': ["plot_objects gerber_obj.GRB,excellon_obj.DRL"]
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

        if 'plot_status' in args:
            if args['plot_status'] is None:
                plot_status = True
            else:
                plot_status = self.parse_bool(args['plot_status'])
        else:
            plot_status = True

        names = [x.strip() for x in args['names'].split(",") if x != '']
        objs = []
        for name in names:
            obj = self.app.collection.get_by_name(name)
            if obj is None or obj.kind not in ('geometry', 'gerber', 'excellon', 'cncjob'):
                self.raise_tcl_error('Plot object not found or unsupported: %s' % name)
            objs.append(obj)

        for obj in objs:
            obj.obj_options['plot'] = plot_status
            obj.plot()
