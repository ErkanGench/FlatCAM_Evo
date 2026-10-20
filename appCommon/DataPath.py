# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# License:  MIT Licence                                    #
# ##########################################################

"""
The folder of the application settings: the preferences, the tools database, the recent files, the preprocessors
folder and the log.

By default it is %APPDATA%/FlatCAM on Windows (the 'config' folder of the application for a portable installation)
and ~/.FlatCAM on Linux and macOS. A folder in the FLATCAM_DATA_PATH environment variable is used instead: a second
installation or a portable copy keeps its own settings, and a test or a script can use a throw-away folder.
"""

import os

DATA_PATH_ENV = 'FLATCAM_DATA_PATH'


def data_path_from_env(environ=None):
    """
    The settings folder set in the FLATCAM_DATA_PATH environment variable.

    A relative path is taken from the current working folder, so it must be read before the application changes the
    working folder to its own folder. The spaces around the value are ignored (on Windows,
    'set FLATCAM_DATA_PATH=C:\\folder && python flatcam.py' keeps the space before '&&').

    :param environ: the environment variables; os.environ when None
    :return:        the absolute path of the folder, or None when the variable is not set or is empty
    """
    environ = os.environ if environ is None else environ
    value = environ.get(DATA_PATH_ENV, '').strip()
    if not value:
        return None
    return os.path.abspath(os.path.expanduser(value))
