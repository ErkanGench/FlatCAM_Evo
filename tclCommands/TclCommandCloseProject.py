from tclCommands.TclCommand import TclCommand

import collections


class TclCommandCloseProject(TclCommand):
    """
    Tcl shell command that closes and removes a project of the Project tab.

    example:
        close_project Board_B -force 1
    """

    # List of all command aliases, to be able use old names for backward compatibility (add_poly, add_polygon)
    aliases = ['close_project']

    description = '%s %s' % ("--", "Closes and removes a project. Without a name, it closes the active project.")

    # Dictionary of types from Tcl command, needs to be ordered
    arg_names = collections.OrderedDict([
        ('name', str),
    ])

    # Dictionary of types from Tcl command, needs to be ordered , this  is  for options  like -optionname value
    option_types = collections.OrderedDict([
        ('force', str),
    ])

    # array of mandatory options for current Tcl command: required = {'name','outname'}
    required = []

    # structured help for current command, args needs to be ordered
    help = {
        'main': 'Closes and removes a project. There is no dialog. '
                'If the project has unsaved changes, the command fails unless -force is True. '
                'If the last project is closed, 1 empty project replaces it.',
        'args': collections.OrderedDict([
            ('name', 'Name of the project. If not given, the active project is closed.'),
            ('force', 'Close a project with unsaved changes; the changes are lost.\n'
                      'Can be used without value which will be auto assumed to be True.\n'
                      'Or it can have a value: True (1) or False (0).'),
        ]),
        'examples': ['close_project\n'
                     'close_project Board_B\n'
                     'close_project Board_B -force 1']
    }

    def execute(self, args, unnamed_args):
        """

        :param args:
        :param unnamed_args:
        :return:
        """

        projects = self.app.projects

        if 'name' in args:
            name = str(args['name'])
            ctx = projects.get_by_name(name)
            if ctx is None:
                self.raise_tcl_error('%s: %s' % ("Project not found", name))
                return 'fail'
        else:
            ctx = projects.active

        is_forced = False
        if 'force' in args:
            value = args['force']
            is_forced = value is None or str(value).strip().lower() in ('1', 'true', 'yes')

        if projects.is_dirty(ctx) and not is_forced:
            self.raise_tcl_error('%s: %s. %s' % ("The project has unsaved changes", ctx.name,
                                                 "Use -force 1 to close it."))
            return 'fail'

        if not projects.close(ctx, force=True):
            self.raise_tcl_error('%s: %s' % ("Could not close the project. A task is running", ctx.name))
            return 'fail'
