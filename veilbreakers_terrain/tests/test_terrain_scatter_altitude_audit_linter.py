from __future__ import annotations

from pathlib import Path

from veilbreakers_terrain.handlers.terrain_scatter_altitude_audit_linter import (
    _cli_main,
    audit_scatter_altitude_conversion,
)


def test_environment_scatter_is_clean_of_forbidden_altitude_normalization():
    source = Path("veilbreakers_terrain/handlers/environment_scatter.py").read_text(
        encoding="utf-8"
    )
    assert audit_scatter_altitude_conversion(source) == []


def test_cli_main_passes_clean_source(tmp_path, capsys):
    source = tmp_path / "clean_scatter.py"
    source.write_text("height_world = transform.from_normalized(value)\n", encoding="utf-8")

    assert _cli_main([str(source)]) == 0

    captured = capsys.readouterr()
    assert "OK: no forbidden altitude idioms" in captured.out
    assert captured.err == ""


def test_cli_main_fails_for_forbidden_altitude_pattern(tmp_path, capsys):
    source = tmp_path / "bad_scatter.py"
    source.write_text("sample = altitude / height_scale\n", encoding="utf-8")

    assert _cli_main([str(source)]) == 1

    captured = capsys.readouterr()
    assert "altitude_div_height_scale" in captured.out
    assert "FAIL: 1 violation" in captured.err


def test_cli_main_fails_for_missing_file(tmp_path, capsys):
    missing = tmp_path / "missing.py"

    assert _cli_main([str(missing)]) == 1

    captured = capsys.readouterr()
    assert "MISSING FILE" in captured.err
