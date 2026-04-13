"""
pip install specfile
apt install python3-rpm

что пока не так(а может и не будет так, а может и не надо совсем чтобы было так)
1. Path-зависимости и нераскрытые макросы отбрасываются.
   BuildRequires: /usr/bin/pod2man -> игнорируется.

2. вариативности нет (но в требованиям к MVP она и не требуется).
   Берётся первый пакет,выводится предупреждение.

3. Диапазоны версий игнорирутся (по заданию тоже норм).
   BuildRequires: gcc >= 11.2.0  ->  просто 'gcc'.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator
import sys
from specfile import Specfile

def _warn(msg: str) -> None:
    print(f"[warn] {msg}", file=sys.stderr)

@dataclass
class PackageSpec:
    name: str # имя главного пакета
    provides: set[str] = field(default_factory=set) # что предоставляет пакет
    build_requires: set[str] = field(default_factory=set) # что требует для сборки пакет
    source_file: Path | None = None # путь к исходному .spec файлу
    def __repr__(self) -> str:
        return (
            f"PackageSpec(name={self.name!r}, "
            f"provides={sorted(self.provides)}, "
            f"build_requires={sorted(self.build_requires)})"
        )


_VERSION_RE = re.compile(r"\s*(>=|<=|!=|=|>|<).*")
_MACRO_RE = re.compile(r"%[{(]?[\w?!]")

def _strip_version(value: str) -> str:
    # просто откидывает версию: 'binutils >= 2.24' -> 'binutils'
    return _VERSION_RE.sub("", value).strip()


def _is_macro(value: str) -> bool:
    # игнорируем пока что макросы
    return bool(_MACRO_RE.search(value))


def _is_path_dep(value: str) -> bool:
    # игнорируем пока что path-зависимости
    return value.startswith("/") or ".so" in value


def _split_deps(raw: str, *, filter_paths: bool = False) -> list[str]:
    result = []
    for comma_part in raw.split(","):
        comma_part = _strip_version(comma_part).strip()
        if not comma_part:
            continue

        tokens = comma_part.split() if " " in comma_part else [comma_part]

        for token in tokens:
            token = token.strip()
            if not token:
                continue
            if filter_paths and _is_path_dep(token):
                continue
            if _is_macro(token):
                continue
            result.append(token)

    return result


def _subpackage_name(main_name: str, section_options_tokens) -> str | None:
    # вычисляет имя subpackage
    # %package c++       ->  'main_name-c++'
    # %package -n libgcc ->  'libgcc'
    # %package (пусто)   ->  None
    raw = "".join(t.value for t in section_options_tokens).strip()

    if not raw:
        return None

    if raw.startswith("-n "):
        name = raw[3:].strip()
        return None if _is_macro(name) else name

    suffix = raw.strip()
    if _is_macro(suffix):
        return None
    return f"{main_name}-{suffix}"


def _collect_provides(tags_context, main_name: str) -> set[str]:
    # извлекает явные provides
    result: set[str] = set()
    for tag in tags_context:
        if tag.name.lower() != "provides":
            continue
        if not tag.valid:
            continue
        for dep in _split_deps(tag.expanded_value or tag.value):
            if dep and dep != main_name:
                result.add(dep)
    return result


def _collect_build_requires(tags_context) -> set[str]:
    # извлекает явные buildRequires
    result: set[str] = set()
    for tag in tags_context:
        if tag.name.lower() != "buildrequires":
            continue
        if not tag.valid:
            continue
        for dep in _split_deps(tag.expanded_value or tag.value, filter_paths=True):
            if dep:
                result.add(dep)
    return result

def parse_spec(spec_path: Path) -> PackageSpec:
    # парсим один спек-файл
    try:
        raw = Specfile(str(spec_path))
    except Exception as e:
        raise ValueError(f"Не удалось открыть {spec_path}: {e}") from e

    with raw.tags() as tags:
        name_tag = next((t for t in tags if t.name.lower() == "name"), None)
    if name_tag is None:
        raise ValueError(f"В файле {spec_path} не найдено поле Name:")
    name = (name_tag.expanded_value or name_tag.value or "").strip()
    if not name or _is_macro(name):
        raise ValueError(f"Не удалось определить имя пакета в {spec_path}: {name!r}")

    spec = PackageSpec(name=name, source_file=spec_path)
    spec.provides.add(name)

    with raw.tags() as tags:
        spec.provides.update(_collect_provides(tags, name))
        spec.build_requires.update(_collect_build_requires(tags))

    with raw.sections() as sections:
        for section in sections:
            if section.name != "package":
                continue
            subpkg_name = _subpackage_name(name, section.options._tokens)
            if subpkg_name is None:
                continue
            spec.provides.add(subpkg_name)
            try:
                with raw.tags(section.id) as sub_tags:
                    spec.provides.update(_collect_provides(sub_tags, name))
            except Exception:
                pass

    return spec

def parse_specs_dir(specs_dir: Path, ignore_errors: bool = False) -> dict[str, PackageSpec]:
    if not specs_dir.is_dir():
        raise FileNotFoundError(f"папка не найдена: {specs_dir}")

    result: dict[str, PackageSpec] = {}

    for spec_file in _iter_specs(specs_dir):
        try:
            spec = parse_spec(spec_file)
        except ValueError as exc:
            if ignore_errors:
                _warn(f"Пропускаем {spec_file.name}: {exc}")
                continue
            raise

        if spec.name in result:
            _warn(
                f"Дублирующийся пакет {spec.name!r}: "
                f"{result[spec.name].source_file} и {spec_file} "
                f"— берем первый"
            )
            continue

        result[spec.name] = spec

    return result


def _iter_specs(directory: Path) -> Iterator[Path]:
    yield from sorted(directory.rglob("*.spec"))

def build_provides_index(specs: dict[str, PackageSpec]) -> dict[str, str]:
    # обратно: capability → package_name. Чтоб удобнее граф строить было
    index: dict[str, str] = {}
    for pkg_name, spec in specs.items():
        for cap in spec.provides:
            if cap in index and index[cap] != pkg_name:
                _warn(
                    f"Capability {cap!r} предоставляется двумя пакетами: "
                    f"{index[cap]!r} и {pkg_name!r} — берем первый: {index[cap]!r}"
                )
            else:
                index[cap] = pkg_name
    return index

def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("specs_dir", type=Path)
    args = parser.parse_args()

    specs = parse_specs_dir(args.specs_dir, ignore_errors=True)
    provides_index = build_provides_index(specs)

    output = {
        "packages": {
            name: {
                "provides": sorted(spec.provides),
                "build_requires": sorted(spec.build_requires),
                "source_file": str(spec.source_file),
            }
            for name, spec in specs.items()
        },
        "provides_index": dict(sorted(provides_index.items())),
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()