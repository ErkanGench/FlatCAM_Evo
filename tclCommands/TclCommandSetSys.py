from tclCommands.TclCommand import TclCommand

import collections
import math
import ast


class TclCommandSetSys(TclCommand):
    """
    Tcl shell command to set the value of a system variable

    example:

    """

    # List of all command aliases, to be able use old names for backward compatibility (add_poly, add_polygon)
    aliases = ['set_sys', 'setsys']

    description = '%s %s' % ("--", "Sets the value of the specified system variable.")

    # Dictionary of types from Tcl command, needs to be ordered
    arg_names = collections.OrderedDict([
        ('name', str),
        ('value', str)
    ])

    # Dictionary of types from Tcl command, needs to be ordered , this  is  for options  like -optionname value
    option_types = collections.OrderedDict([

    ])

    # array of mandatory options for current Tcl command: required = {'name','outname'}
    required = ['name', 'value']

    # structured help for current command, args needs to be ordered
    help = {
        'main': "Sets the value of the specified system variable.",
        'args': collections.OrderedDict([
            ('name', 'Name of the system variable. Required.'),
            ('value', 'Value to set.')
        ]),
        'examples': ['set_sys global_gridx 1.0']
    }

    def execute(self, args, unnamed_args):
        """

        :param args:
        :param unnamed_args:
        :return:
        """

        param = args['name']
        value = args['value']

        if param in self.app.options:
            current = self.app.options[param]
            try:
                if isinstance(current, bool):
                    value = TclCommand.parse_bool(value)
                elif isinstance(current, int):
                    value = int(value)
                elif isinstance(current, float):
                    value = float(value)
                    if not math.isfinite(value):
                        raise ValueError('Expected a finite number')
                elif isinstance(current, str):
                    value = str(value)
                    if param == 'units' or param.endswith('_units'):
                        value = value.upper()
                        if value not in ('MM', 'IN'):
                            raise ValueError('Expected MM or IN')
                    elif param.endswith('_zeros') and current in ('L', 'T'):
                        value = value.upper()
                        if value not in ('L', 'T'):
                            raise ValueError('Expected L or T')
                elif current is None:
                    value = None if str(value).lower() == 'none' else ast.literal_eval(str(value))
                    if value is not None and (not isinstance(value, (int, float, bool)) or not math.isfinite(value)):
                        raise ValueError('Expected None or a finite number')
                elif isinstance(current, (list, tuple, dict)):
                    value = ast.literal_eval(str(value))
                    if not isinstance(value, type(current)):
                        raise ValueError('Expected %s' % type(current).__name__)
            except (ValueError, TypeError, SyntaxError) as err:
                self.raise_tcl_error('Invalid value for %s: %s' % (param, err))
                return 'fail'

            self.app.options[param] = value
            self.app.defaults.propagate_defaults()

        else:
            self.raise_tcl_error("No such system parameter \"{}\".".format(param))
