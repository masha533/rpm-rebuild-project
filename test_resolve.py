import json

from parser import PackageSpec
from resolve import resolve


def debug_output(title, result):
    resolved_deps, final_to_build, warnings, errors = result

    print(f"\n=== {title} ===")
    print(json.dumps(
        {
            "resolved_deps": {k: sorted(v) for k, v in sorted(resolved_deps.items())},
            "final_to_build": sorted(final_to_build),
            "warnings": warnings,
            "errors": errors,
        },
        indent=2,
        ensure_ascii=False,
    ))


def case_simple_chain():
    specs = {
        "llvm": PackageSpec(
            name="llvm",
            provides={"llvm"},
            build_requires={"gcc"},
        ),
        "gcc": PackageSpec(
            name="gcc",
            provides={"gcc"},
            build_requires={"binutils"},
        ),
        "binutils": PackageSpec(
            name="binutils",
            provides={"binutils"},
            build_requires=set(),
        ),
    }

    provides_index = {
        "llvm": {"llvm"},
        "gcc": {"gcc"},
        "binutils": {"binutils"},
    }

    available_repo = set()
    requested_to_build = {"llvm"}

    return resolve(specs, provides_index, available_repo, requested_to_build)


def case_already_in_repo():
    specs = {
        "llvm": PackageSpec(
            name="llvm",
            provides={"llvm"},
            build_requires={"gcc", "pkgconfig(zlib)"},
        ),
        "gcc": PackageSpec(
            name="gcc",
            provides={"gcc"},
            build_requires=set(),
        ),
    }

    provides_index = {
        "llvm": {"llvm"},
        "gcc": {"gcc"},
        "pkgconfig(zlib)": {"zlib-devel"},
    }

    available_repo = {"zlib-devel"}
    requested_to_build = {"llvm"}

    return resolve(specs, provides_index, available_repo, requested_to_build)


def case_multiple_providers():
    specs = {
        "app": PackageSpec(
            name="app",
            provides={"app"},
            build_requires={"libunwind"},
        ),
        "llvm": PackageSpec(
            name="llvm",
            provides={"llvm", "libunwind"},
            build_requires=set(),
        ),
    }

    provides_index = {
        "app": {"app"},
        "libunwind": {"libunwind", "llvm"},
        "llvm": {"llvm"},
    }

    available_repo = set()
    requested_to_build = {"app"}

    return resolve(specs, provides_index, available_repo, requested_to_build)


def case_missing_provider():
    specs = {
        "app": PackageSpec(
            name="app",
            provides={"app"},
            build_requires={"missing-lib"},
        ),
    }

    provides_index = {
        "app": {"app"},
    }

    available_repo = set()
    requested_to_build = {"app"}

    return resolve(specs, provides_index, available_repo, requested_to_build)


def case_shared_dependency():
    specs = {
        "app1": PackageSpec(
            name="app1",
            provides={"app1"},
            build_requires={"gcc"},
        ),
        "app2": PackageSpec(
            name="app2",
            provides={"app2"},
            build_requires={"gcc"},
        ),
        "gcc": PackageSpec(
            name="gcc",
            provides={"gcc"},
            build_requires=set(),
        ),
    }

    provides_index = {
        "app1": {"app1"},
        "app2": {"app2"},
        "gcc": {"gcc"},
    }

    available_repo = set()
    requested_to_build = {"app1", "app2"}

    return resolve(specs, provides_index, available_repo, requested_to_build)

def case_cycle_dependency():
    specs = {
        "gcc": PackageSpec(
            name="gcc",
            provides={"gcc"},
            build_requires={"glibc"},
        ),
        "glibc": PackageSpec(
            name="glibc",
            provides={"glibc"},
            build_requires={"gcc"},
        ),
    }

    provides_index = {
        "gcc": {"gcc"},
        "glibc": {"glibc"},
    }

    available_repo = set()
    requested_to_build = {"gcc"}

    return resolve(specs, provides_index, available_repo, requested_to_build)

def case_empty_dependencies():
    specs = {
        "binutils": PackageSpec(
            name="binutils",
            provides={"binutils"},
            build_requires=set(),
        ),
    }

    provides_index = {
        "binutils": {"binutils"},
    }

    available_repo = set()
    requested_to_build = {"binutils"}

    return resolve(specs, provides_index, available_repo, requested_to_build)

def case_self_dependency():
    specs = {
        "gcc": PackageSpec(
            name="gcc",
            provides={"gcc"},
            build_requires={"gcc"},
        ),
    }

    provides_index = {
        "gcc": {"gcc"},
    }

    available_repo = set()
    requested_to_build = {"gcc"}

    return resolve(specs, provides_index, available_repo, requested_to_build)


# app1  -> liba
# app2  -> liba
# tool1 -> libb
# liba  -> libb
def case_rebuild_dependents():
    specs = {
        "app1": PackageSpec(
            name="app1",
            provides={"app1"},
            build_requires={"liba"},
        ),
        "app2": PackageSpec(
            name="app2",
            provides={"app2"},
            build_requires={"liba"},
        ),
        "tool1": PackageSpec(
            name="tool1",
            provides={"tool1"},
            build_requires={"libb"},
        ),
        "liba": PackageSpec(
            name="liba",
            provides={"liba"},
            build_requires={"libb"},
        ),
        "libb": PackageSpec(
            name="libb",
            provides={"libb"},
            build_requires=set(),
        ),
    }

    provides_index = {
        "app1": {"app1"},
        "app2": {"app2"},
        "tool1": {"tool1"},
        "liba": {"liba"},
        "libb": {"libb"},
    }

    available_repo = set()
    requested_to_build = {"libb"}

    return resolve(
        specs=specs,
        provides_index=provides_index,
        available_repo=available_repo,
        requested_to_build=requested_to_build,
        rebuild_dependents=True,
    )

if __name__ == "__main__":
    debug_output("simple_chain", case_simple_chain())
    debug_output("already_in_repo", case_already_in_repo())
    debug_output("multiple_providers", case_multiple_providers())
    debug_output("missing_provider", case_missing_provider())
    debug_output("shared_dependency", case_shared_dependency())
    debug_output("cycle_dependency", case_cycle_dependency())
    debug_output("empty_dependencies", case_empty_dependencies())
    debug_output("self_dependency", case_self_dependency())
    debug_output("rebuild_dependents", case_rebuild_dependents())