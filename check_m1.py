
import ast
import csv
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

ok = True
passed = 0
failed = 0


def check(name, condition, detail=""):
    global ok, passed, failed

    if condition:
        print(f"PASS  {name}")
        passed += 1
    else:
        print(f"FAIL  {name}" + (f" [{detail}]" if detail else ""))
        failed += 1
        ok = False


def read_file(path):
    path = ROOT / path

    if not path.exists():
        return ""

    return path.read_text(encoding="utf-8", errors="ignore")


def read_csv(path):
    path = ROOT / path

    if not path.exists():
        return []

    try:
        with path.open("r", encoding="utf-8", newline="") as file:
            return list(csv.DictReader(file))
    except (OSError, csv.Error):
        return []


def get_functions(path):
    source = read_file(path)

    if not source:
        return set()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def uses_self_attribute(path, attribute):
    source = read_file(path)

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    return any(
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr == attribute
        for node in ast.walk(tree)
    )


def has_method_call(path, method_name):
    source = read_file(path)

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == method_name
        for node in ast.walk(tree)
    )


def valid_number(row, column):
    try:
        return float(row[column])
    except (KeyError, TypeError, ValueError):
        return None


print("\n========== AEROCORE M1 VERIFICATION ==========\n")


# -------------------------------------------------
# 1. ROW STORE
# -------------------------------------------------

row_store = read_file("aerocore/storage/row_store.py")

check(
    "RowStore source exists",
    bool(row_store),
)

check(
    "RowStore does not use self._records",
    not uses_self_attribute("aerocore/storage/row_store.py", "_records"),
)


# -------------------------------------------------
# 2. COLUMN STORE PERSISTENCE
# -------------------------------------------------

column_store = read_file("aerocore/storage/column_store.py")
column_functions = get_functions("aerocore/storage/column_store.py")

check(
    "ColumnStore source exists",
    bool(column_store),
)

check(
    "ColumnStore has a _rebuild method",
    "_rebuild" in column_functions,
)

check(
    "ColumnStore calls _rebuild during initialization",
    has_method_call("aerocore/storage/column_store.py", "_rebuild"),
)

check(
    "ColumnStore can read records during rebuilding",
    "get_record" in column_store,
)


# -------------------------------------------------
# 3. BENCHMARK VALIDATION
# -------------------------------------------------

policy = read_csv("results/m1/policy_results.csv")

check(
    "Policy benchmark CSV exists and has data",
    len(policy) > 0,
)

if policy:
    required_policy_columns = {
        "workload",
        "policy",
        "pool_fraction",
        "accesses",
        "table_pages",
        "evictions",
    }

    policy_columns = set(policy[0].keys())

    check(
        "Policy benchmark has required columns",
        required_policy_columns <= policy_columns,
        str(required_policy_columns - policy_columns),
    )

    if required_policy_columns <= policy_columns:
        check(
            "Policy benchmark has at least 3 workloads",
            len({r["workload"] for r in policy}) >= 3,
        )

        check(
            "Policy benchmark compares at least 2 policies",
            len({r["policy"] for r in policy}) >= 2,
        )

        check(
            "Policy benchmark uses at least 3 pool sizes",
            len({r["pool_fraction"] for r in policy}) >= 3,
        )

        valid_accesses = all(
            valid_number(r, "accesses") is not None
            and valid_number(r, "table_pages") is not None
            and valid_number(r, "accesses") >= 3 * valid_number(r, "table_pages")
            and valid_number(r, "table_pages") > 0
            for r in policy
        )

        check(
            "Every policy workload has sufficient accesses",
            valid_accesses,
        )

        evictions = [
            valid_number(r, "evictions")
            for r in policy
        ]

        check(
            "Policy benchmark produces evictions",
            all(v is not None for v in evictions)
            and any(v > 0 for v in evictions),
        )


layout = read_csv("results/m1/layout_results.csv")

check(
    "Layout benchmark CSV exists and has data",
    len(layout) > 0,
)

if layout:
    required_layout_columns = {"operation", "table_pages"}

    layout_columns = set(layout[0].keys())

    check(
        "Layout benchmark has required columns",
        required_layout_columns <= layout_columns,
        str(required_layout_columns - layout_columns),
    )

    if required_layout_columns <= layout_columns:
        operations = {r["operation"] for r in layout}

        required_operations = {
            "avg_age",
            "full_scan",
            "point_lookup_1000",
        }

        check(
            "Layout benchmark includes row-friendly and column-friendly operations",
            required_operations <= operations,
            ", ".join(sorted(operations)),
        )

        page_counts = [
            valid_number(r, "table_pages")
            for r in layout
        ]

        check(
            "Layout benchmark uses tables larger than the 16-frame pool",
            all(v is not None and v > 16 for v in page_counts),
        )


# Environment information
environment_path = ROOT / "results/m1/environment.json"

environment_valid = False

if environment_path.exists():
    try:
        environment = json.loads(
            environment_path.read_text(encoding="utf-8")
        )
        environment_valid = isinstance(environment, dict) and bool(environment)
    except (OSError, json.JSONDecodeError):
        environment_valid = False

check(
    "environment.json exists and contains valid JSON information",
    environment_valid,
)


# -------------------------------------------------
# 4. EMPTY FILE VALIDATION
# -------------------------------------------------

empty_files = []

for folder in ("docs", "aerocore", "benchmarks", "tests"):
    directory = ROOT / folder

    if not directory.exists():
        continue

    for path in directory.rglob("*"):
        if (
            path.is_file()
            and path.stat().st_size == 0
            and path.name != "__init__.py"
            and "__pycache__" not in path.parts
        ):
            empty_files.append(str(path.relative_to(ROOT)))


check(
    "No empty files in docs, aerocore, benchmarks, or tests",
    not empty_files,
    ", ".join(empty_files),
)


# -------------------------------------------------
# 5. README VALIDATION
# -------------------------------------------------

readme = read_file("README.md")

check(
    "README exists",
    bool(readme),
)

if readme:
    check(
        "README does not mention NumPy",
        "numpy" not in readme.lower(),
    )

    check(
        "README does not claim a Table API layer",
        "table api" not in readme.lower(),
    )

    python_version_found = re.search(
        r"Python\s+\d+\.\d+",
        readme,
        re.IGNORECASE,
    ) is not None

    check(
        "README states a Python version",
        python_version_found,
    )


# -------------------------------------------------
# 6. REQUIRED AUTOMATED TESTS
# -------------------------------------------------

test_file = ROOT / "tests/test_storage_extra.py"

test_functions = get_functions("tests/test_storage_extra.py")

check(
    "Additional storage test file exists",
    test_file.exists(),
)

required_tests = {
    "ColumnStore restart": "column_store_survives_restart",
    "RowStore restart": "row_store_survives_restart",
    "Delete and slot reuse": "delete_update_and_slot_reuse",
    "Update": "delete_update_and_slot_reuse",
    "Oversized record": "larger_than_a_page",
}

for label, function_name in required_tests.items():
    check(
        f"Automated test exists: {label}",
        function_name in test_functions,
    )


# -------------------------------------------------
# FINAL RESULT
# -------------------------------------------------

print("\n==============================================")
print(f"PASSED: {passed}")
print(f"FAILED: {failed}")
print("==============================================")

if ok:
    print("\nALL CHECKS PASSED")
    sys.exit(0)
else:
    print("\nSOME CHECKS FAILED")
    sys.exit(1)
