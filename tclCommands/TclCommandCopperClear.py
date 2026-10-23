from tclCommands.TclCommand import TclCommand
from appPlugins.ToolNCC.NccGen import NccGen

import collections
import math
import logging

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class TclCommandCopperClear(TclCommand):
    """
    Clear the non-copper areas.
    """

    # Array of all command aliases, to be able to use old names for backward compatibility (add_poly, add_polygon)
    aliases = ['ncc_clear', 'ncc']
    valueless_options = frozenset({'all'})

    description = '%s %s' % ("--", "Clear excess copper.")

    # dictionary of types from Tcl command, needs to be ordered
    arg_names = collections.OrderedDict([
        ('name', str),
    ])

    # dictionary of types from Tcl command, needs to be ordered , this  is  for options  like -optionname value
    option_types = collections.OrderedDict([
        ('tooldia', str),
        ('overlap', float),
        ('order', str),
        ('margin', float),
        ('method', str),
        ('connect', str),
        ('contour', str),
        ('offset', float),
        ('rest', str),
        ('all', int),
        ('ref', str),
        ('box', str),
        ('outname', str),
    ])

    # array of mandatory options for current Tcl command: required = {'name','outname'}
    required = ['name']

    # structured help for current command, args needs to be ordered
    help = {
        'main': "Clear excess copper in polygons. Basically it's a negative Paint.",
        'args': collections.OrderedDict([
            ('name', 'Name of the source Geometry object. String.'),
            ('tooldia', 'Diameter of the tool to be used. Can be a comma separated list of diameters.\n'
                        'WARNING: No space is allowed between tool diameters. E.g: correct: 0.5,1 / incorrect: 0.5, 1'),
            ('overlap', 'Percentage of tool diameter to overlap current pass over previous pass. Float [0, 99.9999]\n'
                        'E.g: for a 25% from tool diameter overlap use -overlap 25'),
            ('margin', 'Bounding box margin. Float number.'),
            ('order', 'Can have the values: "no", "fwd" and "rev". String.'
                      'It is useful when there are multiple tools in tooldia parameter.'
                      '"no" -> the order used is the one provided.'
                      '"fwd" -> tools are ordered from smallest to biggest.'
                      '"rev" -> tools are ordered from biggest to smallest.'),
            ('method', 'Algorithm for copper clearing. Can be: "standard", "seed" or "lines".'),
            ('connect', 'Draw lines to minimize tool lifts. True (1) or False (0)'),
            ('contour', 'Cut around the perimeter of the painting. True (1) or False (0)'),
            ('rest', 'Use rest-machining. True (1) or False (0)'),
            ('offset', 'If used, the copper clearing will finish to a distance from copper features. Float number.'),
            ('all', 'Clear the whole object. Bare -all or -all 1 selects this mode; -all 0 does not. '
                    'Select exactly one mode: all or -box <value>.'),
            ('box', 'Name of the reference object. Requires a value. Select exactly one mode: '
                    '-all (or -all 1) or -box <value>.'),
            ('outname', 'Name of the resulting Geometry object. String. No spaces.'),
        ]),
        'examples': ["ncc obj_name -tooldia 0.3,1 -overlap 10 -margin 1.0 -method 'lines' -all"]
    }

    def execute(self, args, unnamed_args):
        """
        execute current TCL shell command

        :param args: array of known named arguments and options
        :param unnamed_args: array of other values which were passed into command
            without -somename, and  we do not have them in known arg_names
        :return: None or exception
        """

        name = args['name']
        if 'ref' in args:
            if 'box' in args:
                self.raise_tcl_error('Use only one reference object: -box or -ref.')
            args['box'] = args.pop('ref')
        all_selected = 'all' in args and (args['all'] is None or self.parse_bool(args['all']))
        if all_selected == ('box' in args):
            self.raise_tcl_error('Expected exactly one of -all or -box <object>.')

        # Get source object.
        try:
            obj = self.app.collection.get_by_name(str(name))
        except Exception as e:
            self.app.log.error("TclCommandCopperClear.execute() --> %s" % str(e))
            self.raise_tcl_error("%s: %s" % (_("Could not retrieve object"), name))
            return "Could not retrieve object: %s" % name

        if obj is None or obj.kind not in ('geometry', 'gerber'):
            self.raise_tcl_error('Expected an existing Gerber or Geometry object: %s' % name)

        if 'tooldia' in args:
            tooldia = str(args['tooldia'])
        else:
            tooldia = str(self._app_option("tools_ncc_tools"))

        if 'overlap' in args:
            overlap = float(args['overlap']) / 100.0
        else:
            overlap = float(self._app_option("tools_ncc_overlap")) / 100.0

        if 'order' in args:
            order = args['order']
        else:
            order = str(self._app_option("tools_ncc_order"))
        orders = {'no': 0, 'fwd': 1, 'rev': 2, '0': 0, '1': 1, '2': 2}
        if str(order).lower() not in orders:
            self.raise_tcl_error('Order must be no, fwd or rev.')
        order = orders[str(order).lower()]

        if 'margin' in args:
            margin = float(args['margin'])
        else:
            margin = float(self._app_option("tools_ncc_margin"))

        if 'method' in args:
            method = args['method']
            if method == "standard":
                method_data = 0
            elif method == "seed":
                method_data = 1
            elif method == "lines":
                method_data = 2
            else:
                self.raise_tcl_error("Supported methods are: 'standard', 'seed' and 'lines'.")
        else:
            method = int(self._app_option("tools_ncc_method"))
            method_data = method
        if method_data not in (0, 1, 2):
            self.raise_tcl_error('Unsupported copper clearing method.')

        if 'connect' in args:
            try:
                par = args['connect'].capitalize()
            except AttributeError:
                par = args['connect']
            connect = self.parse_bool(par)
        else:
            connect = self.parse_bool(self._app_option('tools_ncc_connect'))

        if 'contour' in args:
            try:
                par = args['contour'].capitalize()
            except AttributeError:
                par = args['contour']
            contour = self.parse_bool(par)
        else:
            contour = self.parse_bool(self._app_option('tools_ncc_contour'))

        offset = 0.0
        if 'offset' in args:
            offset = float(args['offset'])
            has_offset = True
        else:
            has_offset = False

        try:
            tools = [float(dia) for dia in tooldia.split(",") if dia.strip()]
        except AttributeError:
            tools = [float(tooldia)]

        if 'rest' in args:
            try:
                par = args['rest'].capitalize()
            except AttributeError:
                par = args['rest']
            rest = self.parse_bool(par)
        else:
            rest = self.parse_bool(self._app_option('tools_ncc_rest'))
        if not tools or any(not math.isfinite(dia) or dia <= 0 for dia in tools) or not 0 <= overlap < 1:
            self.raise_tcl_error('Tool diameters must be positive and finite; overlap must be in [0, 100).')

        if 'outname' in args:
            outname = args['outname']
        else:
            if rest is True:
                outname = name + "_ncc"
            else:
                outname = name + "_ncc_rm"

        # used only to have correct information's in the obj.tools[tool]['data'] dict
        if all_selected:
            select = 0  # 'ITSELF
        else:
            select = 2  # 'REFERENCE Object'

        # store here the default data for Geometry Data
        default_data = self.app.options.copy()
        default_data.update({
            "name":             outname,
            "plot":             False,
            "tooldia": tooldia,

            "tools_ncc_margin":             margin,
            "tools_ncc_method":             method_data,
            "tools_ncc_ref":                select,
            "tools_ncc_connect":            connect,
            "tools_ncc_contour":            contour,
            "tools_ncc_overlap":            overlap,

            "seg_x":                         self._app_option("geometry_seg_x"),
            "seg_y":                         self._app_option("geometry_seg_y")
        })
        ncc_tools = {}

        tool_uid = 0
        for tool in tools:
            tool_uid += 1
            ncc_tools.update({
                int(tool_uid): {
                    'tooldia':          float('%.*f' % (obj.decimals, tool)),
                    'data':             dict(default_data),
                    'solid_geometry':   []
                }
            })
            ncc_tools[int(tool_uid)]['data']['tooldia'] = self.app.dec_format(tool, obj.decimals)

        if self.app.ncclear_tool.gen is None:
            self.app.ncclear_tool.gen = NccGen(self.app.ncclear_tool)

        # Non-Copper clear all polygons in the non-copper clear object
        if select == 0:     # 'all' in args
            return self.app.ncclear_tool.gen.clear_copper_tcl(
                ncc_obj=obj,
                select_method=0,     # ITSELF
                ncc_tooldia=tooldia,
                overlap=overlap,
                order=order,
                margin=margin,
                has_offset=has_offset,
                offset=offset,
                method=method_data,
                outname=outname,
                connect=connect,
                contour=contour,
                rest=rest,
                tools_storage=ncc_tools,
                plot=False,
                run_threaded=False,
            )
            return

        # Non-Copper clear all polygons found within the box object from the non_copper cleared object
        if select == 2:   # Reference Object 'box' in args
            box_name = args['box']

            # Get box source object.
            try:
                box_obj = self.app.collection.get_by_name(str(box_name))
            except Exception as e:
                self.app.log.error("TclCommandCopperClear.execute() --> %s" % str(e))
                self.app.log.error("Could not retrieve object: %s" % name)
                self.raise_tcl_error("%s: %s" % (_("Could not retrieve object"), name))
                return "fail"

            if box_obj is None or box_obj.kind not in ('geometry', 'gerber'):
                self.raise_tcl_error('Reference object not found or unsupported: %s' % box_name)
            return self.app.ncclear_tool.gen.clear_copper_tcl(
                ncc_obj=obj,
                sel_obj=box_obj,
                select_method=2,     # REFERENCE OBJECT
                ncc_tooldia=tooldia,
                overlap=overlap,
                order=order,
                margin=margin,
                has_offset=has_offset,
                offset=offset,
                method=method_data,
                outname=outname,
                connect=connect,
                contour=contour,
                rest=rest,
                tools_storage=ncc_tools,
                plot=False,
                run_threaded=False,
            )
            return

        # if the program reached this then it's an error because neither -all nor -box <value> was used.
        self.app.log.error("Expected either -box <value> or -all. Copper clearing failed.")
        self.raise_tcl_error('%s' % _("Expected either -box <value> or -all."))
        return "fail"
