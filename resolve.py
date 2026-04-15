# Resolve этап преобразует зависимости из spec-файлов (BuildRequires)
# в конкретные пакеты, которые необходимо собрать.




# заглушка, это dataclass из parser.py, потом просто импортом этого файлика решится вопрос
#
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

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






def choose_provider(
    req: str,
    providers: set[str],
    available_repo: set[str],
    final_to_build: set[str],
) -> tuple[str | None, str | None]:
    """
    Возвращает:
    - выбранный provider или None
    - reason / warning message или None
    """
    if not providers:
        return None, f"Не найден provider для зависимости {req!r}"


    repo_candidates = sorted(p for p in providers if p in available_repo)
    if repo_candidates:
        return repo_candidates[0], None

    build_candidates = sorted(p for p in providers if p in final_to_build)
    if build_candidates:
        return build_candidates[0], None

    chosen = sorted(providers)[0]

    if len(providers) > 1:
        return chosen, (
            f"Для зависимости {req!r} найдено несколько provider'ов "
            f"{sorted(providers)}; выбран {chosen!r}"
        )

    return chosen, None




# Параметры:
# - specs: dict[str, PackageSpec]
#     отображение имя_пакета → PackageSpec;
#     содержит извлечённые из .spec данные:
#     - provides: какие capability предоставляет пакет
#     - build_requires: какие зависимости нужны для сборки
#
# - provides_index: dict[str, set[str]]
#     отображение capability -> множество пакетов-provider'ов;
#     используется для разрешения абстрактных зависимостей
#     (например, "pkgconfig(zlib)" -> {"zlib-devel"})
#     или в общем случае:
#     "libunwind" -> {"libunwind", "llvm"}
#
# - available_repo: set[str]
#     множество пакетов, уже доступных в репозитории;
#     такие пакеты считаются уже удовлетворёнными и не добавляются в сборку
#
# - requested_to_build: set[str]
#     исходный список пакетов, которые требуется собрать;
#     используется как начальное множество, которое затем расширяется
#     транзитивными зависимостями
#
# Возвращает:
# - resolved_deps: dict[pkg → set[pkg]]
#     для каждого пакета список его зависимостей, уже разрешённых в конкретные пакеты;
#     включает только те пакеты, которые требуется собрать
#
# - final_to_build: set[pkg]
#     итоговое множество пакетов для сборки (с учётом всех транзитивных зависимостей)
#
# - warnings: list[str]
#     некритичные проблемы (например, несколько provider’ов — выбран первый)
#
# - errors: list[str]
#     критические ошибки (например, зависимость невозможно разрешить)
#
# Гарантии:
# - в resolved_deps нет абстрактных зависимостей (вроде pkgconfig(...))
# - пакеты из available_repo не попадают в зависимости
# - final_to_build содержит замыкание зависимостей от requested_to_build

def resolve(
    specs: dict[str, PackageSpec],
    provides_index: dict[str, set[str]],
    available_repo: set[str],
    requested_to_build: set[str],
) -> tuple[
    dict[str, set[str]],
    set[str],
    list[str],
    list[str],
]:
    queue = list(requested_to_build)
    final_to_build = set(requested_to_build)
    resolved_deps: dict[str, set[str]] = {}
    warnings: list[str] = []
    errors: list[str] = []

    processed: set[str] = set()
    while queue:
        pkg = queue.pop(0)

        if pkg in processed:
            continue
        processed.add(pkg)

        resolved_deps.setdefault(pkg, set())

        spec = specs.get(pkg)
        if spec is None:
            errors.append(f"Не найден spec для пакета {pkg!r}")
            continue

        for req in spec.build_requires:
            providers = provides_index.get(req, set())

            provider, note = choose_provider(
                req=req,
                providers=providers,
                available_repo=available_repo,
                final_to_build=final_to_build,
            )


            if provider is None:
                errors.append(
                    note or f"Не удалось разрешить зависимость {req!r} для пакета {pkg!r}"
                )
                continue

            if note is not None:
                warnings.append(f"{pkg!r}: {note}")

            if provider in available_repo:
                continue

            resolved_deps[pkg].add(provider)

            if provider not in final_to_build:
                final_to_build.add(provider)
                queue.append(provider)

    for pkg in final_to_build:
        resolved_deps.setdefault(pkg, set())

    return resolved_deps, final_to_build, warnings, errors