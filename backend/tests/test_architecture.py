"""The engineering guidelines' structural rules, checked on every build."""
import ast
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent
CONTEXTS = ROOT / "contexts"
NAMES = sorted(p.name for p in CONTEXTS.iterdir() if p.is_dir() and (p / "__init__.py").exists())
BUSINESS = [n for n in NAMES if n != "shared_kernel"]


def module_name(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def imports(path: Path) -> set[str]:
    """Absolute names of every module a file imports, relative imports resolved."""
    package = module_name(path).split(".")
    if path.name != "__init__.py":
        package = package[:-1]
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            mod = ".".join(base + ([node.module] if node.module else []))
            found.add(mod)
            found |= {f"{mod}.{a.name}" for a in node.names}  # "from . import x" may name a module
    return found


def source_files(under: Path, *, include_tests=False):
    for path in under.rglob("*.py"):
        parts = path.relative_to(ROOT).parts
        if "migrations" in parts or (not include_tests and "tests" in parts):
            continue
        yield path


class ContextBoundaryTests(SimpleTestCase):
    def test_contexts_use_each_other_only_through_public_surfaces(self):
        problems = []
        for ctx in NAMES:
            for path in source_files(CONTEXTS / ctx):
                for name in imports(path):
                    parts = name.split(".")
                    if parts[0] != "contexts" or len(parts) < 2 or parts[1] in (ctx, "shared_kernel"):
                        continue
                    if len(parts) < 3 or parts[2] not in ("public", "contract"):
                        problems.append(f"{path.relative_to(ROOT)} imports {name}")
        self.assertEqual(problems, [])

    def test_domain_and_contract_code_is_pure_python(self):
        """Rule 7: the domain depends on no framework, database or provider."""
        problems = []
        for ctx in NAMES:
            pure = [p for p in source_files(CONTEXTS / ctx)
                    if "domain" in p.relative_to(CONTEXTS / ctx).parts or p.name == "contract.py"
                    or ctx == "shared_kernel"]
            for path in pure:
                for name in imports(path):
                    parts = name.split(".")
                    if parts[0] in ("django", "psycopg", "simulators", "persistence", "config"):
                        problems.append(f"{path.relative_to(ROOT)} imports {name}")
                    elif parts[0] == "contexts" and len(parts) > 2:
                        own = parts[1] == ctx
                        ok = parts[1] == "shared_kernel" or (own and parts[2] in ("domain", "contract")) or (
                            not own and parts[2] == "contract")
                        if not ok:
                            problems.append(f"{path.relative_to(ROOT)} imports {name}")
        self.assertEqual(problems, [])

    def test_no_context_imports_a_simulator(self):
        offenders = [str(p.relative_to(ROOT)) for p in source_files(CONTEXTS)
                     if any(n.startswith("simulators") for n in imports(p))]
        self.assertEqual(offenders, [])


class ContextShapeTests(SimpleTestCase):
    def test_every_context_states_what_it_owns_and_exposes_a_public_surface(self):
        for ctx in BUSINESS:
            doc = ast.get_docstring(ast.parse((CONTEXTS / ctx / "__init__.py").read_text())) or ""
            self.assertIn("Owns:", doc, ctx)
            self.assertIn("Does not own:", doc, ctx)
            self.assertTrue((CONTEXTS / ctx / "public.py").exists(), ctx)

    def test_no_dumping_ground_modules(self):
        """Rules 37 and 39."""
        banned = {"utils.py", "helpers.py", "common.py", "misc.py", "services.py"}
        self.assertEqual([str(p.relative_to(ROOT)) for p in source_files(ROOT, include_tests=True)
                          if p.name in banned and ".venv" not in p.parts], [])

    def test_modules_stay_small(self):
        """Rule 40: a file has one reason to exist."""
        big = [f"{p.relative_to(ROOT)} ({n} lines)" for p in source_files(CONTEXTS)
               if (n := len(p.read_text().splitlines())) > 250]
        self.assertEqual(big, [])

    def test_no_mutable_money_counters(self):
        """Balances are derived from the journal, never kept in a column."""
        import re
        shape = re.compile(r"\w*(amount|balance|total|paid|shares)\w*\s*=\s*F\(", re.I)
        found = [f"{p.relative_to(ROOT)}: {line.strip()}" for p in source_files(CONTEXTS)
                 for line in p.read_text().splitlines() if shape.search(line)]
        self.assertEqual(found, [])

    def test_every_adr_is_indexed(self):
        adr_dir = ROOT.parent / "docs" / "adr"
        index = (adr_dir / "README.md").read_text()
        missing = [p.name for p in adr_dir.glob("[0-9]*.md") if p.name not in index]
        self.assertEqual(missing, [])

    def test_no_business_workflows_in_signals(self):
        """Rule 14."""
        users = [str(p.relative_to(ROOT)) for p in source_files(CONTEXTS)
                 if any(n.startswith("django.db.models.signals") or n.startswith("django.dispatch")
                        for n in imports(p))]
        self.assertEqual(users, [])
