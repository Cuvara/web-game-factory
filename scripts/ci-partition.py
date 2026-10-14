#!/usr/bin/env python3
"""How the acceptance workflow splits the suite across parallel jobs, and the proof that the
split leaves nothing out. Standard library only.

    ci-partition.py units SHARD COUNT   test modules for one unit shard, space-separated
    ci-partition.py core                one per line: every Core Acceptance Suite category
                                        except the goldens and the opt-in ones
    ci-partition.py golden              the golden categories, one per line
    ci-partition.py check COUNT         exit 1 unless every test module runs in exactly one
                                        place: a unit shard, or a category of the core or
                                        golden jobs (the opt-in categories run where they
                                        always did: their own job, or nowhere by default)

A unit shard runs the modules no category of the suite names; the core job runs the
categories with `bin/wgf test-core --strict`, which is where they ran before the split as
well (the old single job ran the whole unit suite and then test-core, so those modules ran
twice). Modules are dealt to shards by size, largest first, onto the lightest shard, so a
shard's time follows the code it tests rather than the alphabet.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.join(HERE, "tests")
sys.path.insert(0, TESTS)

import core_suite  # noqa: E402


def golden():
    return [c for c in core_suite.SUITE if "GOLDEN" in c and c not in core_suite.OPT_IN]


def core():
    return [c for c in core_suite.SUITE if c not in core_suite.OPT_IN and c not in golden()]


def suite_modules(categories):
    return {m for c in categories for m in core_suite.SUITE[c]}


def all_modules():
    return sorted(name[:-3] for name in os.listdir(TESTS)
                  if name.startswith("test_") and name.endswith(".py"))


def unit_modules():
    named = suite_modules(core() + golden())
    return [m for m in all_modules() if m not in named]


def shards(count):
    sized = sorted(unit_modules(),
                   key=lambda m: (-os.path.getsize(os.path.join(TESTS, m + ".py")), m))
    out = [[] for _ in range(count)]
    weight = [0] * count
    for module in sized:
        i = min(range(count), key=lambda k: (weight[k], k))
        out[i].append(module)
        weight[i] += os.path.getsize(os.path.join(TESTS, module + ".py"))
    return [sorted(s) for s in out]


def check(count):
    problems = []
    placed = {}
    for i, shard in enumerate(shards(count)):
        for module in shard:
            placed.setdefault(module, []).append(f"unit shard {i}")
    for category in core() + golden():
        for module in core_suite.SUITE[category]:
            placed.setdefault(module, []).append(category)
    opt_in = suite_modules(core_suite.OPT_IN)
    for module in all_modules():
        where = placed.get(module, [])
        if not where and module not in opt_in:
            problems.append(f"{module} runs nowhere")
        if len([w for w in where if w.startswith("unit shard")]) > 1:
            problems.append(f"{module} runs in more than one unit shard: {where}")
    for category, modules in core_suite.SUITE.items():
        for module in modules:
            if module not in all_modules():
                problems.append(f"{category} names {module}, which does not exist")
    return problems


def main(argv):
    if argv[:1] == ["units"] and len(argv) == 3:
        print(" ".join(shards(int(argv[2]))[int(argv[1])]))
    elif argv == ["core"]:
        print("\n".join(core()))
    elif argv == ["golden"]:
        print("\n".join(golden()))
    elif argv[:1] == ["check"] and len(argv) == 2:
        problems = check(int(argv[1]))
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
