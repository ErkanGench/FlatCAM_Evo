# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# http://flatcam.org                                       #
# File Author: Matthieu Berthomé                           #
# Date: 5/26/2017                                          #
# MIT Licence                                              #
# ##########################################################

from appPreProcessor import PreProc
import math

# This post processor is configured to output code that
# is compatible with almost any version of Grbl.


class GRBL_laser(PreProc):

    include_header = True
    coordinate_format = "%.*f"
    feedrate_format = '%.*f'

    def start_code(self, p):
        units = ' ' + str(p['units']).lower()
        gcode = '(This preprocessor is used with a motion controller loaded with GRBL firmware. )\n'
        gcode += '(It is for the case when it is used together with a LASER connected on the SPINDLE connector.)\n' \
                 '(This preprocessor makes no moves on the Z axis it will only move horizontally.)\n' \
                 '(The horizontal move is done with G0 - highest possible speed set in the GRBL controller.)\n' \
                 '(It assumes a manually focused laser.)\n' \
                 '(The laser is started with M3 or M4 command and stopped with the M5 command.)\n\n'

        xmin = '%.*f' % (p.coords_decimals, p['obj_options']['xmin'])
        xmax = '%.*f' % (p.coords_decimals, p['obj_options']['xmax'])
        ymin = '%.*f' % (p.coords_decimals, p['obj_options']['ymin'])
        ymax = '%.*f' % (p.coords_decimals, p['obj_options']['ymax'])

        gcode += '(Feedrate: ' + str(p['feedrate']) + units + '/min' + ')\n'
        gcode += '(Steps per circle: ' + str(p['steps_per_circle']) + ')\n'

        if str(p['obj_options']['type']) == 'Excellon' or str(p['obj_options']['type']) == 'Excellon Geometry':
            gcode += '(Preprocessor Excellon: ' + str(p['pp_excellon_name']) + ')\n'
        else:
            gcode += '(Preprocessor Geometry: ' + str(p['pp_geometry_name']) + ')\n' + '\n'

        gcode += '(X range: ' + '{: >9s}'.format(xmin) + ' ... ' + '{: >9s}'.format(xmax) + ' ' + units + ')\n'
        gcode += '(Y range: ' + '{: >9s}'.format(ymin) + ' ... ' + '{: >9s}'.format(ymax) + ' ' + units + ')\n\n'

        gcode += '(Laser Power - Spindle Speed: ' + str(p['spindlespeed']) + ')\n'
        gcode += '(Laser Minimum Power: ' + str(p['laser_min_power']) + ')\n\n'

        gcode += ('G20' if p.units.upper() == 'IN' else 'G21') + "\n"
        gcode += 'G90\n'
        gcode += 'G17\n'
        gcode += 'G94'

        return gcode

    def startz_code(self, p):
        return ''

    def lift_code(self, p):
        if float(p.laser_min_power or 0) > 0.0:
            # the formatted text: laser OFF must always be like this else the plotting will not be done correctly
            return '%s S%s (laser OFF)\n' % (str(p.laser_on_code), str(p.laser_min_power))
        else:
            return 'M5'

    def down_code(self, p):
        if p.spindlespeed:
            return '%s S%s' % (str(p.laser_on_code), str(p.spindlespeed))
        else:
            return '%s S0' % str(p.laser_on_code)

    def toolchange_code(self, p):
        return ''

    def up_to_zero_code(self, p):
        return ''

    def rapid_code(self, p):
        return 'G0 ' + self.position_code(p)

    def linear_code(self, p):
        return 'G1 ' + self.position_code(p) + ' F' + str(self.feedrate_format % (p.fr_decimals, p.feedrate))

    def end_code(self, p):
        coords_xy = p['xy_end']
        gcode = ''

        if coords_xy and coords_xy != '':
            gcode += 'G0 X' + self.coord(p, coords_xy[0]) + ' Y' + self.coord(p, coords_xy[1]) + "\n"
        return gcode

    def feedrate_code(self, p):
        return 'G1 F' + str(self.feedrate_format % (p.fr_decimals, p.feedrate))

    def z_feedrate_code(self, p):
        return 'G1 F' + str(self.feedrate_format % (p.fr_decimals, p.z_feedrate))

    def spindle_code(self, p):
        if p.spindlespeed:
            return '%s S%s' % (str(p.laser_on_code), str(p.spindlespeed))
        else:
            return '%s S0' % str(p.laser_on_code)

    def dwell_code(self, p):
        return ''

    def spindle_stop_code(self, p):
        return 'M5'
