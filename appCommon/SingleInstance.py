# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File: SingleInstance.py                                  #
# ##########################################################

"""
Hand the files of a second launch to the FlatCAM window that is already open.

The open instance listens on a local socket (a named pipe on Windows, a unix socket elsewhere) whose name belongs to
the current user and this installation. A second launch with files sends them there as one line of JSON and exits.
"""

import getpass
import hashlib
import json
import logging
import os
import sys

from PyQt6 import QtCore, QtNetwork
from PyQt6.QtCore import pyqtSignal

log = logging.getLogger('base')

# a message is a list of paths: a bigger one is not from FlatCAM
MAX_MESSAGE = 1 << 20


def server_name():
    """
    Name of the local socket: one per user and installation folder. Kept short (a unix socket path has a small limit).
    """
    try:
        user = getpass.getuser()
    except Exception:
        user = os.environ.get('USERNAME') or os.environ.get('USER') or ''
    app_folder = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    digest = hashlib.sha1(('%s|%s' % (user, app_folder)).encode('utf-8', 'replace')).hexdigest()
    return 'FlatCAM_EVO-' + digest[:12]


def send_to_running(files, timeout_ms=300):
    """
    Send the files to the open instance.

    :param files:       list of absolute paths
    :param timeout_ms:  how long to wait for the connection and for the write
    :return:            True if an instance took them, False if none is listening
    """
    sock = QtNetwork.QLocalSocket()
    sock.connectToServer(server_name())
    if not sock.waitForConnected(timeout_ms):
        return False

    if sys.platform == 'win32':
        # let the open window come to the front: only the process that has the foreground may give that right
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
        except Exception:
            pass

    message = json.dumps({'files': [str(f) for f in files]}) + '\n'
    data = message.encode('utf-8')
    sent = sock.write(data) == len(data)
    sock.flush()
    # on Windows this returns False when the pipe took the bytes already: the result is not the outcome
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    if sock.state() != QtNetwork.QLocalSocket.LocalSocketState.UnconnectedState:
        sock.waitForDisconnected(timeout_ms)
    return sent


class InstanceServer(QtCore.QObject):
    """Receives the files that a second launch sends. Runs in the main thread."""

    files_received = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = None
        self.buffers = {}

    def start(self):
        """
        :return: True if this process listens now
        """
        name = server_name()
        # another open instance keeps the name: removeServer() below would delete its unix socket, and on Windows a
        # second pipe with the same name would share the connections
        probe = QtNetwork.QLocalSocket()
        probe.connectToServer(name)
        if probe.waitForConnected(100):
            probe.abort()
            log.debug("SingleInstance: another instance listens on %s." % name)
            return False
        self.server = QtNetwork.QLocalServer(self)
        self.server.setSocketOptions(QtNetwork.QLocalServer.SocketOption.UserAccessOption)
        if not self.server.listen(name):
            # a crashed instance leaves its unix socket file behind
            QtNetwork.QLocalServer.removeServer(name)
            if not self.server.listen(name):
                log.warning("SingleInstance: cannot listen on %s: %s" % (name, self.server.errorString()))
                return False
        self.server.newConnection.connect(self._on_new_connection)
        return True

    def close(self):
        if self.server is not None:
            try:
                self.server.close()
            except Exception:
                pass
        for sock in list(self.buffers):
            try:
                sock.abort()
            except Exception:
                pass
        self.buffers.clear()

    def _on_new_connection(self):
        for _i in range(64):
            if self.server is None or not self.server.hasPendingConnections():
                break
            sock = self.server.nextPendingConnection()
            self.buffers[sock] = bytearray()
            sock.readyRead.connect(lambda s=sock: self._on_ready_read(s))
            sock.disconnected.connect(lambda s=sock: self._on_disconnected(s))
            # a sender that is quick may have written and gone before the signals were connected
            if sock.bytesAvailable():
                self._on_ready_read(sock)
            if sock.state() == QtNetwork.QLocalSocket.LocalSocketState.UnconnectedState:
                self._on_disconnected(sock)

    def _on_ready_read(self, sock):
        buf = self.buffers.get(sock)
        if buf is None:
            return
        buf += bytes(sock.readAll())
        if len(buf) > MAX_MESSAGE:
            log.warning("SingleInstance: message too big, dropped.")
            self._drop(sock)
            return
        while b'\n' in buf:
            line, _sep, rest = bytes(buf).partition(b'\n')
            buf[:] = rest
            self._handle(line)

    def _on_disconnected(self, sock):
        # a sender that closes without the newline: take what it sent
        buf = self.buffers.get(sock)
        if buf:
            self._handle(bytes(buf))
        self._drop(sock)

    def _drop(self, sock):
        self.buffers.pop(sock, None)
        sock.deleteLater()

    def _handle(self, line):
        try:
            data = json.loads(line.decode('utf-8'))
        except Exception:
            log.warning("SingleInstance: ignored a malformed message.")
            return
        files = data.get('files') if isinstance(data, dict) else None
        if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
            log.warning("SingleInstance: ignored a message with an unexpected content.")
            return
        if files:
            self.files_received.emit(files)


class FileOpenFilter(QtCore.QObject):
    """
    macOS delivers a double-clicked file as a FileOpen event to the running application, also before the App is built.
    The files are kept until the App asks for them.
    """

    files_received = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pending = []
        self.ready = False

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.FileOpen:
            path = event.file()
            if path:
                if self.ready:
                    self.files_received.emit([path])
                else:
                    self.pending.append(path)
            return True
        return False

    def set_ready(self):
        """The App can take files now: hand over those that came before."""
        self.ready = True
        if self.pending:
            files, self.pending = self.pending, []
            self.files_received.emit(files)
