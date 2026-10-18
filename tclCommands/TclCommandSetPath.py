# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 4/28/2020                                          #
# MIT Licence                                              #
# ##########################################################

from tclCommands.TclCommand import TclCommand

import collections
import os
import logging
import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class TclCommandSetPath(TclCommand):
    """
    Tcl shell command to set the default path for Tcl Shell for opening files.

    example:

    """

    # List of all command aliases, to be able to use old names for backward compatibility (add_poly, add_polygon)
    aliases = ['set_path']

    description = '%s %s' % ("--", "Set the folder path to the specified path.")

    # Dictionary of types from Tcl command, needs to be ordered
    arg_names = collections.OrderedDict([
        ('path', str)
    ])

    # Dictionary of types from Tcl command, needs to be ordered , this  is  for options  like -optionname value
    option_types = collections.OrderedDict([
        ('create', str),
    ])

    # array of mandatory options for current Tcl command: required = {'name','outname'}
    required = ['path']

    # structured help for current command, args needs to be ordered
    help = {
        'main': "Will set the folder path to the specified path.\n"
                "By using this command there is no need for usage of the absolute path to the files.",
        'args': collections.OrderedDict([
            ('path', 'A folder path to where the user is supposed to have the file that he will work with.\n'
                     'WARNING: No spaces allowed. Use quotes around the path if it contains spaces.'),
            ('create', 'If set to True, if the folder does not exist it will create it.'),
        ]),
        'examples': ['set_path D:\\Project_storage_path']
    }

    def execute(self, args, unnamed_args):
        """

        :param args:
        :param unnamed_args:
        :return:
        """

        if 'path' not in args:
            self.raise_tcl_error('A directory path is required.')
        else:
            path = str(args['path']).replace('\\', '/')

        # check if path exists
        path_isdir = os.path.isdir(path)
        if path_isdir is False:
            path_isfile = os.path.isfile(path)
            if path_isfile:
                msg = '[ERROR] %s: %s, %s' % (
                    "The provided path",
                    str(path),
                    "is a path to file and not a directory as expected.")
                self.app.inform_shell.emit(msg)
                self.raise_tcl_error('The provided path is not a directory.')

            if 'create' in args:
                eval_option = self.parse_bool(args['create'])

                if eval_option:
                    self.app.inform_shell.emit("Path not found, let's create it.")
                    os.makedirs(path, exist_ok=True)
                else:
                    self.raise_tcl_error('The provided directory does not exist.')
            else:
                msg = '[ERROR] %s: %s, %s' % (
                    "The provided path", str(path), "do not exist. Check for typos.")
                self.app.inform_shell.emit(msg)
                self.raise_tcl_error('The provided directory does not exist.')

        self.app.shell.tcl.call('cd', path)
        self.app.options["global_tcl_path"] = str(path)
        msg = '[success] %s: %s' % ("Relative path set to", str(path))
        self.app.inform_shell.emit(msg)
