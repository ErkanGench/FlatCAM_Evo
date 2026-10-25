# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# http://flatcam.org                                       #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 3/10/2019                                          #
# MIT Licence                                              #
# ##########################################################

from appPreProcessor import PreProc


# HP-GL plotter preprocessor (not a Roland one): the coordinates are integers in plotter units of 0.025mm
class hpgl(PreProc):
    include_header = True
    coordinate_format = "%.*f"

    def start_code(self, p):
        gcode = 'IN;\n'
        gcode += 'PU;'
        return gcode

    def startz_code(self, p):
        return ''

    def lift_code(self, p):
        gcode = 'PU;' + '\n'
        return gcode

    def down_code(self, p):
        gcode = 'PD;' + '\n'
        return gcode

    def toolchange_code(self, p):
        return 'SP%d;' % int(p.tool)

    def up_to_zero_code(self, p):
        return ''

    def position_code(self, p):
        # the bed offset and skew are applied in job units
        x, y = self.bed_xy(p)

        # we work only with METRIC units because HPGL mention only metric units so if FlatCAM units are INCH we
        # transform them in METRIC
        if str(p['units']).lower() == 'in':
            x *= 25.4
            y *= 25.4

        # HP-GL plotter unit is 0.025mm (40 units per mm), the coordinates are integers
        x = round(x * 40)
        y = round(y * 40)

        # constrain the x and y values within the domain of valid values: [-32768 ... 32767]
        x = max(-32768, min(32767, x))
        y = max(-32768, min(32767, y))

        return 'PA%d,%d;' % (x, y)

    def rapid_code(self, p):
        return self.position_code(p)

    def linear_code(self, p):
        return self.position_code(p)

    def end_code(self, p):
        gcode = self.position_code(p)
        return gcode

    def feedrate_code(self, p):
        return ''

    def z_feedrate_code(self, p):
        return ''

    def feedrate_rapid_code(self, p):
        return ''

    def spindle_code(self, p):
        return ''

    def dwell_code(self, p):
        return ''

    def spindle_stop_code(self, p):
        return ''
