import collections
import datetime
import logging

import gettext
import appTranslation as fcTranslate
import builtins

from appHandlers.appHistory import history_of
from camlib import flatten_shapely_geometry, object_circle_steps
from tclCommands.TclCommand import TclCommand

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')

TRUE_WORDS = ('1', 'true', 'yes', 'on')
FALSE_WORDS = ('0', 'false', 'no', 'off', '')


class TclCommandQRCode(TclCommand):
    """
    Tcl shell command to insert a QR Code in a Gerber object or to create a new Gerber object with it.
    """

    aliases = ['qrcode']

    description = '%s %s' % ("--", "Insert a QR Code in a Gerber object or create a new Gerber object with it.")

    arg_names = collections.OrderedDict([
        ('name', str)
    ])

    option_types = collections.OrderedDict([
        ('data', str),
        ('x', float),
        ('y', float),
        ('version', int),
        ('error', str),
        ('box_size', float),
        ('border', int),
        ('polarity', str),
        ('rounded', str),
        ('rotation', int),
        ('mirror', str),
        ('anchor', str),
        ('margin', float),
        ('output', str),
        ('outname', str),
        ('serial', int),
        ('serial_pad', int),
        ('mask_pattern', str),
    ])

    required = ['data']

    help = {
        'main': "Insert a QR Code in a Gerber object (output source, undoable) or create a new Gerber object "
                "that contains only the QR Code (output new). The values that are not given are taken from the "
                "QR Code plugin defaults. The position (-x, -y) is in the units of the application; for a PCB "
                "document target (-output source) it is in the units of that object.",
        'args': collections.OrderedDict([
            ('name', 'Name of the target Gerber object. Required for -output source.'),
            ('data', 'Text of the QR Code. Tokens: {date} {time} {project} {object} {serial}.'),
            ('x', 'X coordinate of the anchor. Default 0.'),
            ('y', 'Y coordinate of the anchor. Default 0.'),
            ('version', 'QR version 1..40. 0 means automatic.'),
            ('error', 'Error correction level: L, M, Q or H.'),
            ('box_size', 'Size of a module in tenths of a millimeter (the plugin Box Size).'),
            ('border', 'Border in modules (the quiet zone). Minimum 0.'),
            ('polarity', 'pos: the QR is copper. neg: the QR is cleared out of the copper.'),
            ('rounded', 's: square modules. r: rounded modules.'),
            ('rotation', 'Counter-clockwise rotation: 0, 90, 180 or 270.'),
            ('mirror', 'Mirror about the vertical axis (for a bottom layer): 0 or 1.'),
            ('anchor', 'Point of the QR placed at x, y: bl, tl, br, tr or c.'),
            ('margin', 'Clearance around the QR. 0 or not given: border * module size.'),
            ('output', 'source: modify the Gerber (default). new: create a new Gerber object.'),
            ('outname', 'Name of the new Gerber object, for -output new.'),
            ('serial', 'Value of the {serial} token. Default: the plugin Serial start.'),
            ('serial_pad', 'Zero padding width of the {serial} token. Default: the plugin Serial pad.'),
            ('mask_pattern', 'QR mask pattern 0..7, or auto.'),
        ]),
        'examples': ['qrcode board.gtl -data "{object} {serial}" -x 10 -y 10 -serial 7 -version 0 -anchor c',
                     'qrcode -data "hello" -output new -outname qr_label']
    }

    def execute(self, args, unnamed_args):
        from appPlugins.ToolQRCode import QRCodeGen as Gen

        if unnamed_args:
            self.raise_tcl_error(_("Too many arguments. Correct format: qrcode name -data text [options]"))
            return 'fail'

        options = getattr(self.app, 'options', None) or {}

        def pick(key, pref, cast, default):
            """The given argument, else the plugin default, else the fallback."""
            if key in args and args[key] is not None:
                return args[key]
            try:
                return cast(options.get(pref, default))
            except (TypeError, ValueError):
                return default

        data = str(args.get('data', ''))
        if data == '':
            self.raise_tcl_error(_("There is no QRCode Data."))
            return 'fail'

        output = str(args.get('output', 'source')).lower()
        if output not in ('source', 'new'):
            self.raise_tcl_error('%s: %s' % (_("Unknown output"), output))
            return 'fail'

        obj = None
        name = args.get('name')
        if output == 'source' or name:
            if not name:
                self.raise_tcl_error(_("The name of the target Gerber object is required."))
                return 'fail'
            obj = self.app.collection.get_by_name(str(name))
            if obj is None:
                self.raise_tcl_error('%s: %s' % (_("Object not found"), name))
                return 'fail'
            if getattr(obj, 'kind', 'gerber') != 'gerber':
                self.raise_tcl_error('%s: %s' % (_("Not a Gerber object"), name))
                return 'fail'

        mirror_text = str(args.get('mirror', options.get('tools_qrcode_mirror', '0'))).lower()
        if mirror_text not in TRUE_WORDS + FALSE_WORDS:
            self.raise_tcl_error('%s: %s' % (_("Mirror must be 0 or 1"), mirror_text))
            return 'fail'
        mirror = mirror_text in TRUE_WORDS

        version = int(pick('version', 'tools_qrcode_version', int, 0))
        error = str(pick('error', 'tools_qrcode_error', str, 'L')).upper()
        box_size = float(pick('box_size', 'tools_qrcode_box_size', float, 3.0))
        border = int(pick('border', 'tools_qrcode_border_size', int, 4))
        polarity = str(pick('polarity', 'tools_qrcode_polarity', str, 'pos')).lower()
        rounded = str(pick('rounded', 'tools_qrcode_rounded', str, 's')).lower()
        rotation = int(pick('rotation', 'tools_qrcode_rotation', int, 0))
        anchor = str(pick('anchor', 'tools_qrcode_anchor', str, 'bl')).lower()
        margin = args['margin'] if 'margin' in args else options.get('tools_qrcode_margin')
        try:
            margin = float(margin) if margin not in (None, '') else None
        except (TypeError, ValueError):
            margin = None
        if margin is not None and margin <= 0:
            margin = None

        if error not in ('L', 'M', 'Q', 'H'):
            self.raise_tcl_error('%s: %s' % (_("Error correction must be L, M, Q or H"), error))
            return 'fail'
        if polarity not in ('pos', 'neg'):
            self.raise_tcl_error('%s: %s' % (_("Polarity must be pos or neg"), polarity))
            return 'fail'
        if rounded not in ('s', 'r'):
            self.raise_tcl_error('%s: %s' % (_("Rounded must be s or r"), rounded))
            return 'fail'
        if border < 0 or box_size <= 0 or not 0 <= version <= 40:
            self.raise_tcl_error(_("Invalid version, box size or border."))
            return 'fail'

        units = str(getattr(self.app, 'app_units', 'MM')).upper()
        if output == 'source' and obj.obj_options.get('pcbdoc_import'):
            units = str(obj.units).upper()  # the units of a PCB document import are the object units
        pos = (float(args.get('x', 0.0)), float(args.get('y', 0.0)))

        project = getattr(self.app, 'project_filename', None)
        if project:
            import os
            project = os.path.splitext(os.path.basename(str(project)))[0]
        now = datetime.datetime.now()
        serial = args['serial'] if 'serial' in args and args['serial'] is not None else \
            pick('serial', 'tools_qrcode_serial_start', int, 0)
        serial_pad = int(pick('serial_pad', 'tools_qrcode_serial_pad', int, 0))
        if serial_pad < 0:
            self.raise_tcl_error(_("Serial pad must be 0 or more."))
            return 'fail'
        context = {'object': obj.obj_options['name'] if obj is not None else str(args.get('outname', '')),
                   'project': project or '', 'date': now, 'time': now, 'serial': serial}
        text = Gen.expand_tokens(data, context, serial_pad)

        mask_text = str(args['mask_pattern'] if args.get('mask_pattern') is not None
                        else options.get('tools_qrcode_mask_pattern', 'auto')).strip().lower()
        if mask_text in ('', 'auto'):
            mask_pattern = None
        elif mask_text in ('0', '1', '2', '3', '4', '5', '6', '7'):
            mask_pattern = int(mask_text)
        else:
            self.raise_tcl_error('%s: %s' % (_("Mask pattern must be 0..7 or auto"), mask_text))
            return 'fail'
        # the round features of the code are not smaller than half of a module
        circle_steps = object_circle_steps(options, 'geometry',
                                           float(options.get('tools_qrcode_min_module', 0.15)) / 2, units)

        try:
            modules, utility, info = Gen.qr_geometry(text, version or None, error, box_size, border, units,
                                                     mask_pattern, circle_steps)
            eff_margin = Gen.effective_margin(margin, border, box_size, units)
            modules, utility = Gen.transform_geometry([modules, utility], rotation, mirror, anchor, eff_margin)
        except (Gen.QRDataOverflow, ValueError) as err:
            self.raise_tcl_error(str(err))
            return 'fail'

        if output == 'source':
            src_units = units
            try:
                solid, tools = Gen.insert_geometry(obj.solid_geometry, obj.tools, modules, utility, pos, border,
                                                   box_size, rounded, polarity, units=src_units, margin=eff_margin)
                follow = None
                if polarity == 'pos' and obj.follow_geometry:
                    follow = flatten_shapely_geometry(obj.follow_geometry) + \
                        [geo.centroid for geo in Gen.plan_insertion(
                            modules, utility, pos, border, box_size, rounded, polarity, src_units,
                            eff_margin).modules]
            except Exception as err:
                self.raise_tcl_error(str(err))
                return 'fail'
            with history_of(self.app).snapshot(_("QRCode"), [obj]):
                obj.solid_geometry = solid
                obj.tools = tools
                if follow is not None:
                    obj.follow_geometry = follow
                try:
                    a, b, c, d = obj.bounds()
                    obj.obj_options['xmin'] = a
                    obj.obj_options['ymin'] = b
                    obj.obj_options['xmax'] = c
                    obj.obj_options['ymax'] = d
                except Exception as err:
                    log.error("TclCommandQRCode bounds error --> %s" % str(err))
                obj.regenerate_source()
            return None

        outname = str(args.get('outname') or 'qrcode')
        solid, tools = Gen.new_gerber_geometry(modules, utility, pos, border, box_size, rounded, polarity,
                                               units=units, margin=eff_margin)

        def init(new_obj, app_obj):
            new_obj.tools = tools
            new_obj.solid_geometry = solid
            new_obj.units = units
            try:
                a, b, c, d = new_obj.bounds()
                new_obj.obj_options['xmin'] = a
                new_obj.obj_options['ymin'] = b
                new_obj.obj_options['xmax'] = c
                new_obj.obj_options['ymax'] = d
            except Exception as err:
                log.error("TclCommandQRCode bounds error --> %s" % str(err))
            new_obj.regenerate_source(name=outname)

        self.check_result(self.app.app_obj.new_object('gerber', outname, init, plot=False))
        return None
