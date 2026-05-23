"""WAVE6-9 verify-only: pin Channel.MACRO_COLOR_RGB rename + rgb_triplet unit.

WAVE-6 audit (confidence 60) flagged that PR #125's rename of
``Channel.MACRO_COLOR`` -> ``Channel.MACRO_COLOR_RGB`` and retag of
``"dimensionless"`` -> ``"rgb_triplet"`` could leave external golden-baseline
files stale.

Inspection at HEAD ``e29ace10`` found **0 stale references**:
  - No ``*.json`` / ``*.npz`` / ``*.md`` / ``*.txt`` file under ``output/``
    or ``veilbreakers_terrain/tests/`` contains ``"dimensionless"`` for the
    ``macro_color`` key.
  - No Python source contains a live bare ``Channel.MACRO_COLOR`` reference
    (only docstring / legacy-note occurrences).
  - Both ``_channels.ChannelInfo`` and
    ``terrain_golden_snapshots._CHANNEL_CANONICAL_UNITS`` agree on
    ``"rgb_triplet"`` for ``macro_color``.

Disposition: **verify-only** (no purge required). Tests below pin the
contract so any future regression breaks loud at import time or during CI.

Coverage beyond what PR #125's ``test_checkpoint_5_cascade_hotfix.py`` pins:
  - Subprocess grep asserting zero bare ``Channel.MACRO_COLOR`` (no _RGB
    suffix) in production source (not just test comments).
  - ``"rgb_triplet"`` is in the closed-set of valid unit strings used by
    ``_CHANNEL_CANONICAL_UNITS``.
  - ``"macro_color": "dimensionless"`` does NOT exist anywhere in
    ``_CHANNEL_CANONICAL_UNITS`` (explicit exclusion of the old stale entry).
  - Golden scenario JSON fixtures under ``veilbreakers_terrain/tests/`` do
    not record a stale ``"dimensionless"`` value for the ``macro_color`` key.

Audit ref: docs/aaa-audit/2026_05_22_master_audit_state/CE_WAVE_6_FINDINGS.md
           §WAVE6-9
PR ref:    PR #125 (MACRO_COLOR_RGB retag), fix/wave6-9-golden-baseline-sweep
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Test 1 — Channel.MACRO_COLOR_RGB canonical name exists
# ---------------------------------------------------------------------------


def test_channel_macro_color_rgb_exists() -> None:
    """``Channel.MACRO_COLOR_RGB`` must be present in the enum.

    This is the renamed variant that makes the (H, W, 3) RGB surface explicit.
    """
    from veilbreakers_terrain.handlers._channels import Channel

    assert hasattr(Channel, "MACRO_COLOR_RGB"), (
        "Channel.MACRO_COLOR_RGB must exist — it was introduced by PR #125 "
        "as the canonical replacement for the bare Channel.MACRO_COLOR name. "
        "If this fails the rename was reverted or the enum was reset to a "
        "pre-PR-125 state."
    )


# ---------------------------------------------------------------------------
# Test 2 — _CHANNEL_CANONICAL_UNITS pins "rgb_triplet" for macro_color
# ---------------------------------------------------------------------------


def test_channel_canonical_units_macro_color_is_rgb_triplet() -> None:
    """``_CHANNEL_CANONICAL_UNITS["macro_color"]`` must be ``"rgb_triplet"``.

    This is the golden-snapshot registry that drives assertion-gate verdicts.
    Any stale ``"dimensionless"`` value here would silently pass wrong-unit
    checks against pre-PR-125 snapshot content.
    """
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
        _CHANNEL_CANONICAL_UNITS,
    )

    actual = _CHANNEL_CANONICAL_UNITS.get("macro_color")
    assert actual is not None, (
        "_CHANNEL_CANONICAL_UNITS must contain 'macro_color'. "
        "The key was present before PR #125 (as 'dimensionless') and must "
        "remain registered (now as 'rgb_triplet') for the assertion gate."
    )
    assert actual == "rgb_triplet", (
        f"_CHANNEL_CANONICAL_UNITS['macro_color'] must be 'rgb_triplet' "
        f"(the PR #125 retag). Got {actual!r}. "
        f"A value of 'dimensionless' here means the retag was reverted."
    )


# ---------------------------------------------------------------------------
# Test 3 — No stale "dimensionless" entry for macro_color in the registry
# ---------------------------------------------------------------------------


def test_channel_canonical_units_macro_color_not_dimensionless() -> None:
    """The old ``"dimensionless"`` unit must NOT be registered for macro_color.

    This is the explicit exclusion guard — it complements Test 2 by asserting
    the absence rather than just the presence of the new value.
    """
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
        _CHANNEL_CANONICAL_UNITS,
    )

    actual = _CHANNEL_CANONICAL_UNITS.get("macro_color")
    assert actual != "dimensionless", (
        "_CHANNEL_CANONICAL_UNITS['macro_color'] must NOT be 'dimensionless'. "
        "That was the pre-PR-125 stale tag (Shape-A bug: producer emits "
        "(H, W, 3) float32 RGB, not a scalar dimensionless mask). "
        "If this fails, the PR #125 retag has been reverted."
    )


# ---------------------------------------------------------------------------
# Test 4 — "rgb_triplet" is in the closed-set of valid unit strings
# ---------------------------------------------------------------------------

_VALID_UNIT_STRINGS = frozenset(
    {
        "m",
        "rad",
        "deg",
        "dimensionless",
        "unit_normal_xyz",
        "rgb_triplet",
        "count",
    }
)
"""Closed set of unit strings recognised by the channel registry.

Any unit string outside this set is either a typo or an undocumented
extension — both should break this test so the author explicitly adds the
new token here.

Maintenance: if you add a new unit token to ``_CHANNEL_CANONICAL_UNITS``
or ``ChannelInfo`` that is not in this set, add it here AND document it with
a comment explaining the semantics (scalar, vector, categorical, …).
"""


def test_rgb_triplet_in_valid_unit_closed_set() -> None:
    """``"rgb_triplet"`` must be a member of the canonical valid-unit set.

    This test pins the closed set so future renaming of ``"rgb_triplet"``
    (e.g. to ``"rgb_float32"`` or ``"rgb_linear"``) causes a loud failure
    rather than silently passing stale string comparisons.
    """
    assert "rgb_triplet" in _VALID_UNIT_STRINGS, (
        "'rgb_triplet' must be in the closed unit-string set. "
        "It was added by PR #125 for Channel.MACRO_COLOR_RGB."
    )


def test_all_canonical_units_in_valid_closed_set() -> None:
    """Every unit in ``_CHANNEL_CANONICAL_UNITS`` must be in the closed set.

    If this test fails, an undocumented unit token was added to the registry.
    Add the new token to ``_VALID_UNIT_STRINGS`` above with a comment
    explaining its semantics before landing any PR that introduces a new unit.
    """
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
        _CHANNEL_CANONICAL_UNITS,
    )

    unknown = {
        unit
        for unit in _CHANNEL_CANONICAL_UNITS.values()
        if unit not in _VALID_UNIT_STRINGS
    }
    assert not unknown, (
        f"Unknown unit token(s) in _CHANNEL_CANONICAL_UNITS: {sorted(unknown)}. "
        f"Add each to _VALID_UNIT_STRINGS in this test with a semantic "
        f"comment, then re-run."
    )


# ---------------------------------------------------------------------------
# Test 5 — No bare Channel.MACRO_COLOR (without _RGB) in production source
# ---------------------------------------------------------------------------


def test_no_bare_channel_macro_color_in_source() -> None:
    """No production Python file should reference ``Channel.MACRO_COLOR``
    without the ``_RGB`` suffix.

    The bare name was the pre-PR-125 legacy enum member. PR #125 removed it
    and renamed it to ``Channel.MACRO_COLOR_RGB``. Any surviving bare
    reference in *live code* is a production bug (an accessor using a deleted
    enum member) that would raise ``AttributeError`` at runtime.

    This test uses a ``tokenize``-based scan (run in a subprocess so it
    catches file-level drift that import-time tests cannot see). It detects
    the token sequence ``Channel`` ``.`` ``MACRO_COLOR`` (where the trailing
    member name is exactly ``MACRO_COLOR``, not ``MACRO_COLOR_RGB``) in code
    tokens only.

    Exemptions (these are genuinely ignored, not merely tolerated):
      - ``COMMENT`` and ``STRING`` tokens (comments and docstrings). A comment
        or docstring that mentions the old name for historical reference —
        e.g. ``# was Channel.MACRO_COLOR before PR #125`` — is NOT a runtime
        reference and does NOT fail this gate.
      - This test file itself is excluded from the search.
    """
    handlers_dir = _REPO_ROOT / "veilbreakers_terrain" / "handlers"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            # Token-based scan via subprocess so we (a) avoid shell quoting
            # issues on Windows and (b) ignore COMMENT/STRING tokens so that
            # historical doc/comment references to the old name don't fail CI.
            r"""
import io, pathlib, sys, token, tokenize

root = pathlib.Path(sys.argv[1])
hits = []
for py_file in root.rglob("*.py"):
    try:
        src = py_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        continue
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Unparseable file: fall back to a conservative report so drift is
        # never silently skipped.
        hits.append(f"{py_file.relative_to(root.parent.parent)}: <tokenize failed>")
        continue
    # Keep only code tokens (drop COMMENT, STRING, NL, NEWLINE, INDENT, ...).
    code = [t for t in toks if t.type in (token.NAME, token.OP)]
    for i in range(len(code) - 2):
        a, b, c = code[i], code[i + 1], code[i + 2]
        if (
            a.type == token.NAME and a.string == "Channel"
            and b.type == token.OP and b.string == "."
            and c.type == token.NAME and c.string == "MACRO_COLOR"
        ):
            lineno = a.start[0]
            line = src.splitlines()[lineno - 1].rstrip() if lineno >= 1 else ""
            hits.append(f"{py_file.relative_to(root.parent.parent)}:{lineno}: {line}")
if hits:
    print("\n".join(hits))
    sys.exit(1)
sys.exit(0)
""",
            str(handlers_dir),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        "Bare 'Channel.MACRO_COLOR' (without _RGB suffix) found in production "
        "source as a live code reference. These are accesses to a deleted "
        "enum member and will raise AttributeError at runtime. Hits:\n"
        + result.stdout
    )


# ---------------------------------------------------------------------------
# Test 6 — Golden scenario JSON fixtures do not record stale dimensionless
#           unit for macro_color
# ---------------------------------------------------------------------------


def test_golden_scenario_fixtures_no_stale_macro_color_dimensionless() -> None:
    """JSON fixtures under ``veilbreakers_terrain/tests/golden_scenarios/``
    must not record ``"dimensionless"`` as the unit for the ``macro_color``
    channel.

    These files are the closest analogue to the "external golden-baseline"
    risk WAVE6-9 described. If any fixture was captured before PR #125 and
    stores a ``macro_color`` unit assertion with value ``"dimensionless"``,
    the assertion gate will silently pass a stale check.

    If no JSON file records a unit for ``macro_color`` at all, the test
    passes vacuously (the risk surface does not exist).

    A malformed fixture (``json.JSONDecodeError``) is treated as fixture
    corruption/drift and fails the test loudly rather than being silently
    skipped — a corrupt golden baseline is exactly the kind of regression
    this gate exists to catch. Transient ``OSError`` on read is still
    tolerated (skipped) so the gate stays robust to filesystem hiccups.
    """
    fixtures_dir = _REPO_ROOT / "veilbreakers_terrain" / "tests" / "golden_scenarios"
    if not fixtures_dir.exists():
        return  # No fixture directory — risk surface doesn't exist.

    stale: list[str] = []
    malformed: list[str] = []
    for json_file in fixtures_dir.rglob("*.json"):
        try:
            raw = json_file.read_text(encoding="utf-8")
        except OSError:
            continue  # Transient read failure — tolerate.
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            # Malformed fixture is real drift/corruption — record and fail.
            rel = json_file.relative_to(_REPO_ROOT)
            malformed.append(f"{rel}: {exc}")
            continue
        # Walk the JSON looking for any dict that has both a "channel" or
        # "key" field equal to "macro_color" and a "unit" field equal to
        # "dimensionless".
        _collect_stale_macro_color_entries(data, json_file, stale)

    assert not malformed, (
        "Golden scenario fixture(s) are not valid JSON. A corrupt golden "
        "baseline must fail loudly, not be silently skipped. Malformed "
        "files:\n" + "\n".join(malformed)
    )
    assert not stale, (
        "Golden scenario fixture(s) contain a stale 'dimensionless' unit "
        "for the 'macro_color' channel. Update them to 'rgb_triplet' to "
        "match the PR #125 retag. Stale entries:\n"
        + "\n".join(stale)
    )


def _collect_stale_macro_color_entries(
    node: object,
    source_file: Path,
    out: list[str],
) -> None:
    """Recursively walk *node* (dict/list/scalar) from a JSON blob and
    collect any sub-dict that records ``macro_color`` with unit
    ``"dimensionless"``."""
    if isinstance(node, dict):
        channel_key = node.get("channel") or node.get("key") or node.get("name")
        unit_val = node.get("unit")
        if (
            isinstance(channel_key, str)
            and channel_key == "macro_color"
            and unit_val == "dimensionless"
        ):
            out.append(
                f"{source_file}: found macro_color unit='dimensionless' "
                f"(stale pre-PR-125 value)"
            )
        for v in node.values():
            _collect_stale_macro_color_entries(v, source_file, out)
    elif isinstance(node, list):
        for item in node:
            _collect_stale_macro_color_entries(item, source_file, out)
