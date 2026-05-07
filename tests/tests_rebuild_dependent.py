'''Запуск:
    pytest tests/tests_rebuild_dependent.py -v
'''

import json
import subprocess
import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def write_spec_file(path: Path, name: str, build_requires: list[str]):
    lines = [
        f"Name: {name}",
        "Version: 1.0",
        "Release: 1",
        f"Summary: Test package {name}",
        "License: GPL",
    ]
    for br in build_requires:
        lines.append(f"BuildRequires: {br}")
    lines.extend([
        "",
        "%description",
        "Test package.",
        "",
        "%prep",
        "%build",
        "%install",
        "%files",
    ])
    path.write_text("\n".join(lines))

def run_planner(specs_dir: Path, available: list[str], requested: list[str], rebuild_dependents: bool = False) -> dict:
    available_file = specs_dir.parent / "available.txt"
    required_file = specs_dir.parent / "required.txt"
    available_file.write_text("\n".join(available) + "\n")
    required_file.write_text("\n".join(requested) + "\n")

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "main.py"),
        str(specs_dir),
        str(available_file),
        str(required_file),
    ]
    if rebuild_dependents:
        cmd.insert(2, "--rebuild-dependents")

    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "invalid_json", "stderr": result.stderr}

def test_rebuild_dependents_off(tmp_path):
    # без флага --rebuild-dependents собираются только B и C
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    write_spec_file(specs_dir / "a.spec", "a", ["b"])
    write_spec_file(specs_dir / "b.spec", "b", ["c"])
    write_spec_file(specs_dir / "c.spec", "c", [])

    output = run_planner(specs_dir, available=[], requested=["b"], rebuild_dependents=False)
    assert "error" not in output, f"Got error: {output}"
    stages = output["plan"]["stages"]
    all_pkgs = {p for s in stages for p in s["packages"]}
    assert "b" in all_pkgs
    assert "c" in all_pkgs
    assert "a" not in all_pkgs

def test_rebuild_dependents_on(tmp_path):
    # С флагом --rebuild-dependents собираются A, B и C
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    write_spec_file(specs_dir / "a.spec", "a", ["b"])
    write_spec_file(specs_dir / "b.spec", "b", ["c"])
    write_spec_file(specs_dir / "c.spec", "c", [])

    output = run_planner(specs_dir, available=[], requested=["b"], rebuild_dependents=True)
    assert "error" not in output, f"Got error: {output}"
    stages = output["plan"]["stages"]
    all_pkgs = {p for s in stages for p in s["packages"]}
    assert "a" in all_pkgs
    assert "b" in all_pkgs
    assert "c" in all_pkgs

def test_rebuild_dependents_with_available_packages(tmp_path):
    # Если зависящий пакет уже есть в available_repo, он всё равно пересобирается при rebuild_dependents (так как зависит от обновляемого B).
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    write_spec_file(specs_dir / "a.spec", "a", ["b"])
    write_spec_file(specs_dir / "b.spec", "b", ["c"])
    write_spec_file(specs_dir / "c.spec", "c", [])

    available = ["a"]
    output = run_planner(specs_dir, available=available, requested=["b"], rebuild_dependents=True)
    assert "error" not in output, f"Got error: {output}"
    stages = output["plan"]["stages"]
    all_pkgs = {p for s in stages for p in s["packages"]}
    assert "a" in all_pkgs
    assert "b" in all_pkgs
    assert "c" in all_pkgs

def test_rebuild_dependents_transitive(tmp_path):
    # Более длинная цепочка A -> B -> C -> D, запрошена сборка C. Без флага: C и D. С флагом: A, B, C, D
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    write_spec_file(specs_dir / "a.spec", "a", ["b"])
    write_spec_file(specs_dir / "b.spec", "b", ["c"])
    write_spec_file(specs_dir / "c.spec", "c", ["d"])
    write_spec_file(specs_dir / "d.spec", "d", [])

    output_no = run_planner(specs_dir, available=[], requested=["c"], rebuild_dependents=False)
    assert "error" not in output_no
    pkgs_no = {p for s in output_no["plan"]["stages"] for p in s["packages"]}
    assert pkgs_no == {"c", "d"}

    output_yes = run_planner(specs_dir, available=[], requested=["c"], rebuild_dependents=True)
    assert "error" not in output_yes
    pkgs_yes = {p for s in output_yes["plan"]["stages"] for p in s["packages"]}
    assert pkgs_yes == {"a", "b", "c", "d"}

def test_rebuild_dependents_with_cycle(tmp_path):
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    write_spec_file(specs_dir / "a.spec", "a", ["b"])
    write_spec_file(specs_dir / "b.spec", "b", ["a"])

    output_no = run_planner(specs_dir, available=["a"], requested=["b"], rebuild_dependents=False)
    assert "error" not in output_no
    pkgs_no = {p for s in output_no["plan"]["stages"] for p in s["packages"]}
    assert pkgs_no == {"b"}

    output_yes = run_planner(specs_dir, available=["a"], requested=["b"], rebuild_dependents=True)
    assert "error" not in output_no
    pkgs_yes = {p for s in output_yes["plan"]["stages"] for p in s["packages"]}
    assert pkgs_yes == {"a", "b"}