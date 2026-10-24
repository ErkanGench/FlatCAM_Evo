"""
Relative file names typed by the user.

App.__init__() does os.chdir() into the application folder (the GUI resources are loaded by relative path). A relative
file name in a Tcl command (``write_gcode out.nc``) or on the command line is meant relative to the folder FlatCAM was
started from, not relative to the application folder. For a packaged application that folder is the signed, often
read-only application bundle: the file was written inside it and the code signature broke.

This module is imported before the chdir, so it can remember the folder FlatCAM was started from.

The user can still move the process: ``set_path`` and the Tcl ``cd`` change the working folder, and from then on the
relative names follow it (see base_dir()).
"""

import os
import sys


def _normalized(path):
    # on Windows the letters of a path are not case sensitive: C:\Program Files\FlatCAM is c:\program files\flatcam
    return os.path.normcase(os.path.realpath(path))


def _is_inside(path, folder):
    path, folder = _normalized(path), _normalized(folder)
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:
        # different drives on Windows
        return False


def compute_start_dir(cwd, app_dir, frozen, home, system_root=None, exe_dir=None):
    """
    :param cwd: the working directory at the start of the application, None if it could not be read
    :param app_dir: the application folder
    :param frozen: True for a packaged application (PyInstaller, cx_freeze ...)
    :param home: the home folder of the user
    :param system_root: the Windows folder (%SystemRoot%), None elsewhere
    :param exe_dir: for a packaged application, the folder of the executable (the install folder, a Start Menu
    shortcut starts there) or the .app bundle on macOS. With cx_freeze app_dir is its lib/ subfolder.
    :return: the folder that relative file names are resolved against.
    The home folder replaces a working directory that is no place for the user's files: none, the root of the file
    system (a packaged application started from the Finder / Dock, an AppImage or a launcher on Linux, ``C:\\`` or
    ``\\\\server\\share\\`` on Windows), a folder inside the Windows folder (some launchers start in System32) or,
    for a packaged application, a folder inside the application itself. A source checkout started from its own
    folder keeps it.
    """

    if not cwd:
        return home
    if os.path.dirname(cwd) == cwd:
        return home
    if system_root and _is_inside(cwd, system_root):
        return home
    if frozen and any(_is_inside(cwd, folder) for folder in (app_dir, exe_dir) if folder):
        return home
    return cwd


def _current_dir():
    try:
        return os.getcwd()
    except OSError:
        # the folder was deleted under the running process
        return None


def _application_dir():
    # the same folder as App.app_home
    folder = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    if os.path.isfile(folder):
        # cx_freeze: the modules are in a zip file
        folder = os.path.dirname(folder)
    return folder


def _executable_dir():
    folder = os.path.dirname(os.path.realpath(sys.executable))
    # macOS: <name>.app/Contents/MacOS/<exe>; the whole bundle is the application
    parts = folder.replace('\\', '/').split('/')
    if len(parts) >= 3 and parts[-1] == 'MacOS' and parts[-2] == 'Contents' and parts[-3].endswith('.app'):
        folder = os.path.dirname(os.path.dirname(folder))
    return folder


APP_DIR = _application_dir()

START_DIR = compute_start_dir(
    cwd=_current_dir(),
    app_dir=APP_DIR,
    frozen=getattr(sys, 'frozen', False),
    home=os.path.expanduser('~'),
    system_root=os.environ.get('SystemRoot'),
    exe_dir=_executable_dir() if getattr(sys, 'frozen', False) else None,
)


def base_dir():
    """
    :return: the folder that relative file names are resolved against: the folder FlatCAM was started from as long as the
    process is still in the application folder (where App.__init__() put it), and the working folder when the user
    moved the process with ``set_path`` or the Tcl ``cd``.
    """

    cwd = _current_dir()
    if cwd is None or _normalized(cwd) == _normalized(APP_DIR):
        return START_DIR
    return cwd


def resolve_user_path(path, start_dir=None):
    """
    :param path: a file or folder name as the user typed it
    :param start_dir: the folder for relative names; default base_dir()
    :return: the absolute name. ``~`` is expanded, an absolute name and anything that is not a non-empty string are
    returned unchanged.
    """

    if not isinstance(path, str) or path == '':
        return path

    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return os.path.join(base_dir() if start_dir is None else start_dir, path)


COMMAND_WORDS = ('quit', 'exit', 'save')


def local_path_from_url(name):
    """
    :param name: an argument of the command line
    :return: the local path of a file:// URL (some launchers pass the files as URLs); anything else unchanged.
    """

    if isinstance(name, str) and name[:5].lower() == 'file:':
        from urllib.parse import unquote, urlparse
        parsed = urlparse(name)
        path = unquote(parsed.path)
        if parsed.netloc and parsed.netloc.lower() != 'localhost':
            # file://server/share/a.gbr
            path = '//%s%s' % (parsed.netloc, path)
        elif sys.platform == 'win32' and len(path) > 2 and path[0] == '/' and path[2] == ':':
            # file:///C:/boards/a.gbr
            path = path[1:]
        return path or name
    return name


def resolve_existing_paths(names, start_dir=None):
    """
    :param names: the arguments of the command line (the files to open and words like quit or save)
    :return: the list with the names of the files that exist made absolute; the other names are unchanged. A file://
    URL becomes a local path.
    """

    result = []
    for name in names:
        name = local_path_from_url(name)
        resolved = resolve_user_path(name, start_dir)
        result.append(resolved if os.path.exists(resolved) else name)
    return result


def absolute_paths(names, start_dir=None):
    """
    For the arguments that a second launch sends to the open instance, which resolves relative names against its own
    folder: every name is made absolute here, against the folder this launch started from, also when the file does not
    exist. The command words (quit, save) and file:// URLs are handled as in resolve_existing_paths().
    """

    result = []
    for name in names:
        name = local_path_from_url(name)
        if not isinstance(name, str) or name.strip().lower() in COMMAND_WORDS:
            result.append(name)
        else:
            result.append(os.path.normpath(resolve_user_path(name, start_dir)))
    return result
