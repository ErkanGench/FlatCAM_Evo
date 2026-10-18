from tclCommands.TclCommand import TclCommand

import collections


class TclCommandListProjects(TclCommand):
    """
    Tcl shell command that returns the names of the projects in the Project tab.

    example:
        list_projects
    """

    # List of all command aliases, to be able use old names for backward compatibility (add_poly, add_polygon)
    aliases = ['list_projects']
    returns_value = True

    description = '%s %s' % ("--", "Return to TCL the list of the project names "
                                   "as a string with names separated by the '\\n' char.")

    # Dictionary of types from Tcl command, needs to be ordered
    arg_names = collections.OrderedDict([

    ])

    # Dictionary of types from Tcl command, needs to be ordered , this  is  for options  like -optionname value
    option_types = collections.OrderedDict([

    ])

    # array of mandatory options for current Tcl command: required = {'name','outname'}
    required = []

    # structured help for current command, args needs to be ordered
    help = {
        'main': 'Lists the names of the projects in the Project tab, in the order of the Project combobox. '
                'It returns a string with names separated by "\\n" character',
        'args': collections.OrderedDict([

        ]),
        'examples': ['list_projects']
    }

    def execute(self, args, unnamed_args):
        """

        :param args:
        :param unnamed_args:
        :return:
        """

        return '\n'.join(self.app.projects.names())
