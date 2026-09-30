"""Module boundaries, checked on every build. The ledger must stay a small,
auditable core that knows nothing about groups, banks or people."""
import ast
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent
FIRST_PARTY = {"wepl", "platform_core", "parties", "ledger", "governance", "connectivity", "simulator", "tests"}
ALLOWED = {
    "platform_core": {"wepl"},
    "parties": {"platform_core", "wepl"},
    "ledger": {"platform_core", "wepl"},
    "governance": {"parties", "platform_core", "wepl"},
    "connectivity": {"governance", "ledger", "parties", "platform_core", "wepl"},
    # Test-and-demo only: it plays the bank and drives the demo, so it may use
    # anything, but nothing may import it (see below).
    "simulator": FIRST_PARTY - {"tests"},
}


def imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found & FIRST_PARTY


class ArchitectureTests(SimpleTestCase):
    def test_modules_only_import_what_they_are_allowed_to(self):
        problems = []
        for module, allowed in ALLOWED.items():
            for path in (ROOT / module).rglob("*.py"):
                if "migrations" in path.parts:
                    continue
                for name in imports(path) - allowed - {module}:
                    problems.append(f"{path.relative_to(ROOT)} imports {name}")
        self.assertEqual(problems, [])

    def test_production_code_never_imports_the_simulator(self):
        offenders = []
        for module in ALLOWED:
            if module == "simulator":
                continue
            for path in (ROOT / module).rglob("*.py"):
                if "simulator" in imports(path) and "management" not in path.parts:
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_only_the_ledger_service_writes_journal_rows(self):
        offenders = []
        for path in ROOT.rglob("*.py"):
            rel = path.relative_to(ROOT)
            if rel.parts[0] in {".venv", "tests"} or "migrations" in rel.parts or rel == Path("ledger/services.py"):
                continue
            text = path.read_text()
            if "JournalLine.objects.create" in text or "JournalEntry.objects.create" in text:
                offenders.append(str(rel))
        self.assertEqual(offenders, [])
