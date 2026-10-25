# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# http://flatcam.org                                       #
# File Author: Matthieu Berthomé, Daniel Friderich         #
# Date: 12/15/2019                                         #
# MIT Licence                                              #
# ##########################################################

from appPreProcessor import PreProc
import math


class ISEL_ICP_CNC(PreProc):
    include_header = False

    def start_code(self, p):
        units = ' ' + str(p['units']).lower()
        coords_xy = p['xy_toolchange']
        end_coords_xy = p['xy_end']
        gcode = '; This preprocessor is used with a ISEL ICP CNC router.\n\n'

        xmin = '%.*f' % (p.coords_decimals, p['obj_options']['xmin'])
        xmax = '%.*f' % (p.coords_decimals, p['obj_options']['xmax'])
        ymin = '%.*f' % (p.coords_decimals, p['obj_options']['ymin'])
        ymax = '%.*f' % (p.coords_decimals, p['obj_options']['ymax'])

        gcode += 'IMF_PBL flatcam\n\n'

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

        if str(p['obj_options']['type']) == 'Excellon' or str(p['obj_options']['type']) == 'Excellon Geometry':
            gcode += ';Preprocessor Excellon: ' + str(p['pp_excellon_name']) + '\n' + '\n'
        else:
            gcode += ';Preprocessor Geometry: ' + str(p['pp_geometry_name']) + '\n' + '\n'

        gcode += ';X range: ' + '{: >9s}'.format(xmin) + ' ... ' + '{: >9s}'.format(xmax) + ' ' + units + '\n'
        gcode += ';Y range: ' + '{: >9s}'.format(ymin) + ' ... ' + '{: >9s}'.format(ymax) + ' ' + units + '\n\n'

        gcode += ';Spindle Speed: %s RPM\n' % str(p['spindlespeed'])

        return gcode

    @staticmethod
    def um(p, value):
        # a value in the job units (mm or inch) as integer micrometres, the unit of the ICP language
        return int(round(float(value) * (25400 if str(p.units).upper() == 'IN' else 1000)))

    def um_per_s(self, p, feedrate):
        # a feedrate in job units per minute as integer micrometres per second
        return int(round(float(feedrate) * (25400 if str(p.units).upper() == 'IN' else 1000) / 60))

    def startz_code(self, p):
        if p.startz is not None:
            return 'FASTABS Z' + str(self.um(p, p.startz))
        else:
            return ''

    def lift_code(self, p):
        return 'FASTABS Z' + str(self.um(p, p.z_move))

    def down_code(self, p):
        return 'MOVEABS Z' + str(self.um(p, p.z_cut))

    def toolchange_code(self, p):
        z_toolchange = p.z_toolchange
        toolchangexy = p.xy_toolchange
        f_plunge = p.f_plunge

        if p.startz is not None and p.is_first_tool:
            z_toolchange = p.startz

        toolC_formatted = '%.*f' % (p.decimals, p.toolC)

        gcode = 'SPINDLE OFF\n'
        if toolchangexy is not None:
            gcode += 'FASTABS Z' + str(self.um(p, z_toolchange)) + '\n'
            gcode += 'FASTABS X' + str(self.um(p, toolchangexy[0])) + ' Y' + str(self.um(p, toolchangexy[1])) + '\n'
        gcode += "GETTOOL {tool}\n; Changed to Tool Dia = {toolC}".format(tool=int(p.tool), toolC=toolC_formatted)

        if f_plunge is True:
            gcode += '\nFASTABS Z' + str(self.um(p, p.z_move))
        return gcode

    def up_to_zero_code(self, p):
        return 'MOVEABS Z0'

    def position_code(self, p):
        x_pos, y_pos = self.bed_xy(p)
        return 'X' + str(self.um(p, x_pos)) + ' Y' + str(self.um(p, y_pos))

    def rapid_code(self, p):
        return 'FASTABS ' + self.position_code(p)

    def linear_code(self, p):
        return 'MOVEABS ' + self.position_code(p)

    def end_code(self, p):
        # End Z and the end position in workpiece coordinates; the X-Y move is not made below the Travel Z
        z_first = self.end_xy_move_z(p) if p['xy_end'] else p.z_end
        gcode = 'FASTABS Z' + str(self.um(p, z_first)) + '\n'
        if p['xy_end']:
            gcode += 'FASTABS X' + str(self.um(p, p['xy_end'][0])) + ' Y' + str(self.um(p, p['xy_end'][1])) + '\n'
            if z_first != p.z_end:
                gcode += 'FASTABS Z' + str(self.um(p, p.z_end)) + '\n'
        gcode += 'WPCLEAR\n'
        if not p['xy_end']:
            # WPCLEAR clears the workpiece zero: these are machine coordinates, the reference point
            gcode += 'FASTABS Z0\n'
            gcode += 'FASTABS X0 Y0\n'
        gcode += 'PROGEND'
        return gcode

    def feedrate_code(self, p):
        return 'VEL ' + str(self.um_per_s(p, p.feedrate))

    def z_feedrate_code(self, p):
        return 'VEL ' + str(self.um_per_s(p, p.z_feedrate))

    def spindle_code(self, p):
        sdir = {'CW': 'SPINDLE CW', 'CCW': 'SPINDLE CCW'}[p.spindledir]
        if p.spindlespeed:
            return '%s RPM%s' % (sdir, str(int(p.spindlespeed)))
        else:
            return sdir

    def dwell_code(self, p):
        if p.dwelltime:
            return 'WAIT ' + str(int(p.dwelltime * 1000))

    def spindle_stop_code(self, p):
        return 'SPINDLE OFF'
