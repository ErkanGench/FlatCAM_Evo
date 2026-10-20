# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     10/20/2026                                     #
# License:  MIT Licence                                    #
# ##########################################################
"""
Stop the connected machine controllers when the application closes or crashes.

A plugin that drives a machine registers its stop function. ``stop_all()`` runs them all; the close
of the application and the crash handler (``flatcam.py``) call it. A stop function must stop the
motion, the spindle and the outputs, close the connection, and return quickly.

The application ends with ``os._exit()``, so ``atexit`` handlers do not run: use this registry.
A hard crash (an access violation, a killed process, a power loss) runs no code. Only the hardware
E-stop protects the machine then.
"""

import logging
import threading

try:
    from PyQt6 import sip
except ImportError:  # no Qt: no Qt owner can be deleted
    sip = None

log = logging.getLogger('base')

_lock = threading.Lock()
_stoppers = []
_quit_app = None


def register(stopper):
    """Add a stop function (no arguments). Registering the same function again does nothing."""
    with _lock:
        if stopper not in _stoppers:
            _stoppers.append(stopper)


def unregister(stopper):
    with _lock:
        if stopper in _stoppers:
            _stoppers.remove(stopper)


def connect_quit(qt_app):
    """Run stop_all() when this Qt application quits. A second call for the same application does nothing."""
    global _quit_app
    with _lock:
        if qt_app is None or qt_app is _quit_app:
            return
        _quit_app = qt_app
    qt_app.aboutToQuit.connect(stop_all)


def _owner_deleted(stopper):
    """:return: True if the stop function is a method of a Qt object that Qt has deleted."""
    owner = getattr(stopper, '__self__', None)
    if sip is None or owner is None:
        return False
    try:
        return sip.isdeleted(owner)
    except TypeError:  # not a Qt object
        return False


def stop_all():
    """
    Run every stop function. A failure is logged; the other stop functions still run.
    The stop function of a deleted Qt object still runs (its port can be open), then stop_all() removes it.
    """
    with _lock:
        stoppers = list(_stoppers)
    for stopper in stoppers:
        try:
            stopper()
        except Exception:
            log.exception('MachineSafety.stop_all() -> a controller did not stop')
        if _owner_deleted(stopper):
            unregister(stopper)
