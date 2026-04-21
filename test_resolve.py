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


if __name__ == "__main__":
    debug_output("simple_chain", case_simple_chain())
    debug_output("already_in_repo", case_already_in_repo())
    debug_output("multiple_providers", case_multiple_providers())
    debug_output("missing_provider", case_missing_provider())