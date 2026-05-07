"""
Запуск (из папки tests):
    pytest tests.py -v

Структура теста:
    run_main(required, available) -> subprocess.CompletedProcess
    extract_json(stdout) -> dict          # вытащить JSON из stdout
    is_dag(stages) -> bool                # проверить что stages — DAG
    check_cycle_stages(stages, pkgs)      # проверить bootstrap/full/final структуру
"""

import json
import shutil
import subprocess
import sys
from collections import defaultdict, deque
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

COMMON_AVAILABLE = [
    "m4", "perl", "coreutils", "make", "findutils", "sed", "grep",
    "bison", "flex", "gettext", "texinfo", "texinfo-tex", "help2man",
    "zlib-devel", "gmp-devel", "mpfr-devel", "elfutils-devel",
    "elfutils-libelf-devel", "systemtap-sdt-devel", "python2-devel",
    "python34-devel", "dejagnu", "sharutils", "gdb", "libstdc++-devel",
    "gcc-gfortran", "gcc-gnat", "gcc-go", "gcc-objc", "gcc-objc++",
    "libgnat", "pkgconfig", "glibc-devel", "glibc-static",
    "perl(Data::Dumper)", "perl(Text::ParseWords)", "perl-generators",
    "perl(Thread::Queue)", "perl(threads)", "gcc"
]

AUTOCONF_AVAILABLE = ["m4", "help2man"]
AUTOMAKE_AVAILABLE = ["autoconf", "coreutils", "findutils", "help2man", "make"]
LIBTOOL_AVAILABLE = [
    "autoconf", "automake", "gcc-gfortran", "help2man",
    "libstdc++-devel", "texinfo", "pkgconfig",
]

def write_packages_file(path: Path, packages: list[str] | set[str]) -> Path:
    unique = list(dict.fromkeys(packages))
    path.write_text("\n".join(unique) + "\n", encoding="utf-8")
    return path


def extract_json(stdout: str) -> dict:
    #Вытащить JSON из stdout, игнорируя возможные warn-строки перед ним
    text = stdout.strip()
    if not text:
        raise ValueError("stdout пустой")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        lines = stdout.splitlines()
        start = next(
            (i for i, line in enumerate(lines) if line.lstrip().startswith("{")),
            None,
        )
        if start is None:
            raise ValueError(f"JSON не найден в stdout:\n{stdout[:500]}")
        json_lines = []
        brace_count = 0
        for line in lines[start:]:
            json_lines.append(line)
            for ch in line:
                if ch == "{":
                    brace_count += 1
                elif ch == "}":
                    brace_count -= 1
            if brace_count == 0:
                break
        return json.loads("\n".join(json_lines))


def is_dag(stages: list[dict]) -> bool:
    # проверить что граф стадий ациклический (топологическая сортировка
    graph = {s["id"]: set(s["depends_on"]) for s in stages}
    reverse: dict = defaultdict(set)
    for node, deps in graph.items():
        for dep in deps:
            reverse[dep].add(node)
    indegree = {node: len(deps) for node, deps in graph.items()}
    q = deque(node for node, deg in indegree.items() if deg == 0)
    seen = 0
    while q:
        node = q.popleft()
        seen += 1
        for dependent in reverse.get(node, ()):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                q.append(dependent)
    return seen == len(graph)


def check_cycle_stages(stages: list[dict], cycle_packages: set[str]) -> bool:
    # для каждого пакета из цикла проверить наличие bootstrap -> full -> [final]
    by_pkg: dict[str, list[dict]] = defaultdict(list)
    for stage in stages:
        for pkg in stage["packages"]:
            if pkg in cycle_packages:
                by_pkg[pkg].append(stage)

    for pkg in cycle_packages:
        pkg_stages = sorted(by_pkg.get(pkg, []), key=lambda s: s["id"])
        if not pkg_stages:
            return False
        types = [s["type"] for s in pkg_stages]
        if "bootstrap" not in types or "full" not in types:
            return False
        bootstrap = next(s for s in pkg_stages if s["type"] == "bootstrap")
        full = next(s for s in pkg_stages if s["type"] == "full")
        if bootstrap["id"] >= full["id"]:
            return False
        if bootstrap["id"] not in full["depends_on"]:
            return False
        for fin in (s for s in pkg_stages if s["type"] == "final"):
            if fin["id"] <= full["id"]:
                return False
    return True


def last_stage_id_for(pkg: str, stages: list[dict]) -> int:
    # ID последней стадии пакета (нужно для пакетов с bootstrap/full/final)
    ids = [s["id"] for s in stages if pkg in s["packages"]]
    if not ids:
        raise KeyError(f"Пакет {pkg!r} не найден в stages")
    return max(ids)

@pytest.fixture
def specs_dir(tmp_path: Path) -> Path:
    src = "specs"
    dst = tmp_path / "specs"
    shutil.copytree(src, dst)
    return dst


@pytest.fixture
def run_main(specs_dir: Path, tmp_path: Path):
    def _run(required_packages: list[str], available_packages: list[str]):
        available_file = write_packages_file(
            tmp_path / "available.txt", available_packages
        )
        required_file = write_packages_file(
            tmp_path / "required.txt", required_packages
        )
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "main.py"),
            str(specs_dir),
            str(available_file),
            str(required_file),
        ]
        return subprocess.run(cmd, capture_output=True, text=True)

    return _run


def test_required_gcc(run_main):
    # gcc требует сборки всего тулчейна, даже для пересборки
    result = run_main(["gcc"], COMMON_AVAILABLE)
    assert result.returncode == 0, f"stderr:\n{result.stderr}"

    output = extract_json(result.stdout)
    stages = output["plan"]["stages"]

    assert is_dag(stages)
    all_pkgs = {pkg for s in stages for pkg in s["packages"]}
    assert {"gcc", "binutils", "isl"}.issubset(all_pkgs)
    #assert check_cycle_stages(stages, {"gcc", "binutils"})

def test_required_gcc_cycle_error(run_main):
    # В available нет ни gcc, ни binutils -> ожидаем ошибку unresolved_cycle
    common_without_gcc = COMMON_AVAILABLE.copy()
    common_without_gcc.remove("gcc")
    result = run_main(["gcc"], common_without_gcc)
    assert result.returncode != 0
    output = extract_json(result.stdout)
    assert output["error"]["type"] == "unresolved_cycle"

def test_required_binutils_and_only_once_in_plan(run_main):
    result = run_main(["binutils"], COMMON_AVAILABLE)
    assert result.returncode == 0, f"stderr:\n{result.stderr}"

    output = extract_json(result.stdout)
    stages = output["plan"]["stages"]

    assert is_dag(stages)
    all_pkgs = [pkg for s in stages for pkg in s["packages"]]
    assert "binutils" in all_pkgs
    assert all_pkgs.count("binutils") == 1
    #assert check_cycle_stages(stages, {"gcc", "binutils"})


def test_required_isl_one_stage(run_main):
    # isl не имеет зависимостей из наших spec-файлов — ровно одна acyclic-стадия
    result = run_main(["isl"], COMMON_AVAILABLE)
    assert result.returncode == 0, f"stderr:\n{result.stderr}"

    output = extract_json(result.stdout)
    stages = output["plan"]["stages"]

    assert is_dag(stages)
    assert len(stages) == 1
    assert stages[0]["type"] == "acyclic"
    assert stages[0]["packages"] == ["isl"]


def test_required_autoconf_one_stage(run_main):
    # autoconf не зависит от других наших пакетов — ровно одна acyclic-стадия
    result = run_main(["autoconf"], COMMON_AVAILABLE)
    assert result.returncode == 0, f"stderr:\n{result.stderr}"

    output = extract_json(result.stdout)
    stages = output["plan"]["stages"]

    assert is_dag(stages)
    assert len(stages) == 1
    assert stages[0]["type"] == "acyclic"
    assert stages[0]["packages"] == ["autoconf"]


def test_required_automake_reuses_available_autoconf(run_main):
    # Если autoconf уже в репо, он не должен попасть в план сборки automake
    available = list(dict.fromkeys(COMMON_AVAILABLE + AUTOCONF_AVAILABLE + ["autoconf"]))
    result = run_main(["automake"], available)
    assert result.returncode == 0, f"stderr:\n{result.stderr}"

    output = extract_json(result.stdout)
    stages = output["plan"]["stages"]

    assert is_dag(stages)
    all_pkgs = {pkg for s in stages for pkg in s["packages"]}
    assert "automake" in all_pkgs
    assert "autoconf" not in all_pkgs


def test_required_libtool_reuses_available_autoconf_and_automake(run_main):
    # Если autoconf и automake в репо, libtool строится один без них
    available = list(dict.fromkeys(
        COMMON_AVAILABLE + AUTOCONF_AVAILABLE + AUTOMAKE_AVAILABLE
        + LIBTOOL_AVAILABLE + ["autoconf", "automake"]
    ))
    result = run_main(["libtool"], available)
    assert result.returncode == 0, f"stderr:\n{result.stderr}"

    output = extract_json(result.stdout)
    stages = output["plan"]["stages"]

    assert is_dag(stages)
    all_pkgs = {pkg for s in stages for pkg in s["packages"]}
    assert "libtool" in all_pkgs
    assert "autoconf" not in all_pkgs
    assert "automake" not in all_pkgs


def test_required_libtool_builds_autoconf_and_automake(run_main):
    # libtool тянет autoconf и automake транзитивно, порядок строго соблюдается
    result = run_main(["libtool"], COMMON_AVAILABLE)
    assert result.returncode == 0, f"stderr:\n{result.stderr}"

    output = extract_json(result.stdout)
    stages = output["plan"]["stages"]

    assert is_dag(stages)
    all_pkgs = {pkg for s in stages for pkg in s["packages"]}
    assert {"libtool", "autoconf", "automake"}.issubset(all_pkgs)
    assert last_stage_id_for("autoconf", stages) < last_stage_id_for("automake", stages)
    assert last_stage_id_for("automake", stages) < last_stage_id_for("libtool", stages)
    for pkg in ("autoconf", "automake", "libtool"):
        stage = next(s for s in stages if pkg in s["packages"])
        assert stage["type"] == "acyclic"


def test_required_package_not_skipped_if_already_available(run_main):
    available = list(dict.fromkeys(COMMON_AVAILABLE + ["isl"]))
    result = run_main(["isl"], available)
    assert result.returncode == 0, f"stderr:\n{result.stderr}"

    output = extract_json(result.stdout)
    stages = output["plan"]["stages"]

    assert is_dag(stages)
    all_pkgs = {pkg for s in stages for pkg in s["packages"]}
    assert "isl" in all_pkgs


def test_no_duplicate(run_main):
    # autoconf + automake в одном запросе: оба в плане, autoconf ровно один раз
    result = run_main(["autoconf", "automake"], COMMON_AVAILABLE)
    assert result.returncode == 0, f"stderr:\n{result.stderr}"

    output = extract_json(result.stdout)
    stages = output["plan"]["stages"]
    all_pkgs = {pkg for s in stages for pkg in s["packages"]}

    assert "autoconf" in all_pkgs
    assert "automake" in all_pkgs

    assert sum("autoconf" in s["packages"] for s in stages) == 1


def test_shared_dependency_no_duplicate(run_main):
    # automake и libtool оба зависят от autoconf — он строится ровно один раз
    result = run_main(["automake", "libtool"], COMMON_AVAILABLE)
    assert result.returncode == 0, f"stderr:\n{result.stderr}"

    output = extract_json(result.stdout)
    stages = output["plan"]["stages"]
    all_pkgs = {pkg for s in stages for pkg in s["packages"]}

    assert "autoconf" in all_pkgs
    assert sum("autoconf" in s["packages"] for s in stages) == 1


@pytest.mark.parametrize("pkg", ["isl", "binutils"])
def test_package_builds_even_if_in_repo(run_main, pkg):
    # Пакет запрошен к сборке, но уже есть в репо — все равно добавляем
    available = list(dict.fromkeys(COMMON_AVAILABLE + [pkg]))
    result = run_main([pkg], available)
    assert result.returncode == 0, f"stderr:\n{result.stderr}"

    output = extract_json(result.stdout)
    all_pkgs = {p for s in output["plan"]["stages"] for p in s["packages"]}
    assert pkg in all_pkgs


def test_missing_required_package_errors(run_main):
    # Пакет которого нет ни в specs ни в репо — ненулевой код возврата
    result = run_main(["nonexistent"], COMMON_AVAILABLE)
    assert result.returncode != 0
    assert "nonexistent" in result.stderr


def test_empty_required_list_returns_empty_plan(run_main):
    # Пустой build_list —  пустой список стадий
    result = run_main([], COMMON_AVAILABLE)
    assert result.returncode == 0, f"stderr:\n{result.stderr}"

    output = extract_json(result.stdout)
    assert output["plan"]["stages"] == []


def test_transitive_dependency_not_in_repo(run_main):
    # Транзитивная зависимость которой нет в репо, должна попасть в план
    result = run_main(["libtool"], COMMON_AVAILABLE)
    assert result.returncode == 0, f"stderr:\n{result.stderr}"

    output = extract_json(result.stdout)
    all_pkgs = {p for s in output["plan"]["stages"] for p in s["packages"]}

    assert "autoconf" in all_pkgs
    assert "automake" in all_pkgs


def test_transitive_dependency_in_repo(run_main):
    # Транзитивная зависимость которая есть в репо, не должна тянуться в план
    available = list(dict.fromkeys(COMMON_AVAILABLE + ["isl"]))
    result = run_main(["gcc"], available)
    assert result.returncode == 0, f"stderr:\n{result.stderr}"

    output = extract_json(result.stdout)
    all_pkgs = {p for s in output["plan"]["stages"] for p in s["packages"]}

    assert "isl" not in all_pkgs
    assert "gcc" in all_pkgs


def test_stages_depend_only_on_earlier_stages(run_main):
    # Каждая стадия может зависеть только от стадий с меньшим id
    result = run_main(["libtool"], COMMON_AVAILABLE)
    assert result.returncode == 0, f"stderr:\n{result.stderr}"

    stages = extract_json(result.stdout)["plan"]["stages"]
    for stage in stages:
        for dep_id in stage["depends_on"]:
            assert dep_id < stage["id"], (
                f"Стадия {stage['id']} зависит от стадии {dep_id} "
                f"с бо́льшим или равным id — нарушение порядка"
            )


def test_all_requested_packages_in_plan(run_main):
    # Каждый запрошенный пакет должен появитсья в плане
    requested = ["autoconf", "automake", "libtool"]
    result = run_main(requested, COMMON_AVAILABLE)
    assert result.returncode == 0, f"stderr:\n{result.stderr}"

    output = extract_json(result.stdout)
    all_pkgs = {p for s in output["plan"]["stages"] for p in s["packages"]}

    for pkg in requested:
        in_plan = pkg in all_pkgs
        assert in_plan, f"{pkg!r} не попал в план"