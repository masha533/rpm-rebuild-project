"""
Запуск:
    python3 main.py ./specs ./available.txt ./required.txt
"""

from pathlib import Path
import argparse
import json
import sys

from parser import parse_specs_dir, build_provides_index
from resolve import resolve
from planner import build_plan
from bootstrap_handler import apply_bootstrap


def read_package_list(path: Path) -> set[str]:
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")
    result = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            result.add(line)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("specs_dir", type=Path)
    parser.add_argument("available_repo", type=Path)
    parser.add_argument("requested", type=Path)
    args = parser.parse_args()

    specs = parse_specs_dir(args.specs_dir, ignore_errors=False)
    provides_index = build_provides_index(specs)

    available_repo = read_package_list(args.available_repo)
    requested_to_build = read_package_list(args.requested)

    for pkg in available_repo:
        if pkg not in provides_index:
            provides_index[pkg] = {pkg}

    unknown = requested_to_build - set(specs.keys())
    already_in_repo = unknown & available_repo
    truly_unknown = unknown - available_repo

    for pkg in sorted(already_in_repo):
        print(f"[warn] {pkg!r} запрошен к сборке, но уже есть в репозитории — пропускаем", file=sys.stderr)

    if truly_unknown:
        for pkg in sorted(truly_unknown):
            print(f"[error] Пакет {pkg!r} не найден ни в specs, ни в репозитории", file=sys.stderr)
        sys.exit(1)

    requested_to_build -= available_repo

    if not requested_to_build:
        print(json.dumps({"warnings": [], "plan": {
            "packages_graph": {}, "components": [], "stages": [],
            "bootstrap_algorithm": {"type": "none", "message": "Все пакеты уже доступны"}
        }}, indent=2, ensure_ascii=False))
        return

    resolved_deps, final_to_build, warnings, errors = resolve(
        specs=specs,
        provides_index=provides_index,
        available_repo=available_repo,
        requested_to_build=requested_to_build,
    )

    if errors:
        print("Ошибки разрешения зависимостей:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    plan = build_plan(final_to_build, resolved_deps)
    final_plan = apply_bootstrap(plan)

    output = {
        "warnings": warnings,
        "plan": final_plan,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()