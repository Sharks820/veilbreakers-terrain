"""Bundle D supplement — preset locking + autosave + retention.

Extends ``terrain_checkpoints`` (Bundle D) without mutating it. Adds:
  * preset lock registry + ``PresetLocked`` exception
  * content-hashed checkpoint filename generator
  * periodic ``save_every_n_operations`` monkey-patch helper
  * retention policy enforcer keyed off ``TerrainQualityProfile``

Per Addendum 1.B.4. No bpy imports.
"""

from __future__ import annotations

import logging
import re
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Set, Tuple

_log = logging.getLogger(__name__)

from .terrain_quality_profiles import TerrainQualityProfile  # noqa: E402


# ---------------------------------------------------------------------------
# Preset locks
# ---------------------------------------------------------------------------


class PresetLocked(RuntimeError):
    """Raised when attempting to mutate a locked preset."""


_PRESET_LOCKS: Set[str] = set()


def lock_preset(name: str) -> None:
    """Prevent mutations to preset ``name`` until explicitly unlocked."""
    _PRESET_LOCKS.add(name)


def unlock_preset(name: str) -> None:
    """Remove the lock on preset ``name`` (no-op if not locked)."""
    _PRESET_LOCKS.discard(name)


def is_preset_locked(name: str) -> bool:
    return name in _PRESET_LOCKS


def assert_preset_unlocked(name: str) -> None:
    """Raise ``PresetLocked`` if the preset is locked."""
    if is_preset_locked(name):
        raise PresetLocked(f"preset {name!r} is locked")


# ---------------------------------------------------------------------------
# Autosave monkey-patch
# ---------------------------------------------------------------------------


def save_every_n_operations(
    controller: Any,
    n: int,
) -> Callable[[], int]:
    """Wrap ``controller.run_pass`` so every Nth call triggers a checkpoint.

    Checkpoints are written atomically: the mask stack is serialized to a
    ``.npz.tmp`` file first, then renamed to ``.npz``.  This matches Houdini
    PDG's atomic-write contract — a crash mid-write never corrupts the last
    good checkpoint.

    The controller must expose ``run_pass`` and either:
      * ``_save_checkpoint(pass_name, result)`` — called with the pass result,
        or
      * ``checkpoint_dir`` + a mask stack accessible as
        ``controller.state.mask_stack`` — used for direct atomic npz write
        when ``_save_checkpoint`` is not available.

    Returns an "unpatch" callable that restores the original ``run_pass`` and,
    when called, returns the total operation count accumulated since patching.
    """
    if n <= 0:
        raise ValueError(f"n must be >= 1, got {n}")

    original = getattr(controller, "run_pass", None)
    if not callable(original):
        raise AttributeError(
            "controller has no callable run_pass; cannot auto-save"
        )

    counter: Dict[str, int] = {"i": 0}

    def _atomic_npz_save(pass_name: str) -> None:
        """Direct atomic npz write with SHA-256 integrity verification.

        Write sequence (matches Houdini PDG atomic-write contract):
          1. Write npz to ``<fname>.tmp``
          2. Compute SHA-256 of the tmp file
          3. Rename tmp → final (atomic on POSIX; atomic-replace on Windows Vista+)
          4. Write SHA-256 sidecar ``<fname>.npz.sha256`` for later verification
          5. Re-read the final file and verify its digest matches the pre-rename
             digest — catches filesystem-level corruption or rename aliasing.

        On any failure the tmp file is cleaned up and a WARNING is logged;
        the pipeline is never aborted by autosave I/O errors.
        """
        import hashlib as _hashlib

        cp_dir = getattr(controller, "checkpoint_dir", None)
        state = getattr(controller, "state", None)
        stack = getattr(state, "mask_stack", None) if state else None
        if cp_dir is None or stack is None:
            _log.warning(
                "save_every_n_operations: no checkpoint_dir/mask_stack on "
                "controller; skipping atomic write for pass %r",
                pass_name,
            )
            return
        cp_dir = Path(cp_dir)
        cp_dir.mkdir(parents=True, exist_ok=True)
        safe = _sanitize(pass_name)
        fname = f"autosave_{counter['i']:06d}_{safe}.npz"
        tmp_path = cp_dir / (fname + ".tmp")
        final_path = cp_dir / fname
        sidecar_path = final_path.with_suffix(".npz.sha256")
        try:
            stack.to_npz(tmp_path)

            # Hash the tmp file before rename
            pre_hash = _hashlib.sha256()
            with open(tmp_path, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    pre_hash.update(chunk)
            pre_digest = pre_hash.hexdigest()

            # Atomic rename
            try:
                tmp_path.rename(final_path)
            except OSError:
                import shutil as _shutil
                _shutil.copy2(str(tmp_path), str(final_path))
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

            # Post-rename integrity verification
            post_hash = _hashlib.sha256()
            with open(final_path, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    post_hash.update(chunk)
            post_digest = post_hash.hexdigest()
            if post_digest != pre_digest:
                _log.warning(
                    "save_every_n_operations: post-rename integrity check FAILED "
                    "for %r (pre=%s, post=%s) — file may be corrupted.",
                    fname, pre_digest[:16], post_digest[:16],
                )
            else:
                # Write sidecar only when digest is confirmed good
                try:
                    sidecar_path.write_text(
                        f"{post_digest}  {final_path.name}\n", encoding="utf-8"
                    )
                except OSError as sidecar_exc:
                    _log.warning(
                        "save_every_n_operations: could not write sidecar for %r: %s",
                        fname, sidecar_exc,
                    )
                _log.debug(
                    "save_every_n_operations: atomic checkpoint written → %s (sha256=%s…)",
                    final_path, post_digest[:16],
                )
        except Exception as exc:
            _log.warning(
                "save_every_n_operations: atomic write failed for %r: %r",
                pass_name,
                exc,
            )
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        counter["i"] += 1
        if counter["i"] % n == 0:
            pass_name = getattr(result, "pass_name", "autosave")
            save_fn = getattr(controller, "_save_checkpoint", None)
            if callable(save_fn):
                try:
                    save_fn(pass_name, result)
                except TypeError:
                    # Older signature: _save_checkpoint(pass_name)
                    try:
                        save_fn(pass_name)
                    except Exception as exc:
                        _log.warning(
                            "save_every_n_operations: checkpoint save failed: %r", exc
                        )
                except Exception as exc:
                    _log.warning(
                        "save_every_n_operations: checkpoint save failed: %r", exc
                    )
            else:
                _atomic_npz_save(pass_name)
        return result

    controller.run_pass = wrapped  # type: ignore[assignment]

    def unpatch() -> int:
        controller.run_pass = original  # type: ignore[assignment]
        return counter["i"]

    return unpatch


# ---------------------------------------------------------------------------
# Checkpoint filename generator
# ---------------------------------------------------------------------------


_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_\-]+")


def _sanitize(name: str) -> str:
    return _SAFE_NAME_RE.sub("_", name).strip("_") or "pass"


def generate_checkpoint_filename(
    pass_num: int,
    pass_name: str,
    content_hash: str,
) -> str:
    """Return ``terrain_{pass_num:02d}_{pass_name}_{content_hash[:8]}.blend``.

    ``content_hash`` may be a longer hash; only the first 8 hex characters
    are embedded. ``pass_name`` is sanitized to ``[a-zA-Z0-9_-]``.
    """
    if pass_num < 0:
        raise ValueError(f"pass_num must be >= 0, got {pass_num}")
    safe = _sanitize(pass_name)
    short = (content_hash or "").strip()[:8] or "00000000"
    return f"terrain_{pass_num:02d}_{safe}_{short}.blend"


# ---------------------------------------------------------------------------
# Retention policy
# ---------------------------------------------------------------------------


def _day_key(mtime: float) -> Tuple[int, int, int]:
    """Return (year, month, day) UTC tuple for an mtime timestamp."""
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return (dt.year, dt.month, dt.day)


def _week_key(mtime: float) -> Tuple[int, int]:
    """Return (ISO year, ISO week) UTC tuple for an mtime timestamp."""
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    iso = dt.isocalendar()
    return (iso[0], iso[1])


def enforce_retention_policy(
    checkpoint_dir: Path,
    profile: TerrainQualityProfile,
) -> List[Path]:
    """Apply a three-tier retention policy matching Houdini PDG checkpoint cadence.

    Tiers (evaluated in order; a file kept by an earlier tier is never deleted):
      1. **Recent N**: always keep the ``profile.checkpoint_retention`` most-recent
         files regardless of age.
      2. **Daily (past 7 days)**: keep the newest file per calendar day for the
         7 days prior to "now".  This gives one-per-day recovery anchors across
         the last week.
      3. **Weekly (past 4 weeks)**: keep the newest file per ISO week for the
         4 weeks prior to "now".  This gives one-per-week anchors for the
         broader recent history.

    All files not pinned by any tier are deleted.  Only ``terrain_*.blend``
    and ``terrain_*.npz`` files in the given directory are considered (autosave
    npz files from ``save_every_n_operations`` are included).  Returns the list
    of paths deleted.  Non-fatal if the directory does not exist.
    """
    checkpoint_dir = Path(checkpoint_dir)
    if not checkpoint_dir.exists():
        return []

    def _is_checkpoint(p: Path) -> bool:
        return (
            p.is_file()
            and p.name.startswith("terrain_")
            and p.suffix in (".blend", ".npz")
        )

    files = [p for p in checkpoint_dir.iterdir() if _is_checkpoint(p)]
    if not files:
        return []

    # Attach mtime once to avoid repeated stat calls
    stamped: List[Tuple[float, Path]] = []
    for p in files:
        try:
            stamped.append((p.stat().st_mtime, p))
        except OSError:
            continue

    stamped.sort(key=lambda t: t[0])  # oldest first

    keep_n = max(int(profile.checkpoint_retention), 0)
    now = _time.time()
    seven_days_ago = now - 7 * 86400
    four_weeks_ago = now - 28 * 86400

    pinned: Set[Path] = set()

    # Tier 1 — keep the most-recent N
    for _, p in stamped[-keep_n:]:
        pinned.add(p)

    # Tier 2 — one file per day for the past 7 days
    seen_days: Set[Tuple[int, int, int]] = set()
    for mtime, p in reversed(stamped):  # newest first
        if mtime < seven_days_ago:
            break
        dk = _day_key(mtime)
        if dk not in seen_days:
            seen_days.add(dk)
            pinned.add(p)

    # Tier 3 — one file per week for the past 4 weeks
    seen_weeks: Set[Tuple[int, int]] = set()
    for mtime, p in reversed(stamped):
        if mtime < four_weeks_ago:
            break
        wk = _week_key(mtime)
        if wk not in seen_weeks:
            seen_weeks.add(wk)
            pinned.add(p)

    deleted: List[Path] = []
    for _, p in stamped:
        if p in pinned:
            continue
        try:
            p.unlink()
            deleted.append(p)
            _log.debug("enforce_retention_policy: deleted %s", p.name)
        except OSError:
            continue

    if deleted:
        _log.info(
            "enforce_retention_policy: deleted %d/%d checkpoints "
            "(kept %d recent + daily + weekly anchors)",
            len(deleted),
            len(stamped),
            len(pinned),
        )
    return deleted


__all__ = [
    "PresetLocked",
    "lock_preset",
    "unlock_preset",
    "is_preset_locked",
    "assert_preset_unlocked",
    "save_every_n_operations",
    "generate_checkpoint_filename",
    "enforce_retention_policy",
]
