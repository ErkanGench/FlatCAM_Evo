import collections
import logging
from copy import deepcopy

import gettext
import appTranslation as fcTranslate
import builtins

from tclCommands.TclCommand import TclCommand

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')

MODES = {'factor': 'factor', 'etchant': 'etch_list', 'manual': 'manual'}


class TclCommandEtchCompensate(TclCommand):
    """
    Tcl shell command to compensate the etching of a Gerber object into a new Gerber object.
    """

    aliases = ['etch_compensate']

    description = '%s %s' % ("--", "Grow the copper of a Gerber object to compensate the etching, into a new object.")

    arg_names = collections.OrderedDict([
        ('name', str),
    ])

    option_types = collections.OrderedDict([
        ('outname', str),
        ('thickness', float),
        ('mode', str),
        ('factor', float),
        ('etchant', str),
        ('offset', float),
    ])

    required = ['name']

    help = {
        'main': "Compensate the etching of a Gerber object: the copper and the apertures are grown by the lateral "
                "undercut and the result is a new Gerber object (the Etch Compensation plugin). The values that "
                "are not given are taken from the plugin defaults.",
        'args': collections.OrderedDict([
            ('name', 'Name of the Gerber object. Required.'),
            ('outname', 'Name of the new object. Default: the name + the plugin suffix.'),
            ('thickness', 'Copper thickness in microns.'),
            ('mode', 'factor, etchant or manual. factor: offset = thickness / etch factor; etchant: the etch '
                     'factor of the etchant; manual: the offset is given.'),
            ('factor', 'Etch factor (depth / lateral undercut), for the factor mode. Must be greater than 0.'),
            ('etchant', 'cucl2, fecl3 or alkaline, for the etchant mode.'),
            ('offset', 'Offset in microns, for the manual mode. Can be negative, not 0.'),
        ]),
        'examples': ['etch_compensate copper.gtl',
                     'etch_compensate copper.gtl -thickness 35 -mode factor -factor 2.5 -outname copper_comp',
                     'etch_compensate copper.gtl -mode etchant -etchant fecl3',
                     'etch_compensate copper.gtl -mode manual -offset 12']
    }

    def execute(self, args, unnamed_args):
        from appPlugins.ToolEtchCompensation import EtchCompensationGen as Gen

        name = str(args['name'])
        source = self.app.collection.get_by_name(name)
        if source is None:
            self.raise_tcl_error('%s: %s' % (_("Object not found"), name))
            return 'fail'
        if getattr(source, 'kind', None) != 'gerber':
            self.raise_tcl_error('%s: %s' % (_("Expected a Gerber object"), name))
            return 'fail'

        def option(key, pref, fallback):
            return args[key] if key in args else self._app_option(pref, fallback)

        mode_in = str(args['mode']).lower() if 'mode' in args else None
        if mode_in is None:
            mode = str(self._app_option('tools_etch_ratio', 'factor'))
        elif mode_in in MODES:
            mode = MODES[mode_in]
        else:
            self.raise_tcl_error('%s: %s' % (_("Unknown mode, use factor, etchant or manual"), mode_in))
            return 'fail'

        try:
            steps = int(self._app_option('gerber_circle_steps', 64))
        except (TypeError, ValueError):
            steps = 64

        try:
            result = Gen.compensate_gerber(
                source.solid_geometry, source.tools, float(option('thickness', 'tools_etch_thickness', 18.0)),
                mode, self.app.app_units, steps,
                factor=float(option('factor', 'tools_etch_factor', 3.0)),
                etchant=str(option('etchant', 'tools_etch_etchant', 'cucl2')).lower(),
                offset_um=float(option('offset', 'tools_etch_offset', 0.0)))
        except (ValueError, TypeError) as err:
            self.raise_tcl_error(str(err))
            return 'fail'
        if result['offset'] == 0:
            self.raise_tcl_error(_("The offset is 0, there is nothing to compensate."))
            return 'fail'

        suffix = str(self._app_option('tools_etch_suffix', '_comp') or '')
        outname = str(args.get('outname') or (name + suffix))
        options = {k: deepcopy(v) for k, v in source.obj_options.items() if k != 'name'}

        def init(new_obj, app_obj):
            new_obj.obj_options.update(options)
            new_obj.obj_options['name'] = outname
            for attr in ('fill_color', 'outline_color'):
                if hasattr(source, attr):
                    setattr(new_obj, attr, deepcopy(getattr(source, attr)))
            new_obj.tools = result['apertures']
            new_obj.solid_geometry = result['solid_geometry']
            new_obj.regenerate_source(name=outname)

        self.check_result(self.app.app_obj.new_object('gerber', outname, init, plot=False))
        return None
