# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# http://flatcam.org                                       #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 3/10/2019                                          #
# MIT Licence                                              #
# ##########################################################

from appPreProcessor import PreProc
import math


class Marlin(PreProc):

    include_header = True
    coordinate_format = "%.*f"
    feedrate_format = '%.*f'
    feedrate_rapid_format = feedrate_format

    def start_code(self, p):
        units = ' ' + str(p['units']).lower()
        coords_xy = p['xy_toolchange']
        end_coords_xy = p['xy_end']
        gcode = ';This preprocessor works with controllers with Marlin firmware.\n'

        xmin = '%.*f' % (p.coords_decimals, p['obj_options']['xmin'])
        xmax = '%.*f' % (p.coords_decimals, p['obj_options']['xmax'])
        ymin = '%.*f' % (p.coords_decimals, p['obj_options']['ymin'])
        ymax = '%.*f' % (p.coords_decimals, p['obj_options']['ymax'])

        if str(p['obj_options']['type']) == 'Geometry':
            gcode += ';TOOL DIAMETER: ' + str(p['obj_options']['tool_dia']) + units + '\n'
            gcode += ';Feedrate_XY: ' + str(p['feedrate']) + units + '/min' + '\n'
            gcode += ';Feedrate_Z: ' + str(p['z_feedrate']) + units + '/min' + '\n'
            gcode += ';Feedrate rapids ' + str(p['feedrate_rapid']) + units + '/min' + '\n' + '\n'
            gcode += ';Z_Cut: ' + str(p['z_cut']) + units + '\n'
            if p['multidepth'] is True:
                gcode += ';DepthPerCut: ' + str(p['z_depthpercut']) + units + ' <=>' + \
                         str(math.ceil(abs(p['z_cut']) / p['z_depthpercut'])) + ' passes' + '\n'
            gcode += ';Z_Move: ' + str(p['z_move']) + units + '\n'

        elif str(p['obj_options']['type']) == 'Excellon' and p['use_ui'] is True:
            gcode += '\n;TOOLS DIAMETER: \n'
            for tool, val in p['tools'].items():
                gcode += ';Tool: %s -> ' % str(tool) + 'Dia: %s' % str(val["tooldia"]) + '\n'

            gcode += '\n;FEEDRATE Z: \n'
            for tool, val in p['tools'].items():
                gcode += ';Tool: %s -> ' % str(tool) + 'Feedrate: %s' % \
                         str(val['data']["tools_drill_feedrate_z"]) + '\n'

            gcode += '\n;FEEDRATE RAPIDS: \n'
            for tool, val in p['tools'].items():
                gcode += ';Tool: %s -> ' % str(tool) + 'Feedrate Rapids: %s' % \
                         str(val['data']["tools_drill_feedrate_rapid"]) + '\n'

            gcode += '\n;Z_CUT: \n'
            for tool, val in p['tools'].items():
                gcode += ';Tool: %s -> ' % str(tool) + 'Z_Cut: %s' % str(val['data']["tools_drill_cutz"]) + '\n'

            gcode += '\n;Tools Offset: \n'
            for tool, val in p['tools'].items():
                gcode += ';Tool: %s -> ' % str(tool) + 'Offset Z: %s' % \
                         str(val['data']["tools_drill_offset"]) + '\n'

            if p['multidepth'] is True:
                gcode += '\n;DEPTH_PER_CUT: \n'
                for tool, val in p['tools'].items():
                    gcode += ';Tool: %s -> ' % str(tool) + 'DeptPerCut: %s' % \
                             str(val['data']["tools_drill_depthperpass"]) + '\n'

            gcode += '\n;Z_MOVE: \n'
            for tool, val in p['tools'].items():
                gcode += ';Tool: %s -> ' % str(tool) + 'Z_Move: %s' % str(val['data']["tools_drill_travelz"]) + '\n'
            gcode += '\n'

        if p['toolchange'] is True:
            gcode += ';Z Toolchange: ' + str(p['z_toolchange']) + units + '\n'

            if coords_xy is not None:
                gcode += ';X,Y Toolchange: ' + "%.*f, %.*f" % (p.decimals, coords_xy[0],
                                                               p.decimals, coords_xy[1]) + units + '\n'
            else:
                gcode += ';X,Y Toolchange: ' + "None" + units + '\n'

        gcode += ';Z Start: ' + str(p['startz']) + units + '\n'
        gcode += ';Z End: ' + str(p['z_end']) + units + '\n'
        if end_coords_xy is not None:
            gcode += ';X,Y End: ' + "%.*f, %.*f" % (p.decimals, end_coords_xy[0],
                                                    p.decimals, end_coords_xy[1]) + units + '\n'
        else:
            gcode += ';X,Y End: ' + "None" + units + '\n'
        gcode += ';Steps per circle: ' + str(p['steps_per_circle']) + '\n'
        gcode += ';Steps per circle: ' + str(p['steps_per_circle']) + '\n'

        if str(p['obj_options']['type']) == 'Excellon' or str(p['obj_options']['type']) == 'Excellon Geometry':
            gcode += ';Preprocessor Excellon: ' + str(p['pp_excellon_name']) + '\n' + '\n'
        else:
            gcode += ';Preprocessor Geometry: ' + str(p['pp_geometry_name']) + '\n' + '\n'

        gcode += ';X range: ' + '{: >9s}'.format(xmin) + ' ... ' + '{: >9s}'.format(xmax) + ' ' + units + '\n'
        gcode += ';Y range: ' + '{: >9s}'.format(ymin) + ' ... ' + '{: >9s}'.format(ymax) + ' ' + units + '\n\n'

        gcode += ';Spindle Speed: %s RPM\n' % str(p['spindlespeed'])

        gcode += 'G20\n' if p.units.upper() == 'IN' else 'G21\n'
        gcode += 'G90\n'

        return gcode

    def startz_code(self, p):
        if p.startz is not None:
            return 'G0 Z' + self.coordinate_format % (p.coords_decimals, p.startz)
        else:
            return ''

    def lift_code(self, p):
        return 'G0 Z' + self.coordinate_format % (p.coords_decimals, p.z_move) + " " + self.feedrate_rapid_code(p)

    def down_code(self, p):
        return 'G1 Z' + self.coordinate_format % (p.coords_decimals, p.z_cut) + " " + self.inline_z_feedrate_code(p)

    def toolchange_code(self, p):
        z_toolchange = p.z_toolchange
        toolchangexy = p.xy_toolchange

        if p.startz is not None and p.is_first_tool:
            z_toolchange = p.startz

        # Marlin has no M6 and its T selects an extruder, so the tool number is only in the M0 message
        message = 'Change to tool T%d dia %s' % (int(p.tool), '%.*f' % (p.decimals, p.toolC))
        if str(p['obj_options']['type']) == 'Excellon':
            message += ' drills %s' % p['tools'][int(p['tool'])]['nr_drills']

        gcode = '\n' + self.spindle_stop_code(p) + '\n'
        gcode += 'G0 Z' + self.coord(p, z_toolchange) + '\n'
        if toolchangexy is not None:
            gcode += 'G0 X' + self.coord(p, toolchangexy[0]) + ' Y' + self.coord(p, toolchangexy[1]) + '\n'
        gcode += 'M0 ' + message + '\n'
        gcode += 'G0 Z' + self.coord(p, z_toolchange) + '\n'

        if p.f_plunge is True:
            gcode += '\nG0 Z%.*f' % (p.coords_decimals, p.z_move)
        return gcode

    def up_to_zero_code(self, p):
        return 'G1 Z0 ' + self.inline_z_feedrate_code(p)

    def rapid_code(self, p):
        return 'G0 ' + self.position_code(p) + " " + self.feedrate_rapid_code(p)

    def linear_code(self, p):
        return 'G1 ' + self.position_code(p) + " " + self.inline_feedrate_code(p)

    def end_code(self, p):
        # End Z and the end position; the X-Y move is not made below the Travel Z
        gcode = self.end_moves_code(p, rapid='G0', suffix=" " + self.feedrate_rapid_code(p))

        return gcode

    def feedrate_code(self, p):
        return 'G1 F' + str(self.feedrate_format % (p.fr_decimals, p.feedrate))

    def inline_feedrate_code(self, p):
        return 'F' + self.feedrate_format % (p.fr_decimals, p.feedrate)

    def inline_z_feedrate_code(self, p):
        return 'F' + self.feedrate_format % (p.fr_decimals, p.z_feedrate)

    def z_feedrate_code(self, p):
        return 'G1 F' + str(self.feedrate_format % (p.fr_decimals, p.z_feedrate))

    def feedrate_rapid_code(self, p):
        return 'F' + self.feedrate_rapid_format % (p.fr_decimals, p.feedrate_rapid)

    def spindle_code(self, p):
        sdir = {'CW': 'M3', 'CCW': 'M4'}[p.spindledir]
        if p.spindlespeed:
            return '%s S%s' % (sdir, str(p.spindlespeed))
        else:
            return sdir

    def dwell_code(self, p):
        # G4 S is seconds, G4 P is milliseconds; the dwell time is in seconds
        if not p.dwelltime:
            return ''
        seconds = float(p.dwelltime)
        if seconds == int(seconds):
            return 'G4 S%d' % int(seconds)
        return 'G4 P%d' % int(round(seconds * 1000))

    def spindle_stop_code(self, p):
        gcode = 'M400\n'
        gcode += 'M5'
        return gcode
