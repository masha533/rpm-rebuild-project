"""
Запуск:
    python3 main.py ./specs ./available.txt ./required.txt --rebuild-dependents
    (по умолчанию rebuild-dependents = False)
"""

from pathlib import Path
import argparse
import json
import sys

from parser import parse_specs_dir, build_provides_index
from resolve import resolve
from planner import build_plan


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
    parser.add_argument(
        "--rebuild-dependents",
        action="store_true",
        help="пересобрать пакеты, которые зависят от запрошенных"
    )
    args = parser.parse_args()

    specs = parse_specs_dir(args.specs_dir, ignore_errors=False)
    provides_index = build_provides_index(specs)

    available_repo = read_package_list(args.available_repo)
    requested_to_build = read_package_list(args.requested)

    for pkg in available_repo:
        if pkg not in provides_index:
            provides_index[pkg] = {pkg}

    unknown = requested_to_build - set(specs.keys())
    if unknown:
        for pkg in sorted(unknown):
            if pkg in available_repo:
                print(
                    f"[error] Нельзя пересобрать пакет {pkg!r}: "
                    f"он есть в репозитории, но для него не найден spec-файл.",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[error] Пакет {pkg!r} запрошен к сборке, "
                    f"но не найден ни среди spec-файлов, ни в репозитории.",
                    file=sys.stderr,
                )
        sys.exit(1)

    for pkg in sorted(requested_to_build & available_repo):
         print(
            f"[info] Пакет {pkg!r} уже есть в репозитории, "
            f"но он указан в списке запрошенных пакетов, поэтому будет пересобран.",
            file=sys.stderr,
        )

    if not requested_to_build:
        print(json.dumps({
            "warnings": [],
            "plan": {
                "packages_graph": {},
                "repo_requires": {},
                "components": [],
                "stages": [],
            }
        }, indent=2, ensure_ascii=False))
        return

    resolved_deps, final_to_build, warnings, errors = resolve(
        specs=specs,
        provides_index=provides_index,
        available_repo=available_repo,
        requested_to_build=requested_to_build,
        rebuild_dependents=args.rebuild_dependents
    )

    if errors:
        print("Ошибки разрешения зависимостей:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    plan = build_plan(final_to_build, resolved_deps, available_repo)

    cycle_stages = [
        stage
        for stage in plan["stages"]
        if stage["type"] == "cycle"
    ]

    if cycle_stages:
        print(json.dumps({
            "warnings": warnings,
            "error": {
                "type": "unresolved_cycle",
                "message": (
                    "Невозможно построить план сборки. "
                    "Некоторые пакеты зависят друг от друга по кругу, "
                    "и эту зависимость нельзя закрыть пакетами из репозитория. "
                    "Первая сборка не сможет начаться, потому что для нее уже нужен "
                    "один из пакетов этого же цикла."
                ),
                "cycle_stages": cycle_stages,
            },
            "analysis": plan,
        }, indent=2, ensure_ascii=False))
        sys.exit(1)

    output = {
        "warnings": warnings,
        "plan": plan,
    }

    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()