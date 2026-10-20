"""Ticket 5 acceptance tests: GitHub wiring, pre-manifest UI, staged installs."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from defaults import AppDefaults
from services.updater.github.transport import DEFAULT_REPOSITORY


@pytest.fixture
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class Signal:
    def __init__(self):
        self.emissions = []

    def emit(self, *args):
        self.emissions.append(args)


def _fake_app(tmp_path):
    from appMain import App
    from defaults import AppDefaults as Defaults

    app = App.__new__(App)
    app.data_path = str(tmp_path)
    app.options = {}
    app.defaults = Defaults(beta=False, version="1.0")
    app.log = MagicMock()
    app.inform = Signal()
    app.update_progress = Signal()
    app.update_staged = Signal()
    app.worker_task = Signal()
    app.ui = None
    app._update_dialog = None
    app._update_progress_dialog = None
    app._update_in_progress = False
    app._update_cancel_event = None
    app._rollback_in_progress = False
    app._release_preparation_in_progress = False
    app._manual_update_requested = False
    app._check_in_progress = False
    app._check_queued = False
    app.save_in_progress = False
    app.quit_application = MagicMock()
    app._updater_shutdown_preflight = MagicMock(return_value=True)
    return app


def _payload(**overrides):
    payload = {
        "status": "update_available",
        "channel": "windows",
        "mandatory": False,
        "current": {"version": "1.0", "build": ""},
        "current_version": "1.0",
        "current_build": "",
        "tag": "v1.1",
        "version": "1.1",
        "build_string": "github:mariusadrian88/flatcam_evo:1.1",
        "release_notes": "Plain <b>notes</b>",
        "published_at": "2026-09-17T10:00:00Z",
        "release_page": "https://github.com/MariusAdrian88/FlatCAM_Evo/releases/tag/v1.1",
        "zipball_url": "https://api.github.com/repos/MariusAdrian88/FlatCAM_Evo/zipball/v1.1",
        "asset": {
            "name": "flatcam-evo-windows-x64-update.zip",
            "url": "https://example.invalid/flatcam-evo-windows-x64-update.zip",
            "size": 2048,
            "sha256": "a" * 64,
        },
        "deletions_asset": None,
        "install": "windows_asset",
        "automatic": True,
        "manual": False,
    }
    payload.update(overrides)
    return payload


def _manifest_dict():
    return {
        "schema_version": 1,
        "channel": "windows",
        "version": "1.1",
        "build": "github:mariusadrian88/flatcam_evo:1.1",
        "version_date": "2026-09-17T10:00:00Z",
        "minimum_required_version": "0",
        "release_notes": "notes",
        "archive": {"filename": "flatcam-evo-windows-x64-update.zip", "size": 3, "sha256": "b" * 64},
        "files": [],
        "deletions": [],
    }


def test_factory_update_url_is_the_github_repository():
    assert DEFAULT_REPOSITORY == "https://github.com/MariusAdrian88/FlatCAM_Evo"
    assert AppDefaults.factory_defaults["global_update_url"] == DEFAULT_REPOSITORY


def test_exact_legacy_digi_default_migrates_to_github(tmp_path):
    filename = tmp_path / "current_defaults.FlatConfig"
    filename.write_text(json.dumps({"global_update_url": "https://s.go.ro/zihniipc", "units": "IN"}))

    defaults = AppDefaults(beta=False, version="1.0")
    defaults.load(str(filename), MagicMock())

    assert defaults["global_update_url"] == DEFAULT_REPOSITORY
    assert defaults["units"] == "IN"


def test_custom_update_url_survives_the_digi_migration(tmp_path):
    filename = tmp_path / "current_defaults.FlatConfig"
    filename.write_text(json.dumps({"global_update_url": "https://mirror.example.invalid/updates"}))

    defaults = AppDefaults(beta=False, version="1.0")
    defaults.load(str(filename), MagicMock())

    # A custom share saved before the provider choice is kept for the legacy Digi provider.
    assert defaults["global_legacy_update_url"] == "https://mirror.example.invalid/updates"
    assert defaults["global_update_url"] == DEFAULT_REPOSITORY


def test_both_entrypoints_construct_the_github_checker():
    import appMain
    from services.updater.github.checker import GitHubUpdateChecker

    assert appMain.GitHubUpdateChecker is GitHubUpdateChecker
    assert not hasattr(appMain, "UpdateChecker")
    assert "create_update_checker" in inspect.getsource(appMain.App._setup_defaults_and_preferences)

    import appHandlers.appLifecycle as lifecycle_module

    source = inspect.getsource(lifecycle_module.AppLifecycle.version_check)
    assert "checker_for" in source
    assert "digi.checker" not in source


def test_dialog_renders_premanifest_metadata_and_plain_notes(qapp):
    from appGUI.UpdateDialog import UpdateDialog

    dialog = UpdateDialog(None, _payload())
    texts = " ".join(label.text() for label in dialog.findChildren(QtWidgets.QLabel))

    assert "1.1" in texts
    assert "2.0 KB" in texts
    assert dialog.findChild(QtWidgets.QTextBrowser).toPlainText() == "Plain <b>notes</b>"
    buttons = {button.text() for button in dialog.findChildren(QtWidgets.QPushButton)}
    assert "Update now" in buttons


def test_source_dialog_reports_the_unknown_size(qapp):
    from appGUI.UpdateDialog import UpdateDialog

    dialog = UpdateDialog(None, _payload(channel="linux", install="linux_zipball", asset=None))
    texts = " ".join(label.text() for label in dialog.findChildren(QtWidgets.QLabel))

    assert "unknown" in texts.lower()
    assert dialog.findChild(QtWidgets.QTextBrowser).toPlainText() == "Plain <b>notes</b>"


def test_linux_dialog_ignores_the_windows_asset_size(qapp):
    from appGUI.UpdateDialog import UpdateDialog

    payload = _payload(
        channel="linux",
        install="linux_zipball",
        asset={"name": "flatcam-evo-windows-x64-update.zip", "size": 2048, "sha256": "a" * 64},
    )
    dialog = UpdateDialog(None, payload)
    texts = " ".join(label.text() for label in dialog.findChildren(QtWidgets.QLabel))

    assert "unknown" in texts.lower()
    assert "2.0 KB" not in texts


def test_release_details_display_the_manifest_build_key():
    from appGUI.UpdateDialog import _release_details

    details = _release_details({"manifest": {"version": "2.0", "build": "manifest-build"}})

    assert details["build"] == "manifest-build"


def test_manual_dialog_links_the_release_and_never_offers_a_download(qapp):
    from appGUI.UpdateDialog import UpdateDialog

    payload = _payload(install="manual", automatic=False, manual=True, manual_reason="appimage")
    dialog = UpdateDialog(None, payload)
    texts = " ".join(label.text() for label in dialog.findChildren(QtWidgets.QLabel))

    assert dialog.update_button is None
    assert "replace this installation manually" in texts
    assert payload["release_page"] in texts
    assert not any(button.text() == "Update now" for button in dialog.findChildren(QtWidgets.QPushButton))


def test_automatic_manual_offer_is_ignored_but_a_manual_check_shows_it(qapp, tmp_path):
    from appMain import App

    app = _fake_app(tmp_path)
    app._start_update_download = MagicMock()
    payload = _payload(install="manual", automatic=False, manual=True, manual_reason="appimage")

    App.on_update_available(app, payload)
    assert app._update_dialog is None
    app._start_update_download.assert_not_called()

    app._manual_update_requested = True
    App.on_update_available(app, payload)
    assert app._update_dialog is not None
    app._update_dialog._on_other()
    app._start_update_download.assert_not_called()


class RecordingDialog:
    last = None

    def __init__(self, *args, **kwargs):
        RecordingDialog.last = self
        self.range = (0, 100)
        self.label = ""
        self.value = 0
        self.canceled = SimpleNamespace(connect=lambda slot: None)
        self.visible = False

    def setWindowTitle(self, _title):
        pass

    def setWindowModality(self, _modality):
        pass

    def setAutoClose(self, _value):
        pass

    def setAutoReset(self, _value):
        pass

    def setRange(self, low, high):
        self.range = (low, high)

    def maximum(self):
        return self.range[1]

    def setLabelText(self, text):
        self.label = text

    def setValue(self, value):
        self.value = value

    def show(self):
        self.visible = True

    def close(self):
        self.visible = False


def test_source_download_progress_is_indeterminate_until_a_total_arrives(monkeypatch, tmp_path):
    from appMain import App

    app = _fake_app(tmp_path)
    monkeypatch.setattr("appMain.QtWidgets.QProgressDialog", RecordingDialog)

    App._start_update_download(app, _payload(channel="linux", install="linux_zipball", asset=None))
    dialog = RecordingDialog.last
    assert dialog.range == (0, 0)
    assert app.worker_task.emissions

    App._on_update_progress(app, -1, "Downloading update...")
    assert dialog.range == (0, 0)

    App._on_update_progress(app, 50, "Downloading update: 50%")
    assert dialog.range == (0, 100)
    assert dialog.value == 50


def test_windows_download_progress_uses_the_known_asset_size(monkeypatch, tmp_path):
    from appMain import App

    app = _fake_app(tmp_path)
    monkeypatch.setattr("appMain.QtWidgets.QProgressDialog", RecordingDialog)

    App._start_update_download(app, _payload())

    assert RecordingDialog.last.range == (0, 100)


def test_dependency_warning_cancels_before_preflight_and_launch(qapp, monkeypatch, tmp_path):
    from appMain import App

    app = _fake_app(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    archive = staging / "flatcam-evo-linux-source.zip"
    archive.write_bytes(b"source")
    launch = MagicMock(return_value=True)
    monkeypatch.setattr("appMain.launch_update", launch)
    observed = {}

    def cancel_dialog(box):
        observed["format"] = box.textFormat()
        observed["text"] = box.text()
        observed["default"] = box.defaultButton().text()
        return QtWidgets.QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", cancel_dialog)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        MagicMock(side_effect=AssertionError("untested static prompt")),
    )

    App.on_update_staged(app, {
        "staging_dir": str(staging),
        "archive_path": str(archive),
        "manifest": _manifest_dict() | {"channel": "linux"},
        "channel": "linux",
        "trust": "Source archive downloaded over HTTPS from GitHub; TLS only, no published digest.",
        "dependencies": {"changed": True, "added": ["newdep<2.0"], "removed": []},
    })

    launch.assert_not_called()
    app._updater_shutdown_preflight.assert_not_called()
    app.quit_application.assert_not_called()
    assert not staging.exists()
    assert app._update_in_progress is False
    assert app._update_cancel_event is None
    assert observed["format"] == QtCore.Qt.TextFormat.PlainText
    assert "newdep<2.0" in observed["text"]
    assert observed["default"] == "Cancel"


def test_staged_update_confirms_trust_then_launches_the_same_manifest(qapp, monkeypatch, tmp_path):
    from appMain import App

    app = _fake_app(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    archive = staging / "flatcam-evo-windows-x64-update.zip"
    archive.write_bytes(b"archive")
    manifest = _manifest_dict()
    launch = MagicMock(return_value=True)
    monkeypatch.setattr("appMain.launch_update", launch)
    observed = {}

    def confirm_dialog(box):
        observed["format"] = box.textFormat()
        observed["text"] = box.text()
        return QtWidgets.QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", confirm_dialog)

    App.on_update_staged(app, {
        "staging_dir": str(staging),
        "archive_path": str(archive),
        "manifest": manifest,
        "channel": "windows",
        "trust": "Update archive verified against the published GitHub SHA-256 digest.",
        "dependencies": {"changed": False, "added": [], "removed": []},
    })

    assert observed["format"] == QtCore.Qt.TextFormat.PlainText
    assert "Trust:" in observed["text"]
    launch.assert_called_once()
    assert launch.call_args[0][1] == manifest
    assert launch.call_args[0][2] == str(archive)
    app._updater_shutdown_preflight.assert_called_once()
    app.quit_application.assert_called_once_with(mode="updater")
    assert not staging.exists()


def test_cancellation_after_worker_success_prevents_the_gui_launch(monkeypatch, tmp_path):
    from appMain import App

    app = _fake_app(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    archive = staging / "flatcam-evo-windows-x64-update.zip"
    archive.write_bytes(b"archive")
    staged = SimpleNamespace(
        staging_dir=staging,
        archive_path=archive,
        manifest=_manifest_dict(),
        channel="windows",
        install="windows_asset",
        trust="Update archive verified against the published GitHub SHA-256 digest.",
        dependencies={"changed": False, "added": [], "removed": []},
    )
    monkeypatch.setattr("appMain.stage_update", lambda *args, **kwargs: staged)
    app.update_checker = SimpleNamespace(create_transport=lambda app, repository_url=None: object())

    cancel = threading.Event()
    App._download_update_worker(app, {"status": "update_available"}, cancel)
    data = app.update_staged.emissions[0][0]
    assert data["canceled"] is False

    launch = MagicMock(return_value=True)
    monkeypatch.setattr("appMain.launch_update", launch)
    app._update_cancel_event = cancel
    app._update_in_progress = True
    cancel.set()

    App.on_update_staged(app, data)

    launch.assert_not_called()
    app._updater_shutdown_preflight.assert_not_called()
    app.quit_application.assert_not_called()
    assert not staging.exists()
    assert app._update_in_progress is False
    assert app._update_cancel_event is None
    assert any("canceled" in emission[0].lower() for emission in app.inform.emissions)


def _main_window_close_ignored(app):
    from appGUI.MainGUI import MainGUI

    class Event:
        def __init__(self):
            self.ignore_calls = 0

        def ignore(self):
            self.ignore_calls += 1

    gui = MainGUI.__new__(MainGUI)
    gui.app = app
    gui.final_save = SimpleNamespace(emit=MagicMock())
    gui.geometry = MagicMock(return_value=SimpleNamespace(x=lambda: 0, y=lambda: 0, width=lambda: 1, height=lambda: 1))
    gui.lock_action = SimpleNamespace(isChecked=lambda: False)
    gui.show_text_action = SimpleNamespace(isChecked=lambda: False)
    gui.isMaximized = lambda: False
    gui.saveState = lambda *_args: b"state"
    gui.splitter = SimpleNamespace(sizes=lambda: [1])
    event = Event()
    with patch("appGUI.MainGUI.QSettings"):
        gui.closeEvent(event)
    return event.ignore_calls == 1 and not gui.final_save.emit.called


def test_confirmation_keeps_the_operation_guard_and_blocks_duplicates(qapp, monkeypatch, tmp_path):
    from appMain import App

    app = _fake_app(tmp_path)
    app._update_in_progress = True
    staging = tmp_path / "staging"
    staging.mkdir()
    archive = staging / "flatcam-evo-windows-x64-update.zip"
    archive.write_bytes(b"archive")
    launch = MagicMock(return_value=True)
    monkeypatch.setattr("appMain.launch_update", launch)
    observed = {}

    def approve(box):
        observed["active"] = App._update_operation_active(app)
        App.on_update_available(app, _payload())
        observed["duplicate_dialog"] = app._update_dialog
        emissions = len(app.worker_task.emissions)
        App._start_update_download(app, _payload())
        observed["duplicate_download"] = len(app.worker_task.emissions) == emissions
        observed["close_ignored"] = _main_window_close_ignored(app)
        return QtWidgets.QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", approve)

    App.on_update_staged(app, {
        "staging_dir": str(staging),
        "archive_path": str(archive),
        "manifest": _manifest_dict(),
        "channel": "windows",
        "trust": "Update archive verified against the published GitHub SHA-256 digest.",
        "dependencies": {"changed": False, "added": [], "removed": []},
    })

    assert observed["active"] is True
    assert observed["duplicate_dialog"] is None
    assert observed["duplicate_download"] is True
    assert observed["close_ignored"] is True
    launch.assert_called_once()
    assert not staging.exists()


def test_lifecycle_github_entrypoint_uses_the_default_repository(monkeypatch, tmp_path):
    from appHandlers.appLifecycle import AppLifecycle
    from services.updater.github import checker as checker_module
    from services.updater.github.checker import GitHubUpdateChecker

    app = SimpleNamespace(
        options={"global_version_check": True},
        defaults={"global_version_check": True},
        version="1.0",
        build_string="build-1",
        os="win32",
        data_path=str(tmp_path),
        log=MagicMock(),
        inform=Signal(),
        update_available=Signal(),
        update_check_result=Signal(),
        update_checker=None,
    )
    captured = []

    class ConfiguredTransport:
        def __init__(self, repository, **kwargs):
            captured.append(repository)

        def list_releases(self):
            return ()

    monkeypatch.setattr(checker_module, "GitHubReleaseTransport", ConfiguredTransport)

    result = AppLifecycle(app).version_check(forced=True)

    assert result["status"] == "up_to_date"
    assert captured == [DEFAULT_REPOSITORY]
    assert isinstance(app.update_checker, GitHubUpdateChecker)


def test_failed_helper_stays_running_and_removes_the_stage(qapp, monkeypatch, tmp_path):
    from appMain import App

    app = _fake_app(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    archive = staging / "flatcam-evo-windows-x64-update.zip"
    archive.write_bytes(b"archive")
    monkeypatch.setattr("appMain.launch_update", MagicMock(return_value=False))
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "exec",
        lambda _box: QtWidgets.QMessageBox.StandardButton.Yes,
    )

    App.on_update_staged(app, {
        "staging_dir": str(staging),
        "archive_path": str(archive),
        "manifest": _manifest_dict(),
        "channel": "windows",
        "trust": "Update archive verified against the published GitHub SHA-256 digest.",
        "dependencies": {"changed": False, "added": [], "removed": []},
    })

    app.quit_application.assert_not_called()
    assert not staging.exists()
    assert app._update_in_progress is False
    assert app._update_cancel_event is None
    assert any("updater could not be started" in emission[0].lower() for emission in app.inform.emissions)


def _launcher_fixture(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    archive = staging / "flatcam-evo-windows-x64-update.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("flatcam.py", b"new entry")
    data = archive.read_bytes()
    manifest = {
        "schema_version": 1,
        "channel": "windows",
        "version": "2.0",
        "build": "build-2",
        "version_date": "2026-09-17",
        "minimum_required_version": "0",
        "release_notes": "",
        "archive": {
            "filename": archive.name,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        "files": [{"path": "flatcam.py", "size": 9, "sha256": hashlib.sha256(b"new entry").hexdigest()}],
        "deletions": [],
    }
    return staging, archive, manifest


def test_launcher_owns_a_verified_archive_copy_before_stage_cleanup(monkeypatch, tmp_path):
    import services.updater.launcher as launcher_module
    import updater_app
    from services.updater.launcher import launch_update

    staging, archive, manifest = _launcher_fixture(tmp_path)
    app = SimpleNamespace(data_path=str(tmp_path / "data"), log=MagicMock())
    captured = {}

    def fake_popen(argv, **kwargs):
        job = json.loads(Path(argv[3]).read_text(encoding="utf-8"))
        captured["job"] = job
        Path(job["startup_ack_path"]).write_text("started", encoding="utf-8")

    monkeypatch.setattr(launcher_module.subprocess, "Popen", fake_popen)

    assert launch_update(app, manifest, archive, relaunch_argv=["python", "flatcam.py"])

    job_archive = Path(captured["job"]["archive_path"])
    assert job_archive != archive
    assert job_archive.read_bytes() == archive.read_bytes()
    shutil.rmtree(staging)
    assert not archive.exists()
    updater_app._validate_archive(job_archive, manifest["archive"])


def test_failed_launch_removes_the_job_copy_and_keeps_the_original_stage(monkeypatch, tmp_path):
    import services.updater.launcher as launcher_module
    from services.updater.launcher import launch_update

    staging, archive, manifest = _launcher_fixture(tmp_path)
    app = SimpleNamespace(data_path=str(tmp_path / "data"), log=MagicMock())

    def fail_popen(*args, **kwargs):
        raise OSError("helper unavailable")

    monkeypatch.setattr(launcher_module.subprocess, "Popen", fail_popen)

    assert launch_update(app, manifest, archive, relaunch_argv=["python", "flatcam.py"]) is False
    assert archive.exists()
    update_root = tmp_path / "data" / "update"
    assert not update_root.exists() or not any(update_root.iterdir())
