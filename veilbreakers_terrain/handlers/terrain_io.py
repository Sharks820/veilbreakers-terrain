"""Shared atomic-write + finiteness-assertion utilities (Phase B D24).

Implements two narrow primitives shared across the export, manifest, and
pipeline layers so partial writes can never corrupt manifests and NaN/Inf
poisoning is caught at the boundary that produced it.

Two concerns, one module:
  - **Atomic writes** — write to ``<path>.<unique>.tmp`` adjacent to the
    final path, ``flush()`` + ``os.fsync()`` the file descriptor, then
    ``os.replace(tmp, path)``. ``os.replace`` is atomic on POSIX and on
    Windows (NTFS / ReFS) since Vista. The temp suffix is unique per
    invocation so concurrent writers don't collide on the temp name.
  - **Finiteness assertion** — ``assert_finite_array`` raises ``ValueError``
    with a specific channel + pass attribution when an array contains
    NaN or +/-Inf. Lifts the existing ad-hoc ``np.all(np.isfinite(...))``
    pattern into a single named helper so messages are uniform across
    callers.

Pure stdlib + numpy. No bpy. No third-party deps.

References:
  - IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL.md §17.2 D24 (PR #12 atomic
    manifest + descriptor write + PR #13 NaN/Inf assertions).
  - terrain_checkpoints.py::_atomic_npz_write (prior NPZ-only pattern).
  - terrain_unity_export.py::export_unity_manifest (prior in-place
    NamedTemporaryFile + os.replace; this module replaces that pattern with
    a reusable helper).
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Union

import numpy as np


__all__ = [
    "atomic_write_bytes",
    "atomic_write_text",
    "atomic_write_json",
    "assert_finite_array",
    "FiniteArrayError",
]


_PathLike = Union[str, "os.PathLike[str]", Path]


# ---------------------------------------------------------------------------
# Atomic write primitives
# ---------------------------------------------------------------------------


def atomic_write_bytes(path: _PathLike, data: bytes) -> Path:
    """Atomically write ``data`` to ``path``.

    Strategy
    --------
    1. Compute a unique temp path adjacent to ``path``: ``{path}.{uuid4}.tmp``.
       Same parent dir guarantees ``os.replace`` is a same-filesystem rename
       (atomic) and never falls back to copy semantics.
    2. Open the temp file, ``write(data)``, ``flush()``, ``os.fsync(fd)``.
       fsync is required because on Windows + Linux a crash between rename
       and journal flush can otherwise leave the new inode pointing at
       unflushed bytes.
    3. ``os.replace(tmp, path)`` — atomic on POSIX (rename(2)) and on
       Windows since Vista (MoveFileEx with MOVEFILE_REPLACE_EXISTING).
    4. On any failure, the temp file is removed before re-raising so we
       don't accumulate ``.tmp`` cruft.

    Parameters
    ----------
    path : path-like
        Destination path. Parent directory must already exist.
    data : bytes
        Payload to write.

    Returns
    -------
    Path
        The final destination path (echoed for chaining convenience).

    Raises
    ------
    OSError
        If the temp file cannot be created, written, or replaced.
    TypeError
        If ``data`` is not ``bytes``.
    """
    # Defensive runtime check: callers from untyped contexts (e.g. tests
    # that exercise the negative path, or JSON-serialised payloads passed
    # accidentally as str) must surface as a clear TypeError rather than
    # cryptic OSError downstream. Pyright considers this redundant given
    # the static type hint; the runtime guard is still load-bearing.
    if not isinstance(data, (bytes, bytearray, memoryview)):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(
            f"atomic_write_bytes: data must be bytes-like, got {type(data).__name__}"
        )

    final_path = Path(path)
    if not final_path.parent.exists():
        # Refuse to silently mkdir parent — callers should be explicit.
        raise FileNotFoundError(
            f"atomic_write_bytes: parent directory {final_path.parent!r} "
            "does not exist; create it before calling"
        )

    tmp_name = f"{final_path.name}.{uuid.uuid4().hex}.tmp"
    tmp_path = final_path.with_name(tmp_name)
    fd: int = -1
    try:
        # Use os.open so we can fsync the underlying fd reliably on all
        # platforms before closing. Mode 0o600 (owner read+write only)
        # avoids the CodeQL "overly permissive mask" finding — manifest
        # data may carry seed values, tile IDs, or path fragments we do
        # not want world-readable on a multi-user host.
        fd = os.open(
            str(tmp_path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            with os.fdopen(fd, "wb") as fh:
                # Once os.fdopen succeeds, the with-block now owns the fd
                # and will close it; mark our own copy as 'taken' so the
                # outer except doesn't try to close it again.
                fd = -1
                fh.write(bytes(data))
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except (AttributeError, OSError):
                    # Some exotic filesystems (mocked test fixtures, /dev/null)
                    # don't support fsync. Tolerate but don't pretend.
                    pass
        finally:
            # If fd is still owned by us (os.fdopen failed before taking
            # ownership) we must close it ourselves so the temp file can
            # be unlinked on Windows.
            if fd != -1:
                try:
                    os.close(fd)
                except OSError:
                    # fd may already be closed if the OS forced it during
                    # an earlier failure; closing again is safe to ignore.
                    pass

        os.replace(str(tmp_path), str(final_path))
    except Exception:
        # Best-effort cleanup so we don't leak .tmp files on failure paths
        # that escape the inner try.
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            # If we cannot unlink (file disappeared, permission denied),
            # propagate the original failure rather than masking it.
            pass
        raise
    return final_path


def atomic_write_text(
    path: _PathLike,
    text: str,
    *,
    encoding: str = "utf-8",
    newline: str = "\n",
) -> Path:
    """Atomically write ``text`` to ``path``.

    Convenience wrapper that encodes ``text`` and delegates to
    :func:`atomic_write_bytes`. Uses LF line endings by default to match
    the project's existing JSON/manifest convention.
    """
    # Defensive runtime check (see :func:`atomic_write_bytes`). Pyright
    # considers this redundant against the static type, but bytes payloads
    # silently encoded via str() would corrupt the manifest.
    if not isinstance(text, str):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(
            f"atomic_write_text: text must be str, got {type(text).__name__}"
        )
    if newline != "\n":
        # Normalise any embedded newlines so we honour the requested newline.
        text = text.replace("\r\n", "\n").replace("\n", newline)
    return atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(
    path: _PathLike,
    payload: Any,
    *,
    indent: int = 2,
    sort_keys: bool = True,
    default: Any = None,
) -> Path:
    """Atomically serialise ``payload`` as JSON and write it to ``path``.

    Defaults match the conventions used across the existing manifest
    writers (``terrain_unity_export.py``, ``terrain_unity_export_contracts.py``,
    ``terrain_navmesh_export.py``, ``terrain_golden_snapshots.py``):
    ``indent=2``, ``sort_keys=True``, UTF-8 encoded.

    Parameters
    ----------
    path : path-like
        Destination JSON file.
    payload : Any
        Object to serialise. Must be JSON-encodable (with help from
        ``default`` if numpy types are present).
    indent : int
        ``json.dumps`` indent level. Default 2.
    sort_keys : bool
        Whether to sort dict keys deterministically. Default True (for
        deterministic content hashes).
    default : callable, optional
        Optional ``json.dumps(default=...)`` callable for non-JSON types
        such as numpy scalars / arrays.
    """
    body = json.dumps(payload, indent=indent, sort_keys=sort_keys, default=default)
    return atomic_write_text(path, body)


# ---------------------------------------------------------------------------
# NaN / Inf assertion
# ---------------------------------------------------------------------------


class FiniteArrayError(ValueError):
    """Raised when ``assert_finite_array`` finds NaN/Inf in an array.

    Subclass of ``ValueError`` so existing exception handlers that catch
    ``ValueError`` continue to work, but callers can match this specific
    type when they need to attribute the corruption back to a pass.
    """

    def __init__(
        self,
        message: str,
        *,
        channel: str,
        pass_name: str,
        nan_count: int,
        posinf_count: int,
        neginf_count: int,
    ) -> None:
        super().__init__(message)
        self.channel = channel
        self.pass_name = pass_name
        self.nan_count = nan_count
        self.posinf_count = posinf_count
        self.neginf_count = neginf_count


def assert_finite_array(
    arr: Any,
    *,
    channel: str,
    pass_name: str,
) -> None:
    """Raise :class:`FiniteArrayError` if ``arr`` has any NaN or +/-Inf.

    Skips non-floating-point arrays silently — integer / boolean arrays
    cannot represent NaN/Inf so the check is a no-op there. ``None`` and
    non-array values are also skipped (callers that need to assert
    presence should do so explicitly first).

    No-op classes (intentional contract — Hardening PR B Fix #6, VC finding):
        * ``None`` (the channel is absent — caller must check separately).
        * ``np.integer`` / ``np.bool_`` arrays (cannot hold NaN/Inf — the
          IEEE-754 special values only exist in floating-point dtypes).
        * Object-dtype arrays containing Python ints / bools (same reason).

    Float arrays — the load-bearing case — are checked exhaustively via
    ``np.isfinite``.  ``np.float16`` / ``np.float32`` / ``np.float64`` /
    ``np.float128`` (where available) are all covered by the
    ``np.issubdtype(..., np.floating)`` check.

    The error message includes the channel name, the pass that produced
    it, and a breakdown of NaN / +Inf / -Inf counts so the corruption
    site is unambiguous.

    Parameters
    ----------
    arr : array-like
        The array to check. Typically a ``TerrainMaskStack`` channel.
    channel : str
        The channel name (e.g. ``"height"``, ``"erosion_amount"``).
    pass_name : str
        The pass that produced ``arr`` (e.g. ``"pass_erosion"``).
    """
    if arr is None:
        return
    np_arr = np.asarray(arr)
    # Only floating-point arrays can carry NaN/Inf; ints/bools are always finite.
    if not np.issubdtype(np_arr.dtype, np.floating):
        return
    # np.isfinite is True for every finite float, False for NaN / +Inf / -Inf.
    finite_mask = np.isfinite(np_arr)
    if finite_mask.all():
        return

    nonfinite = ~finite_mask
    nan_count = int(np.count_nonzero(np.isnan(np_arr) & nonfinite))
    posinf_count = int(np.count_nonzero(np.isposinf(np_arr) & nonfinite))
    neginf_count = int(np.count_nonzero(np.isneginf(np_arr) & nonfinite))

    message = (
        f"Channel {channel!r} produced by pass {pass_name!r} contains "
        f"{nan_count} NaN, {posinf_count} +Inf, {neginf_count} -Inf cells "
        f"(shape={tuple(int(d) for d in np_arr.shape)}, dtype={np_arr.dtype})."
    )
    raise FiniteArrayError(
        message,
        channel=channel,
        pass_name=pass_name,
        nan_count=nan_count,
        posinf_count=posinf_count,
        neginf_count=neginf_count,
    )
