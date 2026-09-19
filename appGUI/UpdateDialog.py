"""Non-blocking update offer dialog."""

from __future__ import annotations

import gettext

from PyQt6 import QtGui, QtWidgets


_ = gettext.gettext


def _human_bytes(value: int) -> str:
    number = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(number) < 1024:
            return f"{number:.1f} {unit}"
        number /= 1024
    return f"{number:.1f} TB"


class UpdateDialog(QtWidgets.QDialog):
    """Display release details without blocking the application event loop."""

    def __init__(self, parent, payload: dict) -> None:
        super().__init__(parent)
        manifest = payload["manifest"]
        current = payload.get("current", {})
        self._mandatory = bool(payload.get("mandatory", False))
        self.choice = "later"

        self.setWindowTitle(_("FlatCAM update available: %s") % manifest.version)
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        current_text = "%s (%s)" % (current.get("version", "unknown"), current.get("build", ""))
        available_text = "%s (%s)" % (manifest.version, manifest.build_string)
        header = QtWidgets.QLabel(
            _("A new version is available: <b>%s</b><br>You have: <b>%s</b>")
            % (available_text, current_text)
        )
        header.setWordWrap(True)
        header.setAccessibleName(_("Update version information"))
        layout.addWidget(header)

        archive_size = QtWidgets.QLabel(
            _("Full archive size: %s") % _human_bytes(manifest.archive.size)
        )
        archive_size.setAccessibleName(_("Update archive size"))
        layout.addWidget(archive_size)

        notes = QtWidgets.QTextBrowser()
        notes.setAccessibleName(_("Release notes"))
        notes.setOpenExternalLinks(True)
        notes.setPlainText(manifest.release_notes or _("No release notes provided."))
        layout.addWidget(notes)

        if self._mandatory:
            warning = QtWidgets.QLabel(
                _("This update is mandatory. Update now or exit FlatCAM.")
            )
            warning.setWordWrap(True)
            warning.setAccessibleName(_("Mandatory update warning"))
            layout.addWidget(warning)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self.update_button = QtWidgets.QPushButton(_("Update now"))
        self.update_button.setDefault(True)
        self.update_button.setAccessibleName(_("Update now"))
        buttons.addWidget(self.update_button)
        self.other_button = QtWidgets.QPushButton(
            _("Exit") if self._mandatory else _("Later")
        )
        self.other_button.setAccessibleName(self.other_button.text())
        buttons.addWidget(self.other_button)
        layout.addLayout(buttons)

        self.update_button.clicked.connect(self._on_update)
        self.other_button.clicked.connect(self._on_other)

    def _on_update(self) -> None:
        self.choice = "update"
        self.accept()

    def _on_other(self) -> None:
        self.choice = "exit" if self._mandatory else "later"
        self.reject()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        self.choice = "exit" if self._mandatory else "later"
        super().closeEvent(event)
