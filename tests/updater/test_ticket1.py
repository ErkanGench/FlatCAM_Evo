"""Focused tests for the Ticket 1 updater core."""

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from services.updater.manifest import (
    ArchiveInfo,
    DeletionEntry,
    FileEntry,
    ManifestError,
    Manifest,
    compare_versions,
    manifest_to_json,
    parse_manifest,
    select_channel,
    validate_relative_path,
)
from services.updater.release import (
    DEFAULT_EXCLUSION_POLICY,
    prepare_releases,
)
from services.updater.transport import (
    DigiPublicShareTransport,
    DownloadCancelled,
    TransportError,
)


LINK_ID = "28e6f3bf-0636-46b7-8bdc-d1f7b105f7a0"
DYNAMIC_LINK_ID = "6f1d2a3b-4c5d-4e6f-8a7b-9c0d1e2f3a4b"
SECOND_DYNAMIC_LINK_ID = "7a2e3b4c-5d6f-4a7b-8c9d-0e1f2a3b4c5d"
SHORT_URL = "https://s.go.ro/zihniipc"
CANONICAL_URL = f"https://storage.rcs-rds.ro/links/{LINK_ID}"
ORIGIN_URL = "https://storage.rcs-rds.ro"
METADATA_URL = f"{ORIGIN_URL}/api/v2/public/links/{LINK_ID}"
LISTING_URL = f"{METADATA_URL}/bundle?path=%2Fwindows"
CONTENT_URL = (
    f"{ORIGIN_URL}/content/links/{LINK_ID}/files/get/flatcam-windows.zip"
    "?path=%2Fwindows%2Fflatcam-windows.zip"
)


class FakeResponse:
    def __init__(self, body=b"", url=None, headers=None, status=200):
        self._body = body
        self._position = 0
        self.url = url
        self.headers = headers or {}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def geturl(self):
        return self.url

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self._body) - self._position
        end = min(self._position + size, len(self._body))
        result = self._body[self._position:end]
        self._position = end
        return result


class DigiOpener:
    def __init__(self, archive=b"archive-bytes", link_id=LINK_ID, redirect_url=None, metadata_id=None):
        self.archive = archive
        self.link_id = link_id
        self.redirect_url = redirect_url
        self.metadata_id = metadata_id
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        url = request.full_url
        canonical_url = self.redirect_url or f"https://storage.rcs-rds.ro/links/{self.link_id}"
        metadata_url = f"https://storage.rcs-rds.ro/api/v2/public/links/{self.link_id}"
        listing_url = f"{metadata_url}/bundle?path=%2Fwindows"
        content_url = (
            f"https://storage.rcs-rds.ro/content/links/{self.link_id}/files/get/flatcam-windows.zip"
            "?path=%2Fwindows%2Fflatcam-windows.zip"
        )
        if url == SHORT_URL:
            return FakeResponse(url=canonical_url)
        if url == metadata_url:
            body = json.dumps({"id": self.metadata_id or self.link_id, "public": True}).encode()
            return FakeResponse(body=body, url=url)
        if url == listing_url:
            body = json.dumps({
                "files": [{"name": "flatcam-windows.zip", "size": len(self.archive)}]
            }).encode()
            return FakeResponse(body=body, url=url)
        if url == content_url:
            return FakeResponse(
                body=self.archive,
                url=url,
                headers={"Content-Length": str(len(self.archive))},
            )
        raise AssertionError(f"unexpected URL: {url}")


class TestManifestCore(unittest.TestCase):
    def test_platform_mapping_uses_linux_channel_for_linux_and_darwin(self):
        self.assertEqual("windows", select_channel("Windows"))
        self.assertEqual("windows", select_channel("win32"))
        self.assertEqual("linux", select_channel("Linux"))
        self.assertEqual("linux", select_channel("Darwin"))

    def test_version_comparison_orders_release_then_build(self):
        self.assertLess(compare_versions("1.2", "1.3"), 0)
        self.assertGreater(compare_versions("1.3", "1.2"), 0)
        self.assertGreater(compare_versions("1.3", "1.3", "build 12", "build 11"), 0)

    def test_manifest_round_trip_contains_archive_and_deletion_history(self):
        manifest = Manifest(
            schema_version=1,
            channel="linux",
            version="1.2.3",
            build_string="build 12",
            version_date="2026-09-17",
            minimum_required_version="1.0",
            release_notes="Bug fixes",
            archive=ArchiveInfo("flatcam-source.zip", 12, "a" * 64),
            files=(FileEntry("flatcam.py", 4, "b" * 64),),
            deletions=(DeletionEntry("old.py", "1.2.0"),),
        )

        encoded = manifest_to_json(manifest)
        parsed = parse_manifest(encoded)

        self.assertEqual(manifest, parsed)
        self.assertEqual(encoded, manifest_to_json(parsed))

    def test_manifest_rejects_malformed_required_data_and_traversal(self):
        base = {
            "schema_version": 1,
            "channel": "linux",
            "version": "1.0",
            "build": "build 1",
            "version_date": "2026-09-17",
            "minimum_required_version": "0",
            "release_notes": "",
            "archive": {"filename": "flatcam-source.zip", "size": 1, "sha256": "a" * 64},
            "files": [{"path": "flatcam.py", "size": 1, "sha256": "b" * 64}],
            "deletions": [],
        }

        for field in ("archive", "files", "version"):
            malformed = dict(base)
            malformed.pop(field)
            with self.subTest(field=field):
                with self.assertRaises(ManifestError):
                    parse_manifest(malformed)

        malformed = dict(base)
        malformed["files"] = [{"path": "../evil", "size": 1, "sha256": "b" * 64}]
        with self.assertRaises(ManifestError):
            parse_manifest(malformed)

        malformed = dict(base)
        malformed["archive"] = {
            "filename": "C:/evil.zip",
            "size": 1,
            "sha256": "a" * 64,
        }
        with self.assertRaises(ManifestError):
            parse_manifest(malformed)

    def test_relative_path_validation_rejects_absolute_and_parent_paths(self):
        for path in ("../evil", "/evil", "\\evil", "C:/evil", "a/../../evil"):
            with self.subTest(path=path):
                with self.assertRaises(ManifestError):
                    validate_relative_path(path)


class TestDigiTransport(unittest.TestCase):
    def _transport(self, archive=b"archive-bytes"):
        opener = DigiOpener(archive)
        transport = DigiPublicShareTransport(
            SHORT_URL,
            expected_link_id=LINK_ID,
            opener=opener,
            timeout=7,
        )
        return transport, opener

    def test_short_link_redirect_and_canonical_metadata_are_validated(self):
        transport, opener = self._transport()

        try:
            metadata = transport.resolve_share()
        except Exception as exc:
            self.fail(f"canonical endpoint request was rejected: {exc}")

        self.assertEqual(LINK_ID, metadata.link_id)
        self.assertEqual(CANONICAL_URL, metadata.canonical_url)
        self.assertEqual(ORIGIN_URL, metadata.origin_url)
        self.assertEqual(
            [SHORT_URL, METADATA_URL],
            [request.full_url for request, _ in opener.requests],
        )
        self.assertEqual(7, opener.requests[0][1])

    def test_digi_listing_and_download_use_documented_paths_and_referer(self):
        transport, opener = self._transport()

        try:
            remote = transport.check_file("windows", "flatcam-windows.zip")
            payload = transport.download_bytes("windows", "flatcam-windows.zip")
        except Exception as exc:
            self.fail(f"Digi endpoint request was rejected: {exc}")

        self.assertEqual("flatcam-windows.zip", remote.name)
        self.assertEqual(b"archive-bytes", payload)
        self.assertEqual(
            [SHORT_URL, METADATA_URL, LISTING_URL, CONTENT_URL],
            [request.full_url for request, _ in opener.requests],
        )
        for request, _ in opener.requests[1:]:
            self.assertEqual(CANONICAL_URL, request.get_header("Referer"))
            self.assertNotIn("Authorization", dict(request.header_items()))
            self.assertNotIn("Cookie", dict(request.header_items()))

    def test_default_transport_resolves_dynamic_id_and_reuses_it_for_operation(self):
        opener = DigiOpener(link_id=DYNAMIC_LINK_ID)
        transport = DigiPublicShareTransport(SHORT_URL, opener=opener)

        remote = transport.check_file("windows", "flatcam-windows.zip")
        payload = transport.download_bytes("windows", "flatcam-windows.zip")

        metadata_url = f"{ORIGIN_URL}/api/v2/public/links/{DYNAMIC_LINK_ID}"
        listing_url = f"{metadata_url}/bundle?path=%2Fwindows"
        content_url = (
            f"{ORIGIN_URL}/content/links/{DYNAMIC_LINK_ID}/files/get/flatcam-windows.zip"
            "?path=%2Fwindows%2Fflatcam-windows.zip"
        )
        canonical_url = f"{ORIGIN_URL}/links/{DYNAMIC_LINK_ID}"
        self.assertEqual("flatcam-windows.zip", remote.name)
        self.assertEqual(b"archive-bytes", payload)
        self.assertEqual(
            [SHORT_URL, metadata_url, listing_url, content_url],
            [request.full_url for request, _ in opener.requests],
        )
        self.assertEqual(1, sum(request.full_url == SHORT_URL for request, _ in opener.requests))
        for request, _ in opener.requests[1:]:
            self.assertEqual(canonical_url, request.get_header("Referer"))

    def test_new_transport_resolves_current_id_without_persistent_pin(self):
        first = DigiPublicShareTransport(
            SHORT_URL,
            opener=DigiOpener(link_id=DYNAMIC_LINK_ID),
        )
        second = DigiPublicShareTransport(
            SHORT_URL,
            opener=DigiOpener(link_id=SECOND_DYNAMIC_LINK_ID),
        )

        self.assertEqual(DYNAMIC_LINK_ID, first.resolve_share().link_id)
        self.assertEqual(SECOND_DYNAMIC_LINK_ID, second.resolve_share().link_id)

    def test_download_rejects_unsafe_remote_name(self):
        transport, _ = self._transport()

        with self.assertRaises(ManifestError):
            transport.download_bytes("windows", "../flatcam-windows.zip")

    def test_stream_download_cancellation_removes_partial_and_preserves_destination(self):
        transport, _ = self._transport(archive=b"0123456789")
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "flatcam-windows.zip"
            destination.write_bytes(b"old archive")
            calls = []

            def cancel():
                calls.append(True)
                return len(calls) > 1

            with self.assertRaises(DownloadCancelled):
                transport.download_archive(
                    "windows",
                    "flatcam-windows.zip",
                    destination,
                    cancel_cb=cancel,
                )

            self.assertEqual(b"old archive", destination.read_bytes())
            self.assertFalse(Path(str(destination) + ".part").exists())

    def test_stream_download_verifies_hash_and_replaces_atomically(self):
        payload = b"known archive"
        transport, _ = self._transport(archive=payload)
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "flatcam-windows.zip"
            destination.write_bytes(b"old archive")
            observed = []

            def progress(written, total):
                observed.append((written, total, destination.read_bytes()))

            result = transport.download_archive(
                "windows",
                "flatcam-windows.zip",
                destination,
                expected_size=len(payload),
                expected_sha256=hashlib.sha256(payload).hexdigest(),
                progress_cb=progress,
            )

            self.assertEqual(destination, result)
            self.assertEqual(payload, destination.read_bytes())
            self.assertTrue(observed)
            self.assertTrue(all(old == b"old archive" for _, _, old in observed))

    def test_non_https_canonical_link_is_rejected(self):
        opener = DigiOpener()
        transport = DigiPublicShareTransport(
            "http://s.go.ro/zihniipc",
            expected_link_id=LINK_ID,
            opener=opener,
        )

        with self.assertRaises(TransportError):
            transport.resolve_share()

    def test_non_digi_canonical_link_is_rejected(self):
        opener = DigiOpener(
            redirect_url=f"https://example.com/links/{DYNAMIC_LINK_ID}",
        )
        transport = DigiPublicShareTransport(SHORT_URL, opener=opener)

        with self.assertRaises(TransportError):
            transport.resolve_share()

    def test_invalid_canonical_link_path_is_rejected(self):
        opener = DigiOpener(
            redirect_url=f"{ORIGIN_URL}/not-links/{DYNAMIC_LINK_ID}",
        )
        transport = DigiPublicShareTransport(SHORT_URL, opener=opener)

        with self.assertRaises(TransportError):
            transport.resolve_share()

    def test_mismatching_metadata_id_is_rejected(self):
        opener = DigiOpener(
            link_id=DYNAMIC_LINK_ID,
            metadata_id=SECOND_DYNAMIC_LINK_ID,
        )
        transport = DigiPublicShareTransport(SHORT_URL, opener=opener)

        with self.assertRaises(TransportError):
            transport.resolve_share()


class TestReleasePreparation(unittest.TestCase):
    def _make_roots(self, directory):
        windows = Path(directory) / "windows-root"
        linux = Path(directory) / "linux-root"
        for root in (windows, linux):
            (root / "app").mkdir(parents=True)
            (root / "app" / "main.py").write_text("print('ok')", encoding="utf-8")
            (root / "resources.txt").write_text("resource", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "test_app.py").write_text("not payload", encoding="utf-8")
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "main.pyc").write_bytes(b"cache")
            (root / "docs").mkdir()
            (root / "docs" / "README.md").write_text("not payload", encoding="utf-8")
            (root / "make_freezed.py").write_text("build script", encoding="utf-8")
            (root / "build.py").write_text("build script", encoding="utf-8")
        return windows, linux

    def test_exclusion_policy_is_explicit_and_excludes_build_inputs(self):
        for path in (
            "tests/test.py",
            "docs/readme.md",
            "__pycache__/x.pyc",
            ".cache/generated",
            "make_freezed.py",
            "build.py",
        ):
            self.assertTrue(DEFAULT_EXCLUSION_POLICY.excludes(path), path)

    def test_preparation_builds_checksumed_deterministic_pairs_and_upload_paths(self):
        with TemporaryDirectory() as directory:
            windows, linux = self._make_roots(directory)
            output_one = Path(directory) / "release-one"
            output_two = Path(directory) / "release-two"
            kwargs = {
                "version": "1.2.3",
                "build_string": "build 12",
                "version_date": "2026-09-17",
                "minimum_required_version": "1.0",
                "release_notes": "Notes",
            }

            first = prepare_releases({"windows": windows, "linux": linux}, output_one, **kwargs)
            second = prepare_releases({"windows": windows, "linux": linux}, output_two, **kwargs)

            first_windows = first.artifacts["windows"]
            second_windows = second.artifacts["windows"]
            self.assertEqual(
                first_windows.archive_path.read_bytes(),
                second_windows.archive_path.read_bytes(),
            )
            self.assertEqual(
                first_windows.manifest_path.read_bytes(),
                second_windows.manifest_path.read_bytes(),
            )
            self.assertEqual(4, len(first.upload_paths))
            self.assertEqual(
                {
                    "app/main.py",
                    "resources.txt",
                },
                {entry.path for entry in first_windows.manifest.files},
            )
            archive_bytes = first_windows.archive_path.read_bytes()
            self.assertEqual(len(archive_bytes), first_windows.manifest.archive.size)
            self.assertEqual(
                hashlib.sha256(archive_bytes).hexdigest(),
                first_windows.manifest.archive.sha256,
            )
            self.assertTrue(all(path.exists() for path in first.upload_paths))


if __name__ == "__main__":
    unittest.main()
