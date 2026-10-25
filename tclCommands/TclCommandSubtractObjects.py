import collections
import logging

import gettext
import appTranslation as fcTranslate
import builtins

from camlib import object_circle_steps
from tclCommands.TclCommand import TclCommand

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')

KINDS = ('gerber', 'geometry', 'excellon')


class TclCommandSubtractObjects(TclCommand):
    """
    Tcl shell command to subtract, intersect or xor the area of objects from a Gerber, Geometry or Excellon object.
    """

    aliases = ['subtract_objects', 'subtract']

    description = '%s %s' % ("--", "Subtract (or intersect, xor) the area of one or more objects from a target object "
                                   "into a new object.")

    arg_names = collections.OrderedDict([
        ('target', str),
        ('subtractors', str),
    ])

    option_types = collections.OrderedDict([
        ('op', str),
        ('margin', float),
        ('close_paths', str),
        ('target_tools', str),
        ('outname', str),
        ('keep_target', str),
        ('delete_subtractors', str),
        ('steps', int),
    ])

    required = ['target', 'subtractors']

    help = {
        'main': "Apply the area of the subtractor objects to the target object and create a new object with the "
                "result (the Subtract plugin). The values that are not given are taken from the Subtract plugin "
                "defaults. The subtractors may be Gerber, Geometry or Excellon (drills and slots as holes) objects "
                "and are given as a comma separated list.",
        'args': collections.OrderedDict([
            ('target', 'Name of the target object (Gerber, Geometry or Excellon). Required.'),
            ('subtractors', 'Names of the subtractor objects, separated by commas. Required.'),
            ('op', 'subtract (default), intersect or xor. xor is not valid for an Excellon target.'),
            ('margin', 'Grows the subtractor area by this value (the units of the application). Default 0.'),
            ('close_paths', 'Geometry target: 1 unites the polygons and gives polygons; 0 works on the rings.'),
            ('target_tools', 'Comma separated ids of the target apertures / tools to affect. Default all.'),
            ('outname', 'Name of the new object. Default: target name + the plugin suffix.'),
            ('keep_target', '1 keeps the target; 0 deletes it and gives the result its name.'),
            ('delete_subtractors', '1 deletes the subtractor objects after the operation.'),
            ('steps', 'Circle steps (whole circle) of the shapes made from drills and margins.'),
        ]),
        'examples': ['subtract_objects copper.gtl mask.gts',
                     'subtract copper.gtl drills.drl,keepout -op subtract -margin 0.2 -outname copper_cut',
                     'subtract_objects board.gbr outline -op intersect -keep_target 0']
    }

    def _flag(self, args, key, pref, default):
        value = args[key] if key in args else self._app_option(pref, default)
        try:
            return self.parse_bool(value)
        except ValueError as err:
            self.raise_tcl_error('-%s: %s' % (key, err))

    def execute(self, args, unnamed_args):
        from appPlugins.ToolSub import SubGen

        target_name = str(args['target'])
        names = [n.strip() for n in ','.join([str(args['subtractors'])] + [str(u) for u in unnamed_args]).split(',')]
        names = [n for n in names if n]
        if not names:
            self.raise_tcl_error(_("There is no subtractor object."))
            return 'fail'

        op = str(args.get('op') or self._app_option('tools_sub_operation', 'subtract')).lower()
        if op not in SubGen.OPERATIONS:
            self.raise_tcl_error('%s: %s' % (_("Unknown operation, use subtract, intersect or xor"), op))
            return 'fail'

        try:
            margin = float(args['margin'] if 'margin' in args else self._app_option('tools_sub_margin', 0.0))
        except (TypeError, ValueError):
            margin = 0.0
        if margin < 0:
            self.raise_tcl_error(_("The margin can not be negative."))
            return 'fail'

        close_paths = self._flag(args, 'close_paths', 'tools_sub_close_paths', True)
        keep_target = self._flag(args, 'keep_target', 'tools_sub_keep_target', True)
        delete_subtractors = self._flag(args, 'delete_subtractors', 'tools_sub_delete_subtractors', False)

        target = self.app.collection.get_by_name(target_name)
        if target is None:
            self.raise_tcl_error('%s: %s' % (_("Object not found"), target_name))
            return 'fail'
        if getattr(target, 'kind', None) not in KINDS:
            self.raise_tcl_error('%s: %s' % (_("Expected a Gerber, Geometry or Excellon object"), target_name))
            return 'fail'

        subtractors = []
        for name in names:
            if name == target_name:
                self.raise_tcl_error(_("The target object can not be a subtractor."))
                return 'fail'
            obj = self.app.collection.get_by_name(name)
            if obj is None:
                self.raise_tcl_error('%s: %s' % (_("Object not found"), name))
                return 'fail'
            if getattr(obj, 'kind', None) not in KINDS:
                self.raise_tcl_error('%s: %s' % (_("Expected a Gerber, Geometry or Excellon object"), name))
                return 'fail'
            if all(obj is not s for s in subtractors):
                subtractors.append(obj)
        if any(s is target for s in subtractors):
            self.raise_tcl_error(_("The target object can not be a subtractor."))
            return 'fail'
        if target.kind == 'excellon' and op == 'xor':
            self.raise_tcl_error(_("The xor operation is not valid for an Excellon object."))
            return 'fail'

        if 'steps' in args:
            try:
                steps = int(args['steps'])
            except (TypeError, ValueError):
                steps = 64
        else:
            # the circles of the margin and of the drills and slots: the largest radius sets the steps
            radius = max([margin] + [float(tool.get('tooldia') or 0.0) / 2 for obj in [target] + subtractors
                                     if obj.kind == 'excellon' for tool in (obj.tools or {}).values()])
            steps = object_circle_steps(self.app.options, target.kind, radius, getattr(self.app, 'app_units', 'MM'))
        if steps < 4:
            self.raise_tcl_error(_("The circle steps must be at least 4."))
            return 'fail'

        target_tools = None
        if args.get('target_tools') not in (None, ''):
            keys = {str(k): k for k in (target.tools or {})}
            target_tools = []
            for token in str(args['target_tools']).split(','):
                token = token.strip()
                if not token:
                    continue
                if token not in keys:
                    self.raise_tcl_error('%s: %s' % (_("Unknown tool id"), token))
                    return 'fail'
                target_tools.append(keys[token])

        try:
            result = SubGen.compute(target, subtractors, op, margin, steps, close_paths, target_tools)
        except ValueError as err:
            self.raise_tcl_error(str(err))
            return 'fail'
        if result.empty_area:
            self.raise_tcl_error(_("The subtractors have no area."))
            return 'fail'

        suffix = str(self._app_option('tools_sub_suffix', '_sub') or '')
        if keep_target:
            outname = str(args.get('outname') or (target_name + suffix))
        else:
            outname = str(args.get('outname') or target_name)
        # the result is made before the target is deleted: a failed creation must not lose the target
        create_name = outname if (keep_target or outname != target_name) else (target_name + (suffix or '_sub'))
        created = []

        def init(new_obj, app_obj):
            created.append(new_obj)
            SubGen.apply_result(new_obj, result, target)
            try:
                a, b, c, d = new_obj.bounds()
                new_obj.obj_options['xmin'] = a
                new_obj.obj_options['ymin'] = b
                new_obj.obj_options['xmax'] = c
                new_obj.obj_options['ymax'] = d
            except Exception as err:
                log.error("TclCommandSubtractObjects bounds error --> %s" % str(err))
            new_obj.regenerate_source(name=outname)

        self.check_result(self.app.app_obj.new_object(target.kind, create_name, init, plot=False))
        if not keep_target:
            self.app.collection.delete_by_name(target_name)
            if created and created[0].obj_options.get('name') != outname:
                self.app.collection.rename_object(created[0], outname)

        if delete_subtractors:
            for obj in subtractors:
                name = obj.obj_options['name']
                if self.app.collection.get_by_name(name) is not None:
                    self.app.collection.delete_by_name(name)
        return None
