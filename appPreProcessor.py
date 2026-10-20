# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# http://flatcam.org                                       #
# File Author: Matthieu Berthomé                           #
# Date: 5/26/2017                                          #
# MIT Licence                                              #
# ##########################################################

from importlib.machinery import SourceFileLoader
import os
from abc import ABCMeta, abstractmethod

# module-root dictionary of preprocessors

import logging

log = logging.getLogger('base')
preprocessors = {}


class ABCPreProcRegister(ABCMeta):
    # handles preprocessors registration on instantiation
    def __new__(cls, clsname, bases, attrs):
        newclass = super(ABCPreProcRegister, cls).__new__(cls, clsname, bases, attrs)
        if object not in bases:
            if newclass.__name__ in preprocessors:
                log.warning('Preprocessor %s has been overriden' % newclass.__name__)
            preprocessors[newclass.__name__] = newclass()  # here is your register function
        return newclass


class PreProc(object, metaclass=ABCPreProcRegister):
    @abstractmethod
    def start_code(self, p):
        pass

    @abstractmethod
    def lift_code(self, p):
        pass

    @abstractmethod
    def down_code(self, p):
        pass

    @abstractmethod
    def toolchange_code(self, p):
        pass

    @abstractmethod
    def up_to_zero_code(self, p):
        pass

    @abstractmethod
    def rapid_code(self, p):
        pass

    @abstractmethod
    def linear_code(self, p):
        pass

    @abstractmethod
    def end_code(self, p):
        pass

    @abstractmethod
    def feedrate_code(self, p):
        pass

    @abstractmethod
    def spindle_code(self, p):
        pass

    @abstractmethod
    def spindle_stop_code(self, p):
        pass

    @staticmethod
    def end_xy_move_z(p):
        """
        The height of the final X-Y move to the end position: End Z, or the Travel Z when End Z is lower, so the
        tool does not travel over the workpiece and the clamps below the Travel Z.

        :param p:   preprocessor parameters
        :return:    the Z of the final X-Y move
        """
        try:
            return max(float(p['z_end']), float(p['z_move']))
        except (KeyError, TypeError, ValueError):
            return p['z_end']

    def end_moves_code(self, p, rapid='G00', z_rapid=None, suffix=''):
        """
        The moves at the end of the job: to End Z, then the X-Y move to the end position (if one is set).
        When End Z is below the Travel Z, the X-Y move is made at the Travel Z and the tool goes down to End Z after it.

        :param p:           preprocessor parameters
        :param rapid:       the rapid move command of the X-Y move ('G00' or 'G0')
        :param z_rapid:     the rapid move command of the Z moves; by default the same as rapid
        :param suffix:      text added at the end of each move (e.g. the rapid feedrate)
        :return:            G-code
        """
        z_rapid = rapid if z_rapid is None else z_rapid
        coords_xy = p['xy_end']

        if not coords_xy:
            return z_rapid + ' Z' + self.feedrate_format % (p.fr_decimals, p.z_end) + suffix + "\n"

        z_xy = self.end_xy_move_z(p)
        gcode = z_rapid + ' Z' + self.feedrate_format % (p.fr_decimals, z_xy) + suffix + "\n"
        gcode += '{g} X{x} Y{y}'.format(g=rapid, x=coords_xy[0], y=coords_xy[1]) + suffix + "\n"
        if z_xy != p.z_end:
            gcode += z_rapid + ' Z' + self.feedrate_format % (p.fr_decimals, p.z_end) + suffix + "\n"
        return gcode


class AppPreProcTools(object, metaclass=ABCPreProcRegister):
    @abstractmethod
    def start_code(self, p):
        pass

    @abstractmethod
    def lift_code(self, p):
        pass

    @abstractmethod
    def down_z_start_code(self, p):
        pass

    @abstractmethod
    def lift_z_dispense_code(self, p):
        pass

    @abstractmethod
    def down_z_stop_code(self, p):
        pass

    @abstractmethod
    def toolchange_code(self, p):
        pass

    @abstractmethod
    def rapid_code(self, p):
        pass

    @abstractmethod
    def linear_code(self, p):
        pass

    @abstractmethod
    def end_code(self, p):
        pass

    @abstractmethod
    def feedrate_xy_code(self, p):
        pass

    @abstractmethod
    def z_feedrate_code(self, p):
        pass

    @abstractmethod
    def feedrate_z_dispense_code(self, p):
        pass

    @abstractmethod
    def spindle_fwd_code(self, p):
        pass

    @abstractmethod
    def spindle_rev_code(self, p):
        pass

    @abstractmethod
    def spindle_off_code(self, p):
        pass

    @abstractmethod
    def dwell_fwd_code(self, p):
        pass

    @abstractmethod
    def dwell_rev_code(self, p):
        pass


def load_preprocessors(app):
    preprocessors_path_search = [
        os.path.join(app.data_path, 'preprocessors', '*.py'),
        os.path.join('preprocessors', '*.py')
    ]
    import glob
    for path_search in preprocessors_path_search:
        for file in glob.glob(path_search):
            try:
                SourceFileLoader('FlatCAMPostProcessor', file).load_module()
            except Exception as e:
                app.log.error(str(e))
    return preprocessors
