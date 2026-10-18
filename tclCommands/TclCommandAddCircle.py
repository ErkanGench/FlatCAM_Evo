import collections
import math
from tclCommands.TclCommand import TclCommand


class TclCommandAddCircle(TclCommand):
    """
    Tcl shell command to creates a circle in the given Geometry object.

    example:

    """

    # List of all command aliases, to be able use old names for backward compatibility (add_poly, add_polygon)
    aliases = ['add_circle']

    description = '%s %s' % ("--", "Creates a circle in the given Geometry object.")

    # Dictionary of types from Tcl command, needs to be ordered
    arg_names = collections.OrderedDict([
        ('name', str),
        ('center_x', float),
        ('center_y', float),
        ('radius', float)
    ])

    # Dictionary of types from Tcl command, needs to be ordered , this  is  for options  like -optionname value
    option_types = collections.OrderedDict([

    ])

    # array of mandatory options for current Tcl command: required = {'name','outname'}
    required = ['name', 'center_x', 'center_y', 'radius']

    # structured help for current command, args needs to be ordered
    help = {
        'main': "Creates a circle in the given Geometry object.",
        'args': collections.OrderedDict([
            ('name', 'Name of the geometry object to which to append the circle.'),
            ('center_x', 'X coordinate of the center of the circle.'),
            ('center_y', 'Y coordinates of the center of the circle.'),
            ('radius', 'Radius of the circle.')
        ]),
        'examples': ['add_circle geo_name 1.0 2.0 3']
    }

    def execute(self, args, unnamed_args):
        """

        :param args:
        :param unnamed_args:
        :return:
        """

        name = args['name']
        center_x = args['center_x']
        center_y = args['center_y']
        radius = args['radius']
        if unnamed_args:
            self.raise_tcl_error('Too many arguments. Expected name center_x center_y radius.')
        if not all(math.isfinite(v) for v in (center_x, center_y, radius)) or radius <= 0:
            self.raise_tcl_error('Circle coordinates must be finite and radius must be positive.')

        try:
            obj = self.app.collection.get_by_name(str(name))
        except Exception:
            self.raise_tcl_error("Could not retrieve object: %s" % name)
        if obj is None:
            self.raise_tcl_error("Object not found: %s" % name)
        if obj.kind != 'geometry':
            self.raise_tcl_error('Expected Geometry, got %s %s.' % (name, type(obj)))

        return self.check_result(obj.add_circle([float(center_x), float(center_y)], float(radius)))
