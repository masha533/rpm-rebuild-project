from __future__ import annotations


def choose_bootstrap_order(
    component: list[str],
    graph: dict[str, list[str] | set[str]],
) -> list[str]:
    """
    Выбирает порядок пакетов внутри цикла.

    Жаднаый алгоритм:
    на каждом шаге берем пакет, у которого минимально число
    зависимостей на еще не выбранные пакеты той же компоненты.

    Если таких несколько, раньше берем тот, от которого зависит
    больше пакетов внутри оставшейся компоненты.
    """
    remaining = set(component)
    order: list[str] = []

    while remaining:
        best_pkg = ""
        best_key = None

        for pkg in sorted(remaining):
            unresolved_internal = 0
            reverse_need = 0

            for dep in graph.get(pkg, []):
                if dep in remaining:
                    unresolved_internal += 1

            for other in remaining:
                if pkg in graph.get(other, []):
                    reverse_need += 1

            key = (unresolved_internal, -reverse_need, pkg)

            if best_key is None or key < best_key:
                best_key = key
                best_pkg = pkg

        order.append(best_pkg)
        remaining.remove(best_pkg)

    return order


def expand_cycle_stage(
    stage: dict,
    graph: dict[str, list[str] | set[str]],
    external_dep_stage_ids: list[int],
    start_stage_id: int,
) -> list[dict]:
    """
    Разворачивает одну cycle-stage во внутренний DAG

    Схема такая:
    1) bootstrap(pkg) для каждого пакета в выбранном порядке
    2) full(pkg) для каждого пакета в том же порядке
    3) final(pkg) в обратном порядке, но только для тех пакетов,
       у которых были отложенные внутренние зависимости

    Идея:
    - на этапе bootstrap зависимости на более поздние пакеты цикла откладываются
    - на full этапе уже использует full-версии ранних пакетов
      и bootstrap-версии поздних
    - final пытается дозакрыть пакеты, у которых были
      отложенные внутренние зависимости
    """
    component = sorted(stage["packages"])
    comp_set = set(component)
    order = choose_bootstrap_order(component, graph)
    pos = {pkg: i for i, pkg in enumerate(order)}

    new_stages: list[dict] = []

    boot_stage_of: dict[str, int] = {}
    full_stage_of: dict[str, int] = {}
    final_stage_of: dict[str, int] = {}

    deferred_of: dict[str, list[str]] = {}
    earlier_of: dict[str, list[str]] = {}
    external_of: dict[str, list[str]] = {}

    # 1. bootstrap
    for pkg in order:
        internal_deps = sorted(dep for dep in graph.get(pkg, []) if dep in comp_set)
        earlier_internal = sorted(dep for dep in internal_deps if pos[dep] < pos[pkg])
        deferred_internal = sorted(dep for dep in internal_deps if pos[dep] >= pos[pkg])
        external_deps = sorted(dep for dep in graph.get(pkg, []) if dep not in comp_set)

        earlier_of[pkg] = earlier_internal
        deferred_of[pkg] = deferred_internal
        external_of[pkg] = external_deps

        depends_on = list(external_dep_stage_ids)
        for dep in earlier_internal:
            depends_on.append(boot_stage_of[dep])
        depends_on = sorted(set(depends_on))

        stage_id = start_stage_id + len(new_stages)
        boot_stage_of[pkg] = stage_id

        new_stages.append(
            {
                "id": stage_id,
                "packages": [pkg],
                "type": "bootstrap",
                "depends_on": depends_on,
                "internal_edges": [[pkg, dep] for dep in internal_deps],
                "bootstrap_required": True,
                "reason": {
                    "kind": "cycle_bootstrap_step",
                    "component_packages": order,
                    "order_index": pos[pkg],
                    "earlier_internal_requires": earlier_internal,
                    "deferred_internal_requires": deferred_internal,
                    "external_requires": external_deps,
                    "message": (
                        f"Bootstrap-этап для пакета {pkg!r}. "
                        f"Внутренние зависимости на более поздние пакеты цикла "
                        f"временно откладываются."
                    ),
                },
            }
        )

    # 2. full
    for pkg in order:
        internal_deps = sorted(dep for dep in graph.get(pkg, []) if dep in comp_set)
        earlier_internal = earlier_of[pkg]
        deferred_internal = deferred_of[pkg]
        external_deps = external_of[pkg]

        depends_on = list(external_dep_stage_ids)
        depends_on.append(boot_stage_of[pkg])

        for dep in earlier_internal:
            depends_on.append(full_stage_of[dep])

        for dep in deferred_internal:
            depends_on.append(boot_stage_of[dep])

        depends_on = sorted(set(depends_on))

        stage_id = start_stage_id + len(new_stages)
        full_stage_of[pkg] = stage_id

        new_stages.append(
            {
                "id": stage_id,
                "packages": [pkg],
                "type": "full",
                "depends_on": depends_on,
                "internal_edges": [[pkg, dep] for dep in internal_deps],
                "bootstrap_required": True,
                "reason": {
                    "kind": "cycle_full_step",
                    "component_packages": order,
                    "order_index": pos[pkg],
                    "uses_full_from_earlier_packages": earlier_internal,
                    "uses_bootstrap_from_later_or_self_packages": deferred_internal,
                    "external_requires": external_deps,
                    "message": (
                        f"Полная сборка пакета {pkg!r}. "
                        f"Для более ранних пакетов цикла используются full-этапы, "
                        f"для более поздних или самого себя используются "
                        f"bootstrap-этапы."
                    ),
                },
            }
        )

    # 3. final
    # идем справа налево и перестраиваем только те пакеты,
    # у которых были отложенные внутренние зависимости
    for pkg in reversed(order):
        deferred_internal = deferred_of[pkg]
        earlier_internal = earlier_of[pkg]
        external_deps = external_of[pkg]

        if not deferred_internal:
            continue

        depends_on = list(external_dep_stage_ids)
        depends_on.append(full_stage_of[pkg])

        for dep in earlier_internal:
            if dep in final_stage_of:
                depends_on.append(final_stage_of[dep])
            else:
                depends_on.append(full_stage_of[dep])

        for dep in deferred_internal:
            if dep in final_stage_of:
                depends_on.append(final_stage_of[dep])
            else:
                depends_on.append(full_stage_of[dep])

        depends_on = sorted(set(depends_on))

        stage_id = start_stage_id + len(new_stages)
        final_stage_of[pkg] = stage_id

        new_stages.append(
            {
                "id": stage_id,
                "packages": [pkg],
                "type": "final",
                "depends_on": depends_on,
                "internal_edges": [[pkg, dep] for dep in sorted(graph.get(pkg, [])) if dep in comp_set],
                "bootstrap_required": True,
                "reason": {
                    "kind": "cycle_final_step",
                    "component_packages": order,
                    "order_index": pos[pkg],
                    "external_requires": external_deps,
                    "deferred_internal_requires": deferred_internal,
                    "message": (
                        f"Финальный этап для пакета {pkg!r}. "
                        f"Он нужен, потому что на предыдущих шагах были "
                        f"отложенные внутренние зависимости внутри цикла."
                    ),
                },
            }
        )

    return new_stages


def apply_bootstrap(plan: dict) -> dict:
    """
    Берет план из planner.py и разворачивает все cycle-stage.

    Важно:
    - обычные ацикличные стадии просто копируются
    - если старая стадия была развернута в несколько новых,
      все последующие зависимости на нее переводятся на
      последнюю стадию этой группы
    """
    graph = plan["packages_graph"]
    old_stages = plan["stages"]

    new_stages: list[dict] = []

    # старй stage id -> список новых stage id
    produced_from_old: dict[int, list[int]] = {}

    for old_stage in old_stages:
        remapped_dep_ids: list[int] = []

        for dep in old_stage["depends_on"]:
            created = produced_from_old.get(dep, [])
            if not created:
                raise ValueError(
                    f"Не удалось найти уже построенные стадии для зависимости {dep}"
                )
            remapped_dep_ids.append(created[-1])

        remapped_dep_ids = sorted(set(remapped_dep_ids))

        if old_stage["type"] != "cycle":
            new_id = len(new_stages)

            copied = dict(old_stage)
            copied["id"] = new_id
            copied["depends_on"] = remapped_dep_ids

            if "reason" not in copied:
                copied["reason"] = {
                    "kind": "acyclic_component",
                    "component_packages": copied["packages"],
                    "message": (
                        "Компонента не содержит циклов, поэтому перенесена "
                        "в итоговый план без bootstrap-разворачивания."
                    ),
                }

            new_stages.append(copied)
            produced_from_old[old_stage["id"]] = [new_id]
            continue

        expanded = expand_cycle_stage(
            stage=old_stage,
            graph=graph,
            external_dep_stage_ids=remapped_dep_ids,
            start_stage_id=len(new_stages),
        )

        new_stages.extend(expanded)
        produced_from_old[old_stage["id"]] = [stage["id"] for stage in expanded]

    result = dict(plan)
    result["stages"] = new_stages
    result["bootstrap_algorithm"] = {
        "type": "greedy_inside_cycle",
        "message": (
            "Для каждой cycle-stage выбирается жадный порядок пакетов, "
            "после чего строятся bootstrap, full и при необходимости "
            "final-этапы."
        ),
    }

    return result