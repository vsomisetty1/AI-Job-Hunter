"""Architecture rules: imports only point down the layer stack, and no cycles.

Layers (a package may import its own layer or any lower one):

    0  utils, schemas, models          plain data and helpers
    1  core                            config, errors, logging, database, security
    2  documents, storage, llm, parsing, connectors, automation
                                       infrastructure adapters (files, Claude,
                                       job boards, browser automation)
    3  repositories                    queries
    4  agents                          parsing/LLM workers (+ agent_runs recording)
    5  services, learning              business logic, units of work
    6  scheduler                       background and scheduled jobs
    7  routers, dependencies           HTTP layer and dependency injection
    8  bootstrap, main, __main__       composition root
"""

import ast
from collections import defaultdict

from tests.conftest import BACKEND_DIR

LAYERS = {
    "utils": 0, "schemas": 0, "models": 0,
    "core": 1,
    "documents": 2, "storage": 2, "llm": 2, "parsing": 2, "connectors": 2, "automation": 2,
    "repositories": 3,
    "agents": 4,
    "services": 5, "learning": 5,
    "scheduler": 6,
    "routers": 7, "dependencies": 7,
    "bootstrap": 8, "main": 8, "__main__": 8,
}  # fmt: skip

APP = BACKEND_DIR / "app"


def _package(module: str) -> str:
    return module.split(".")[1]


def _imports() -> dict[str, set[str]]:
    """module -> app modules it imports (anywhere in the file)."""
    graph: dict[str, set[str]] = {}
    for path in APP.rglob("*.py"):
        rel = path.relative_to(BACKEND_DIR).with_suffix("")
        module = ".".join(rel.parts).removesuffix(".__init__")
        if module == "app":
            continue
        targets = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app."):
                targets.add(node.module)
            elif isinstance(node, ast.Import):
                targets |= {a.name for a in node.names if a.name.startswith("app.")}
        graph[module] = targets
    return graph


def test_every_package_has_a_layer():
    packages = {p.name for p in APP.iterdir() if p.is_dir() and not p.name.startswith("__")}
    modules = {p.stem for p in APP.glob("*.py") if p.stem != "__init__"}
    assert packages | modules <= set(LAYERS), sorted((packages | modules) - set(LAYERS))


def test_imports_only_point_down():
    violations = []
    for module, targets in _imports().items():
        src = _package(module)
        for target in targets:
            dst = _package(target)
            if LAYERS[dst] > LAYERS[src]:
                violations.append(
                    f"{module} -> {target} ({src}:{LAYERS[src]} -> {dst}:{LAYERS[dst]})"
                )
    assert not violations, "\n".join(sorted(violations))


def test_no_package_cycles():
    edges: dict[str, set[str]] = defaultdict(set)
    for module, targets in _imports().items():
        for target in targets:
            if _package(module) != _package(target):
                edges[_package(module)].add(_package(target))

    def reaches(start: str, goal: str, seen: set[str]) -> bool:
        for nxt in edges[start]:
            if nxt == goal or (nxt not in seen and reaches(nxt, goal, seen | {nxt})):
                return True
        return False

    cycles = sorted(p for p in list(edges) if reaches(p, p, {p}))
    assert not cycles, f"packages in an import cycle: {cycles}"


def test_every_module_imports_cleanly():
    """Each module imports on its own (catches broken and order-dependent imports)."""
    import importlib

    for path in sorted(APP.rglob("*.py")):
        module = ".".join(path.relative_to(BACKEND_DIR).with_suffix("").parts)
        importlib.import_module(module.removesuffix(".__init__"))
