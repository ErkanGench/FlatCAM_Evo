from tclCommands.TclCommand import TclCommand

import collections


class TclCommandSelectProject(TclCommand):
    """
    Tcl shell command that makes a project of the Project tab active.

    example:
        select_project Board_B
    """

    # List of all command aliases, to be able use old names for backward compatibility (add_poly, add_polygon)
    aliases = ['select_project']

    description = '%s %s' % ("--", "Makes the project with the given name the active project.")

    # Dictionary of types from Tcl command, needs to be ordered
    arg_names = collections.OrderedDict([
        ('name', str),
    ])

    # Dictionary of types from Tcl command, needs to be ordered , this  is  for options  like -optionname value
    option_types = collections.OrderedDict([

    ])

    # array of mandatory options for current Tcl command: required = {'name','outname'}
    required = ['name']

    # structured help for current command, args needs to be ordered
    help = {
        'main': 'Makes the project with the given name the active project. '
                'The command fails if no project has that name or if a task is running.',
        'args': collections.OrderedDict([
            ('name', 'Name of the project. Required.'),
        ]),
        'examples': ['select_project Board_B']
    }

    def execute(self, args, unnamed_args):
        """

        :param args:
        :param unnamed_args:
        :return:
        """

        name = str(args['name'])
        ctx = self.app.projects.get_by_name(name)
        if ctx is None:
            self.raise_tcl_error('%s: %s' % ("Project not found", name))
            return 'fail'

        if not self.app.projects.switch(ctx):
            self.raise_tcl_error('%s: %s' % ("Could not select the project. A task is running", name))
            return 'fail'
