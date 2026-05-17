from __future__ import annotations


def dot_quote(value: str) -> str:
    """
    Экранирует строку для DOT-формата Graphviz.
    """
    str = (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )
    return f'"{str}"'


def export_packages_graph_to_dot(plan: dict) -> str:
    """
    Экспортирует граф пакетов в DOT.

    В plan["packages_graph"] зависимости лежат так:
        package -> [dependency, ...]

    Для Graphviz рисуем наоборот:
        dependency -> package

    Получается сначала зависимость, потом пакет, который от неё зависит.
    """
    graph = plan.get("packages_graph", {})
    lines: list[str] = [
        "digraph packages {",
        "  rankdir=LR;",
        "  node [shape=box];",
        "",
    ]


    for pkg in sorted(graph):
        lines.append(f"  {dot_quote(pkg)};")

    if graph:
        lines.append("")

    for pkg in sorted(graph):
        for dep in sorted(graph[pkg]):
            lines.append(f"  {dot_quote(dep)} -> {dot_quote(pkg)};")

    lines.append("}")
    return "\n".join(lines) + "\n"