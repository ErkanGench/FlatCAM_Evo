"""Stage a verified Digi release archive into a disposable download area."""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path


def stage_update_archive(payload, data_path, transport, *, cancel_cb=None, progress_cb=None):
    """Download one verified full archive into a stable, disposable staging area."""
    manifest = payload["manifest"]
    install_key = hashlib.sha1(str(Path(sys.executable).resolve().parent).encode()).hexdigest()[:8]
    staging_root = Path(data_path) / "update" / f"staging_{install_key}"
    archive_path = staging_root / manifest.archive.filename
    shutil.rmtree(staging_root, ignore_errors=True)
    try:
        return transport.download_archive(
            payload["channel"],
            manifest.archive.filename,
            archive_path,
            expected_size=manifest.archive.size,
            expected_sha256=manifest.archive.sha256,
            progress_cb=progress_cb,
            cancel_cb=cancel_cb,
        )
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
