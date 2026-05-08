"""Phase B D24 / PR #12 — atomic manifest write tests.

Pins the atomic-write contract for ``terrain_io.atomic_write_*`` and the
five manifest-emitter sites that were migrated to use them:

  * ``terrain_io.atomic_write_bytes`` / ``atomic_write_text`` /
    ``atomic_write_json`` are atomic (temp + fsync + ``os.replace``) on
    both Windows and POSIX.
  * On crash mid-write, the destination either contains the prior
    contents (or does not exist), never a half-written prefix.
  * On crash mid-write, the temp ``.tmp`` file is cleaned up so we don't
    accumulate cruft.
  * The migrated callers — ``terrain_unity_export_contracts.write_export_manifest``,
    ``terrain_unity_export._write_json``, ``terrain_navmesh_export.export_navmesh_descriptor``,
    ``terrain_golden_snapshots.save_golden_snapshot`` /
    ``seed_golden_library`` — all route through these helpers.

These are GATE D24 ratchet tests — once green, the manifest-corruption
class of bugs from FIX-D24-PR12 is closed.
"""

from __future__ import annotations

import json
import unittest.mock as _umock
from pathlib import Path

import pytest

from veilbreakers_terrain.handlers.terrain_io import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
)


# ---------------------------------------------------------------------------
# Direct contract — atomic_write_bytes / text / json
# ---------------------------------------------------------------------------


class TestAtomicWriteBytesContract:
    """``atomic_write_bytes`` must be atomic, fsync, and clean up tmp on crash."""

    def test_writes_bytes_to_destination(self, tmp_path: Path) -> None:
        target = tmp_path / "out.bin"
        result = atomic_write_bytes(target, b"hello world")
        assert result == target
        assert target.read_bytes() == b"hello world"

    def test_replaces_existing_file_atomically(self, tmp_path: Path) -> None:
        target = tmp_path / "out.bin"
        target.write_bytes(b"OLD CONTENT")
        atomic_write_bytes(target, b"NEW CONTENT")
        assert target.read_bytes() == b"NEW CONTENT"

    def test_no_tmp_files_remain_after_success(self, tmp_path: Path) -> None:
        target = tmp_path / "out.bin"
        atomic_write_bytes(target, b"payload")
        # Only the final file should exist; no .tmp residue.
        leftover = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftover == [], f"unexpected tmp residue: {leftover}"

    def test_crash_during_replace_leaves_target_untouched(
        self, tmp_path: Path
    ) -> None:
        """If ``os.replace`` raises, the target file must not be corrupted.

        Simulates a crash between temp-write and rename. Pre-fix
        non-atomic writers would have already truncated the target file
        by the time the rename failed.
        """
        target = tmp_path / "out.bin"
        target.write_bytes(b"PRIOR_CONTENT")

        with _umock.patch(
            "veilbreakers_terrain.handlers.terrain_io.os.replace",
            side_effect=OSError("simulated crash mid-rename"),
        ):
            with pytest.raises(OSError, match="simulated crash"):
                atomic_write_bytes(target, b"NEW_CONTENT")

        # Target file is still the prior content — not half-written.
        assert target.read_bytes() == b"PRIOR_CONTENT"
        # No .tmp residue should remain.
        leftover = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftover == [], f"tmp residue not cleaned up: {leftover}"

    def test_crash_during_write_leaves_target_untouched(
        self, tmp_path: Path
    ) -> None:
        """If the inner write raises, the target file must not be touched."""
        target = tmp_path / "out.bin"
        target.write_bytes(b"PRIOR_CONTENT")

        # Force the inner os.fdopen call to raise so the temp file is
        # created (via os.open with O_CREAT|O_EXCL) but the fdopen wrapper
        # never runs. The implementation must close the leaked fd and
        # unlink the temp file on this failure path.
        with _umock.patch(
            "veilbreakers_terrain.handlers.terrain_io.os.fdopen",
            side_effect=OSError("simulated open failure"),
        ):
            with pytest.raises(OSError):
                atomic_write_bytes(target, b"NEW_CONTENT")

        # Target file still the prior content.
        assert target.read_bytes() == b"PRIOR_CONTENT"
        # No tmp leak.
        leftover = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftover == []

    def test_rejects_non_bytes_payload(self, tmp_path: Path) -> None:
        target = tmp_path / "out.bin"
        with pytest.raises(TypeError, match="bytes-like"):
            atomic_write_bytes(target, "not-bytes")  # type: ignore[arg-type]

    def test_rejects_missing_parent_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "missing_subdir" / "out.bin"
        with pytest.raises(FileNotFoundError, match="parent directory"):
            atomic_write_bytes(target, b"data")

    def test_fsync_real_io_error_propagates(self, tmp_path: Path) -> None:
        """Copilot PR #47: a real fsync I/O error must NOT be silently
        swallowed.

        Pre-fix behaviour: ``except (AttributeError, OSError): pass``
        would let an ``OSError(ENOSPC, ...)`` from fsync slip through and
        the subsequent ``os.replace`` would still fire, producing a
        manifest file whose contents may not have reached durable
        storage. The fix discriminates by ``errno``: only "fsync
        unsupported" classes (EINVAL/ENOTSUP/EOPNOTSUPP/EROFS/EBADF) are
        tolerated; ENOSPC / EIO / EDQUOT etc. propagate so the caller
        sees the failure.
        """
        import errno as _errno

        target = tmp_path / "out.bin"
        target.write_bytes(b"PRIOR_CONTENT")

        with _umock.patch(
            "veilbreakers_terrain.handlers.terrain_io.os.fsync",
            side_effect=OSError(_errno.ENOSPC, "no space left on device"),
        ):
            with pytest.raises(OSError) as excinfo:
                atomic_write_bytes(target, b"NEW_CONTENT")
        # Real I/O error surfaced — not silently swallowed.
        assert excinfo.value.errno == _errno.ENOSPC

        # Prior content untouched (the os.replace must not have run after
        # a failed fsync).
        assert target.read_bytes() == b"PRIOR_CONTENT"
        # No tmp residue.
        leftover = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftover == [], f"tmp residue: {leftover}"

    def test_fsync_unsupported_errno_is_tolerated(self, tmp_path: Path) -> None:
        """fsync raising EINVAL (e.g. on a pipe/socket pseudo-handle)
        must still let the write succeed — we just lose the durability
        guarantee on that particular fd.

        Mirrors the real-world case of running tests against /dev/null
        or a tempfs that legitimately doesn't implement fsync. The
        ``os.replace`` should still fire and the file should be visible.
        """
        import errno as _errno

        target = tmp_path / "out.bin"
        with _umock.patch(
            "veilbreakers_terrain.handlers.terrain_io.os.fsync",
            side_effect=OSError(_errno.EINVAL, "fsync not supported"),
        ):
            atomic_write_bytes(target, b"PAYLOAD")

        # File written despite the (tolerated) fsync failure.
        assert target.read_bytes() == b"PAYLOAD"
        leftover = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftover == []

    def test_fsync_attribute_error_is_tolerated(self, tmp_path: Path) -> None:
        """Mocked file objects whose ``fileno()`` raises ``AttributeError``
        (e.g. when the test patches ``os.fsync`` to assume an
        unconventional argument) must still let the write succeed.
        """
        target = tmp_path / "out.bin"
        with _umock.patch(
            "veilbreakers_terrain.handlers.terrain_io.os.fsync",
            side_effect=AttributeError("no fileno"),
        ):
            atomic_write_bytes(target, b"PAYLOAD")
        assert target.read_bytes() == b"PAYLOAD"


class TestAtomicWriteTextContract:
    """``atomic_write_text`` encodes utf-8 by default and round-trips."""

    def test_writes_utf8_text(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        atomic_write_text(target, "hello ☃ world")
        assert target.read_text(encoding="utf-8") == "hello ☃ world"

    def test_preserves_lf_newlines_by_default(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        atomic_write_text(target, "line1\nline2\nline3\n")
        # Python opens file in binary by atomic_write_bytes -> raw bytes
        # contain LF only (no CRLF translation).
        assert target.read_bytes() == b"line1\nline2\nline3\n"

    def test_rejects_non_str(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        with pytest.raises(TypeError, match="must be str"):
            atomic_write_text(target, b"bytes-not-str")  # type: ignore[arg-type]


class TestAtomicWriteJsonContract:
    """``atomic_write_json`` produces deterministic, sorted, indented output."""

    def test_writes_sorted_indented_json(self, tmp_path: Path) -> None:
        target = tmp_path / "manifest.json"
        atomic_write_json(target, {"b": 2, "a": 1, "c": [3, 1, 2]})
        text = target.read_text(encoding="utf-8")
        # Keys must be sorted alphabetically — required for content-hash
        # determinism across machines.
        assert text.index('"a"') < text.index('"b"') < text.index('"c"')
        # Indented (default indent=2).
        assert "\n  " in text
        # Round-trips.
        assert json.loads(text) == {"b": 2, "a": 1, "c": [3, 1, 2]}

    def test_replaces_existing_manifest_atomically(self, tmp_path: Path) -> None:
        target = tmp_path / "manifest.json"
        atomic_write_json(target, {"version": 1})
        atomic_write_json(target, {"version": 2, "files": {}})
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded == {"version": 2, "files": {}}


# ---------------------------------------------------------------------------
# Caller migration — verify the 4 manifest emitters now use atomic helpers
# ---------------------------------------------------------------------------


class TestCallerMigration:
    """Pin that every manifest emitter routes through the shared helpers."""

    def test_unity_export_contracts_uses_atomic_helper(self, tmp_path: Path) -> None:
        """``write_export_manifest`` must produce a complete manifest.json."""
        from veilbreakers_terrain.handlers.terrain_unity_export_contracts import (
            write_export_manifest,
        )

        files = {
            "heightmap.raw": {
                "bit_depth": 16,
                "channels": 1,
                "encoding": "raw_u16_le",
                "size": 1024,
            }
        }
        manifest_path = write_export_manifest(tmp_path, files)
        assert manifest_path.exists()
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert loaded["files"] == files
        # No tmp residue.
        leftover = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftover == [], f"tmp residue: {leftover}"

    def test_unity_export_contracts_atomic_under_simulated_crash(
        self, tmp_path: Path
    ) -> None:
        """Simulated crash mid-write must leave the prior manifest intact."""
        from veilbreakers_terrain.handlers.terrain_unity_export_contracts import (
            write_export_manifest,
        )

        # Prior good manifest.
        good_files = {
            "heightmap.raw": {
                "bit_depth": 16,
                "channels": 1,
                "encoding": "raw_u16_le",
            }
        }
        write_export_manifest(tmp_path, good_files)
        prior_text = (tmp_path / "manifest.json").read_text(encoding="utf-8")

        # Patch os.replace inside terrain_io to simulate crash on the second
        # call.
        from veilbreakers_terrain.handlers import terrain_io as _io_mod

        new_files = {
            "heightmap.raw": {
                "bit_depth": 32,
                "channels": 4,
                "encoding": "raw_f32_le",
            }
        }
        with _umock.patch.object(
            _io_mod.os, "replace", side_effect=OSError("simulated rename failure")
        ):
            with pytest.raises(OSError, match="simulated rename"):
                write_export_manifest(tmp_path, new_files)

        # Prior content still on disk.
        assert (tmp_path / "manifest.json").read_text(encoding="utf-8") == prior_text
        # No tmp residue.
        leftover = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftover == [], f"tmp residue: {leftover}"

    def test_unity_export_contracts_imports_atomic_helper(self) -> None:
        """Source-level pin: the migrated module imports the helper.

        Defends against accidental rollback to ``write_text(json.dumps(...))``.
        """
        import inspect

        from veilbreakers_terrain.handlers import terrain_unity_export_contracts

        src = inspect.getsource(terrain_unity_export_contracts)
        assert "from .terrain_io import atomic_write_json" in src, (
            "terrain_unity_export_contracts must import atomic_write_json "
            "(FIX-D24-PR12 regression)"
        )
        assert "atomic_write_json(manifest_path" in src, (
            "terrain_unity_export_contracts.write_export_manifest must "
            "delegate to atomic_write_json"
        )

    def test_navmesh_export_imports_atomic_helper(self) -> None:
        """``terrain_navmesh_export`` must route descriptor JSON through atomic_write_text."""
        import inspect

        from veilbreakers_terrain.handlers import terrain_navmesh_export

        src = inspect.getsource(terrain_navmesh_export)
        assert "from .terrain_io import atomic_write_text" in src, (
            "terrain_navmesh_export must import atomic_write_text "
            "(FIX-D24-PR12 regression)"
        )
        assert "atomic_write_text(" in src, (
            "terrain_navmesh_export must call atomic_write_text for descriptor"
        )

    def test_golden_snapshots_imports_atomic_helper(self) -> None:
        """``terrain_golden_snapshots`` must route both writes atomically."""
        import inspect

        from veilbreakers_terrain.handlers import terrain_golden_snapshots

        src = inspect.getsource(terrain_golden_snapshots)
        assert "from .terrain_io import atomic_write_text" in src, (
            "terrain_golden_snapshots must import atomic_write_text "
            "(FIX-D24-PR12 regression)"
        )
        # Both manifest writers (single snapshot + library manifest).
        atomic_count = src.count("atomic_write_text(")
        assert atomic_count >= 2, (
            f"terrain_golden_snapshots must use atomic_write_text in BOTH "
            f"save_golden_snapshot AND seed_golden_library; found "
            f"{atomic_count} call(s)"
        )

    def test_unity_export_imports_atomic_helper(self) -> None:
        """``terrain_unity_export`` routes manifest + descriptor + sidecar JSON."""
        import inspect

        from veilbreakers_terrain.handlers import terrain_unity_export

        src = inspect.getsource(terrain_unity_export)
        assert "from .terrain_io import atomic_write_bytes, atomic_write_text" in src, (
            "terrain_unity_export must import both atomic helpers "
            "(FIX-D24-PR12 regression)"
        )
        # The manifest+descriptor pair plus the _write_json sidecar should
        # all use atomic helpers.
        assert "atomic_write_bytes(_manifest_path" in src
        assert "atomic_write_bytes(_descriptor_path" in src
        # _write_json now uses atomic_write_text:
        assert "atomic_write_text(target," in src
