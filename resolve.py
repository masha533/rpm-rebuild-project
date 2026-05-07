# Resolve этап преобразует зависимости из spec-файлов (BuildRequires)
# в конкретные пакеты, которые необходимо собрать.


from __future__ import annotations
from collections import deque
from parser import PackageSpec


def choose_provider(
    req: str,
    providers: set[str],
    available_repo: set[str],
    final_to_build: set[str],
    available_specs: set[str],
) -> tuple[str | None, str | None]:
    """
    Возвращает:
    - выбранный provider или None
    - reason / warning message или None
    """
    if not providers:
        return None, f"Не найден provider для зависимости {req!r}"

    note = None
    if len(providers) > 1:
        note = (
            f"Для зависимости {req!r} найдено несколько provider'ов "
            f"{sorted(providers)}"
        )


    repo_candidates = sorted(p for p in providers if p in available_repo)
    if repo_candidates:
        chosen = repo_candidates[0]
        if note is not None:
            note += f"; выбран уже доступный в repo {chosen!r}"

        return chosen, note

    build_candidates = sorted(p for p in providers if p in final_to_build)
    if build_candidates:
        chosen = build_candidates[0]
        if note is not None:
            note += f"; выбран уже включённый в сборку {chosen!r}"

        return chosen, note

    spec_candidates = sorted(p for p in providers if p in available_specs)
    if spec_candidates:
        chosen = spec_candidates[0]
        if note is not None:
            note += f"; выбран пакет, для которого есть локальный spec {chosen!r}"

        return chosen, note


    chosen = sorted(providers)[0]

    if note is not None:
        note += f"; выбран {chosen!r}"

    return chosen, note



def build_reverse_dependencies(
    specs: dict[str, PackageSpec],
    provides_index: dict[str, set[str]],
) -> dict[str, set[str]]:
    """
    Строит обратный граф зависимостей.

    Если пакет A имеет BuildRequires: B,
    то в обратном графе появляется ребро:
    B -> A

    То есть по пакету можно найти все пакеты,
    которые от него зависят.
    """
    reverse_deps: dict[str, set[str]] = {}

    available_specs = set(specs)

    for pkg, spec in specs.items():
        for req in sorted(spec.build_requires):
            providers = provides_index.get(req, set())

            provider, _ = choose_provider(
                req=req,
                providers=providers,
                available_repo=set(),
                final_to_build=set(),
                available_specs=available_specs,
            )

            if provider is None:
                continue


            reverse_deps.setdefault(provider, set()).add(pkg)

    return reverse_deps

def expand_with_dependents(
    requested_to_build: set[str],
    reverse_deps: dict[str, set[str]],
) -> set[str]:
    """
    Расширяет requested_to_build пакетами, которые прямо или косвенно
    зависят от исходно запрошенных пакетов.
    """
    expanded = set(requested_to_build)
    queue = deque(sorted(requested_to_build))

    while queue:
        pkg = queue.popleft()

        for dependent in sorted(reverse_deps.get(pkg, set())):
            if dependent in expanded:
                continue

            expanded.add(dependent)
            queue.append(dependent)

    return expanded



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
# - rebuild_dependents: bool
#     если True, перед обычным раскрытием BuildRequires множество requested_to_build
#     расширяется всеми пакетами, которые прямо или косвенно зависят от исходно
#     запрошенных пакетов
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
    rebuild_dependents: bool = False,
) -> tuple[
    dict[str, set[str]],
    set[str],
    list[str],
    list[str],
]:
    if rebuild_dependents:
        reverse_deps = build_reverse_dependencies(
            specs=specs,
            provides_index=provides_index,
        )

        requested_to_build = expand_with_dependents(
            requested_to_build=requested_to_build,
            reverse_deps=reverse_deps,
        )

    queue = deque(sorted(requested_to_build))

    final_to_build = set(requested_to_build)
    resolved_deps: dict[str, set[str]] = {}
    warnings: list[str] = []
    errors: list[str] = []

    processed: set[str] = set()
    while queue:
        pkg = queue.popleft()

        if pkg in processed:
            continue
        processed.add(pkg)

        resolved_deps.setdefault(pkg, set())

        spec = specs.get(pkg)
        if spec is None:
            errors.append(f"Не найден spec для пакета {pkg!r}")
            continue

        available_specs = set(specs)
        for req in sorted(spec.build_requires):
            providers = provides_index.get(req, set())

            provider, note = choose_provider(
                req=req,
                providers=providers,
                available_repo=available_repo,
                final_to_build=final_to_build,
                available_specs=available_specs,
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