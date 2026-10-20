"""Background update checks for full-archive FlatCAM releases."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from ..manifest import (
    ManifestError,
    compare_versions,
    is_newer,
    parse_manifest,
    parse_version,
    select_channel,
)
from ..recovery import is_release_blocked, restore_dir_for_install
from ..common import (
    app_log as _app_log,
    emit as _emit,
    inform as _inform,
    install_root as _install_root,
    local_build as _local_build,
)


class UpdateChecker:
    """Fetch, validate, and compare one release manifest off the GUI thread."""

    def __init__(
        self,
        app=None,
        *,
        transport_factory=None,
        platform=None,
        install_root=None,
        share_url=None,
    ):
        self.app = app
        self.transport_factory = transport_factory
        self.platform = platform
        self.install_root = install_root
        self.share_url = share_url

    def create_transport(self, app=None, *, share_url=None):
        """Create the configured release transport for checks and downloads."""
        app = app or self.app
        if self.transport_factory is not None:
            return self.transport_factory(app)
        from .transport import DigiPublicShareTransport

        share_url = self.share_url if share_url is None else share_url
        if not share_url:
            raise ValueError("Update share URL is not configured.")
        return DigiPublicShareTransport(short_url=share_url)

    def _transport(self, app=None, *, share_url=None):
        """Compatibility alias for older checker callers."""
        return self.create_transport(app, share_url=share_url)

    def _payload(self, status, channel, app, manifest=None, *, mandatory=False, error=""):
        current = {
            "version": str(getattr(app, "version", "")),
            "build": _local_build(app),
        }
        payload = {
            "status": status,
            "manifest": manifest,
            "channel": channel,
            "mandatory": bool(mandatory),
            "current": current,
            "current_version": current["version"],
            "current_build": current["build"],
            # The offer carries its source so the download uses the same provider and address.
            "provider": "digi",
            "provider_url": getattr(self, "_offer_url", None) or self.share_url,
        }
        if error:
            payload["error"] = error
        return payload

    def run_check(self, app=None, *, forced=False, share_url=None):
        """Run one check and return a result safe for a worker task."""
        app = app or self.app
        self._offer_url = self.share_url if share_url is None else share_url
        try:
            return self._check(app, forced=forced, share_url=share_url)
        except Exception as exc:
            _app_log(app, "error", f"UpdateChecker failed:\n{traceback.format_exc()}")
            channel = self.platform or getattr(app, "os", sys.platform)
            try:
                channel = select_channel(channel)
            except ManifestError:
                channel = "linux"
            result = self._payload("error", channel, app, error=str(exc))
            _inform(app, "Failed checking for the latest version safely.")
            _emit(app, "update_check_result", result)
            return result

    def _check(self, app, *, forced=False, share_url=None):
        preference = getattr(app, "options", None)
        if preference is None:
            preference = getattr(app, "defaults", {})
        defaults = getattr(app, "defaults", {})
        if not forced and not preference.get("global_version_check", defaults.get("global_version_check")):
            channel = select_channel(self.platform or getattr(app, "os", sys.platform))
            result = self._payload("disabled", channel, app)
            _emit(app, "update_check_result", result)
            return result

        channel = select_channel(self.platform or getattr(app, "os", sys.platform))
        transport = self._transport(app, share_url=share_url)
        if transport is None:
            result = self._payload("error", channel, app, error="No update transport is available.")
            _inform(app, "Failed checking for the latest version. No update transport is available.")
            _emit(app, "update_check_result", result)
            return result

        try:
            raw_manifest = transport.download_bytes(channel, "manifest.json")
            manifest = parse_manifest(raw_manifest)
            parse_version(manifest.minimum_required_version)
            if manifest.channel != channel:
                raise ManifestError(
                    f"Manifest channel {manifest.channel!r} does not match {channel!r}."
                )
        except (OSError, ManifestError, RuntimeError, TypeError, ValueError) as exc:
            result = self._payload("error", channel, app, error=str(exc))
            _inform(app, "Failed checking for the latest version. Could not retrieve a valid manifest.")
            _emit(app, "update_check_result", result)
            return result

        local_version = getattr(app, "version", "0")
        local_build = _local_build(app)
        if not is_newer(manifest.version, local_version, manifest.build_string, local_build):
            result = self._payload("up_to_date", channel, app, manifest=manifest)
            _app_log(app, "debug", "The application is up to date.")
            _emit(app, "update_check_result", result)
            return result

        restore_dir = restore_dir_for_install(
            getattr(app, "data_path", Path.home() / ".FlatCAM"),
            self.install_root or _install_root(app),
        )
        if is_release_blocked(restore_dir, manifest.version, manifest.build_string):
            result = self._payload("blocked", channel, app, manifest=manifest)
            _inform(app, "The available release was previously reverted and remains blocked.")
            _emit(app, "update_check_result", result)
            return result

        mandatory = compare_versions(
            manifest.minimum_required_version,
            local_version,
            "",
            local_build,
        ) > 0
        result = self._payload(
            "update_available",
            channel,
            app,
            manifest=manifest,
            mandatory=mandatory,
        )
        _emit(app, "update_check_result", result)
        _emit(app, "update_available", result)
        return result
