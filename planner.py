from __future__ import annotations

from collections import deque
from dataclasses import dataclass,field
from typing import Iterable


@dataclass
class Stage:
    id: int
    packages: list[str]
    type: str          # "acyclic" | "cycle"
    depends_on: list[int]
    internal_edges: list[list[str]] = field(default_factory=list)
    bootstrap_required: bool = False


def normalize_graph(
    to_build: Iterable[str],
    deps: dict[str, Iterable[str]],
    available_repo: Iterable[str] = (),
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """
    Строит граф 
    Ребро A -> B добавляется только если:
    - A зависит от B
    - B тоже надо собрать
    - B НЕ доступен в исходном репозитории

    Если B уже есть в репозитории, зависимость можно закрыть старой версией B,
    поэтому A не обязан ждать новую сборку B.
    """
    to_build_set = set(to_build)
    available_set = set(available_repo)
    graph: dict[str, set[str]] = {}
    repo_requires: dict[str, set[str]] = {}

    for pkg in to_build_set:
        graph[pkg] = set()
        repo_requires[pkg] = set()

        for dep in deps.get(pkg, []):
            if dep in available_set:
                repo_requires[pkg].add(dep)
            elif dep in to_build_set:
                graph[pkg].add(dep)

    return graph, repo_requires


def tarjan_scc(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    components: list[list[str]] = []

    def strongconnect(v: str) -> None:
        nonlocal index

        indices[v] = index
        lowlink[v] = index
        index += 1

        stack.append(v)
        on_stack.add(v)

        for w in graph[v]:
            if w not in indices:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], indices[w])

        if lowlink[v] == indices[v]:
            comp: list[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                comp.append(w)
                if w == v:
                    break
            components.append(sorted(comp))

    for v in sorted(graph):
        if v not in indices:
            strongconnect(v)

    return components


def is_cycle_component(component: list[str], graph: dict[str, set[str]]) -> bool:
    """
    Компонента считается циклом, если
    1) в ней больше одной вершины
    2) или одна вершина,но есть зависимрсть в себя
    """
    if len(component) > 1:
        return True

    only = component[0]
    return only in graph[only]

def get_internal_edges(
    component: list[str],
    graph: dict[str, set[str]],
) -> list[list[str]]:
    """
    Возвращает все ребра внутри одной компоненты.
    Например для ["gcc", "glibc"] вернет:
    [["gcc", "glibc"], ["glibc", "gcc"]]
    """
    comp_set = set(component)
    edges: list[list[str]] = []

    for src in sorted(component):
        for dst in sorted(graph[src]):
            if dst in comp_set:
                edges.append([src, dst])

    return edges

def build_stage_graph(
    graph: dict[str, set[str]],
    components: list[list[str]],
) -> tuple[dict[int, set[int]], dict[str, int]]:
    """
    Строит граф компонент.
    stage_deps[c1] = {c2, ...}
    stage c1 зависит от stage c2.
    """
    comp_of: dict[str, int] = {}
    for cid, comp in enumerate(components):
        for pkg in comp:
            comp_of[pkg] = cid

    stage_deps: dict[int, set[int]] = {cid: set() for cid in range(len(components))}

    for pkg, pkg_deps in graph.items():
        src = comp_of[pkg]
        for dep in pkg_deps:
            dst = comp_of[dep]
            if src != dst:
                stage_deps[src].add(dst)

    return stage_deps, comp_of


def top_sort_stages(stage_deps: dict[int, set[int]]) -> list[int]:
    """
    Топ сорт компонент так,чтобы зависимости шли раньше зависимых.
    У нас stage_deps[A] = {B} -> 'A зависит от B',
    строим обратные ребра B -> A.
    """
    reverse_graph: dict[int, set[int]] = {cid: set() for cid in stage_deps}
    indegree: dict[int, int] = {cid: 0 for cid in stage_deps}

    for stage, deps in stage_deps.items():
        indegree[stage] = len(deps)
        for dep in deps:
            reverse_graph[dep].add(stage)

    queue = deque(sorted(cid for cid, deg in indegree.items() if deg == 0))
    order: list[int] = []

    while queue:
        v = queue.popleft()
        order.append(v)

        for nxt in sorted(reverse_graph[v]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(stage_deps):
        raise ValueError("Не удалось выполнить топологическую сортировку графа этапов")

    return order


def build_plan(
    to_build: Iterable[str],
    deps: dict[str, Iterable[str]],
    available_repo: Iterable[str] = (),
    rebuild_reasons: dict[str, Iterable[str]] | None = None,
) -> dict:
    """
    Возвращает JSON структуру:
    - packages_graph
    - repo_requires
    - components
    - stages
    """
    rebuild_reasons = rebuild_reasons or {}

    graph, repo_requires = normalize_graph(to_build, deps, available_repo)
    components = tarjan_scc(graph)
    stage_deps, _ = build_stage_graph(graph, components)
    topo_order = top_sort_stages(stage_deps)

    #стадии в топологическом порядке: 0, 1, 2, ...
    new_id_of_old: dict[int, int] = {
        old_id: new_id for new_id, old_id in enumerate(topo_order)
    }

    stages: list[Stage] = []
    for old_cid in topo_order:
        comp = components[old_cid]
        is_cycle = is_cycle_component(comp, graph)

        stages.append(
            Stage(
                id=new_id_of_old[old_cid],
                packages=comp,
                type="cycle" if is_cycle else "acyclic",
                depends_on=sorted(new_id_of_old[dep] for dep in stage_deps[old_cid]),
                internal_edges=get_internal_edges(comp, graph) if is_cycle else [],
                bootstrap_required=is_cycle,
            )
        )

    return {
        "packages_graph": {pkg: sorted(graph[pkg]) for pkg in sorted(graph)},
        "repo_requires": {
            pkg: sorted(reqs)
            for pkg, reqs in sorted(repo_requires.items())
            if reqs
        },
        "components": [
            {
                "packages": comp,
                "type": "cycle" if is_cycle_component(comp, graph) else "acyclic",
            }
            for comp in components
        ],
        "stages": [
            {
                "id": stage.id,
                "packages": stage.packages,
                "type": stage.type,
                "depends_on": stage.depends_on,
                "internal_edges": stage.internal_edges,
                "bootstrap_required": stage.bootstrap_required,
                "rebuild_caused_by": {
                    pkg: sorted(rebuild_reasons[pkg])
                    for pkg in stage.packages if pkg in rebuild_reasons
                },
                "message": (
                    "Эти пакеты образуют круговую зависимость. "
                    "Такой этап не является готовым шагом сборки: "
                    "он добавлен в вывод только для диагностики ошибки."
                    if stage.type == "cycle"
                    else
                    "Компонента не содержит циклов, пакет собирается обычным образом."
                ),
            }
            for stage in stages
        ],
    }


if __name__ == "__main__":
    import json

    # Пример: gcc <-> glibc, а gcc еще зависит от binutils
    to_build = {"gcc", "glibc", "binutils"}
    deps = {
        "gcc": {"glibc", "binutils"},
        "glibc": {"gcc"},
        "binutils": set(),
    }

    plan = build_plan(to_build, deps)
    print(json.dumps(plan, indent=2, ensure_ascii=False))