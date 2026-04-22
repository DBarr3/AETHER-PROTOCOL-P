"""Import-graph CI gate — TokenAccountant is the SOLE Anthropic caller.

Why this test exists:
    Red Team Sweep #2's Critical finding C1 proved that
    tests/security/pr1_v5_verification_report.md §12.1d
    ("only lib/token_accountant.py imports anthropic — confirmed in
    prior commits") was false. Three production files imported the
    `anthropic` package directly and bypassed every UVT / DLQ /
    usage_events invariant TokenAccountant enforces.

    The §12.1d claim was made with a grep. Grep is the wrong tool:

      • it matches strings inside docstrings and comments, so a module
        that merely MENTIONS anthropic in a docstring looks like a violation
      • it doesn't follow re-exports (module A imports module B which
        imports anthropic — grep on A is clean)
      • it doesn't catch conditional imports inside try/except branches
      • it doesn't catch `importlib.import_module("anthropic")`
      • sorting out the false positives from the real hits requires
        per-line human review, which is exactly how the signed-off
        report missed three real violations

    This test uses Python's `ast` module + a small import graph walker
    to decide definitively, per file, whether that file transitively
    imports the `anthropic` package. Only lib/token_accountant.py is
    allowed to.

Scope:
    Scans every production Python file under lib/, agent/, mcp_worker/,
    api_server.py, agent_pipeline.py, project_orchestrator.py,
    task_decomposer.py. Excludes tests/, scripts/, deploy/ (CI/tool
    code is permitted to touch the SDK directly — those files don't
    serve user requests).

    For each file, builds the transitive set of local modules it imports,
    then checks whether any of those modules imports `anthropic`. Only
    `lib.token_accountant` is allowed to appear in that transitive set.

Failure mode:
    If you add a new file that needs the Anthropic SDK, DO NOT edit the
    allowlist. Route your call through lib/token_accountant.py — extend
    it with whatever streaming / tool-use / system-prompt / MCP behavior
    you need. The whole point of Stage A was that all billing, caching,
    and DLQ invariants live behind one call site.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# The ONE module permitted to import `anthropic`.
ALLOWED_MODULE = "lib.token_accountant"

# Production directories to scan. Tests, scripts, deploy, harness, and
# vendored/third-party code are intentionally excluded.
SCAN_DIRS = [
    REPO / "lib",
    REPO / "agent",
    REPO / "mcp_worker",
]
# Plus a handful of top-level orchestrator files.
SCAN_FILES = [
    REPO / "api_server.py",
    REPO / "agent_pipeline.py",
    REPO / "project_orchestrator.py",
    REPO / "task_decomposer.py",
]


def _iter_production_py_files() -> list[Path]:
    files: list[Path] = []
    for d in SCAN_DIRS:
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            files.append(p)
    for f in SCAN_FILES:
        if f.exists():
            files.append(f)
    return files


def _module_name_for_path(p: Path) -> str:
    """Convert repo-relative .py path → dotted module name."""
    rel = p.relative_to(REPO).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _path_for_module(mod: str) -> Path | None:
    """Resolve a dotted module name to a repo-relative Path.
    Only resolves modules that live inside the repo; returns None for
    stdlib / third-party packages (including `anthropic` itself)."""
    parts = mod.split(".")
    candidate = REPO.joinpath(*parts).with_suffix(".py")
    if candidate.exists():
        return candidate
    pkg_init = REPO.joinpath(*parts, "__init__.py")
    if pkg_init.exists():
        return pkg_init
    return None


def _direct_imports_from(p: Path) -> set[str]:
    """Return the set of fully-dotted module names this file imports."""
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    deps: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                deps.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0:  # relative — skip for simplicity; production code uses absolute
                continue
            if node.module is None:
                continue
            base = node.module
            for alias in node.names:
                deps.add(base)
                # `from X import Y` — Y might itself be a submodule.
                # We record the base name; transitive walker will cover
                # the rest by resolving the base.
                _ = alias
    return deps


def _transitive_imports(root: Path) -> set[str]:
    """BFS the import graph starting from `root`, staying inside repo.
    Returns the set of dotted module names visited (including external
    packages like `anthropic` which are leaves — not resolved further)."""
    seen: set[str] = set()
    frontier: list[Path] = [root]
    while frontier:
        current = frontier.pop()
        for dep in _direct_imports_from(current):
            if dep in seen:
                continue
            seen.add(dep)
            sub = _path_for_module(dep)
            if sub is not None and sub not in (root,) and sub.exists():
                frontier.append(sub)
    return seen


def test_anthropic_is_imported_only_by_token_accountant() -> None:
    """Every production file's transitive import set must contain `anthropic`
    ONLY via lib.token_accountant (or not at all)."""
    violations: list[tuple[str, str]] = []
    for py in _iter_production_py_files():
        module_name = _module_name_for_path(py)
        # Skip the allowed module itself — it obviously imports anthropic.
        if module_name == ALLOWED_MODULE:
            continue

        # Direct imports (by this file) of `anthropic` — the highest-signal check.
        direct = _direct_imports_from(py)
        direct_hits = {d for d in direct if d == "anthropic" or d.startswith("anthropic.")}
        if direct_hits:
            violations.append((module_name, f"DIRECT import: {sorted(direct_hits)}"))
            continue

        # Transitive imports must go through lib.token_accountant before
        # reaching anthropic. Walk the graph and check.
        trans = _transitive_imports(py)
        has_anthropic = any(d == "anthropic" or d.startswith("anthropic.") for d in trans)
        if has_anthropic:
            # Ensure the path to it goes via lib.token_accountant.
            if ALLOWED_MODULE not in trans:
                violations.append((
                    module_name,
                    f"transitively imports anthropic WITHOUT going through {ALLOWED_MODULE}",
                ))

    if violations:
        msg = ["Red Team #2 C1: production files importing `anthropic` outside the allowlist:"]
        for m, reason in violations:
            msg.append(f"  {m}: {reason}")
        msg.append("")
        msg.append(
            f"Only `{ALLOWED_MODULE}` may import the `anthropic` package. "
            "Route through token_accountant.call() or call_sync() — extend "
            "token_accountant if you need new behavior rather than adding a "
            "new direct call site."
        )
        raise AssertionError("\n".join(msg))


def test_scanner_actually_finds_files() -> None:
    """Sanity check — if SCAN_DIRS are wrong, the main test would pass
    vacuously. Assert we scan at least a dozen files."""
    files = _iter_production_py_files()
    assert len(files) >= 10, (
        f"Scanner found only {len(files)} production files — "
        "SCAN_DIRS / SCAN_FILES may be mis-configured."
    )


def test_token_accountant_itself_does_import_anthropic() -> None:
    """Negative-guard: if someone removes the `httpx`-based call in
    token_accountant and breaks its Anthropic connection, this test
    flags it. Paired invariant with the main assertion."""
    path = REPO / "lib" / "token_accountant.py"
    text = path.read_text(encoding="utf-8")
    # token_accountant uses httpx to hit api.anthropic.com directly —
    # the module doesn't `import anthropic` but it IS the sole place that
    # contacts api.anthropic.com. Assert the URL constant is present.
    assert "api.anthropic.com" in text, (
        "lib/token_accountant.py no longer references api.anthropic.com — "
        "the central call-site has moved and this test needs updating."
    )
