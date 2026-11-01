"""Type-annotation coverage gate for the drivers public API (issue #31).

Walks every module named in issue #31's gap table (plus the extra modules
behind ``tollgate_lab.drivers.__all__``: android_adb, labgrid_router,
playwright_browser) and asserts that every function/method — public or
private, including nested defs — has a return annotation and annotated
parameters (``self``/``cls`` exempt).

``EXPECTED_GAPS`` records the only tolerated gaps, each with a reason; the
gate fails if a gap is fixed (stale entry) or if any other def regresses.
"""

import ast
import inspect
from pathlib import Path

import tollgate_lab.drivers

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Modules from the issue #31 table + the drivers/__all__ surface modules.
MODULES = [
    "tollgate_lab/drivers/ssh.py",
    "tollgate_lab/fixtures/sessions.py",
    "tollgate_lab/drivers/esp_flash.py",
    "tollgate_lab/reporting/nostr_events.py",
    "tollgate_lab/drivers/fipsctl.py",
    "tollgate_lab/drivers/fips_service.py",
    "tollgate_lab/drivers/serial_console.py",
    "tollgate_lab/deploy/ci_artifact.py",
    "tollgate_lab/drivers/router.py",
    "tollgate_lab/hardware/lock.py",
    "tollgate_lab/drivers/android_adb.py",
    "tollgate_lab/drivers/labgrid_router.py",
    "tollgate_lab/drivers/playwright_browser.py",
]

# Documented, tolerated gaps. Everything else must be fully annotated.
EXPECTED_GAPS = {
    ("tollgate_lab/fixtures/sessions.py", "router_session"): (
        "imports SSHClient from drivers.ssh, which does not exist — fixture is"
        " latently broken (ImportError on use); a correct annotation requires"
        " restoring SSHClient (runtime change, out of annotation-only scope)"
    ),
    ("tollgate_lab/fixtures/sessions.py", "fips_daemon"): (
        "takes the broken router_session fixture; same SSHClient blocker"
    ),
    ("tollgate_lab/fixtures/sessions.py", "hardware_lock"): (
        "imports HardwareLock from hardware.lock, which does not exist (the"
        " module exposes a function API: acquire/release_hardware_lock) —"
        " fixture is latently broken; fixing it is a runtime change, out of"
        " annotation-only scope"
    ),
}


def _param_issues(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    issues = []
    args = fn.args
    positional = list(args.posonlyargs) + list(args.args)
    for i, arg in enumerate(positional):
        if i == 0 and arg.arg in ("self", "cls"):
            continue
        if arg.annotation is None:
            issues.append(f"param {arg.arg}")
    for arg in (args.vararg, args.kwarg):
        if arg is not None and arg.annotation is None:
            issues.append(f"param {arg.arg}")
    for arg in args.kwonlyargs:
        if arg.annotation is None:
            issues.append(f"param {arg.arg}")
    if fn.returns is None:
        issues.append("return")
    return issues


def _collect_gaps(node: ast.AST, scope: str, module: str, gaps: dict[str, str]) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualname = f"{scope}.{child.name}" if scope else child.name
            issues = _param_issues(child)
            if issues:
                gaps[qualname] = ", ".join(issues)
            _collect_gaps(child, qualname, module, gaps)
        elif isinstance(child, ast.ClassDef):
            _collect_gaps(child, f"{scope}.{child.name}" if scope else child.name, module, gaps)


def _module_gaps(module: str) -> dict[str, str]:
    tree = ast.parse((_REPO_ROOT / module).read_text(), filename=module)
    gaps: dict[str, str] = {}
    _collect_gaps(tree, "", module, gaps)
    return gaps


def test_issue31_modules_fully_annotated():
    """Every def in the issue #31 table modules is annotated (or a documented gap)."""
    for module in MODULES:
        unexpected = {
            qualname: issues
            for qualname, issues in _module_gaps(module).items()
            if (module, qualname) not in EXPECTED_GAPS
        }
        assert not unexpected, f"{module}: unannotated defs -> {unexpected}"


def test_expected_gaps_still_apply():
    """Every EXPECTED_GAPS entry is still unannotated — remove fixed entries."""
    for module, qualname in EXPECTED_GAPS:
        gaps = _module_gaps(module)
        assert qualname in gaps, (
            f"{module}:{qualname} is now annotated — remove the stale EXPECTED_GAPS entry"
        )


def test_drivers_public_surface_annotated():
    """Every public method/property of each drivers.__all__ class is annotated."""
    for name in tollgate_lab.drivers.__all__:
        obj = getattr(tollgate_lab.drivers, name)
        assert inspect.isclass(obj), f"drivers.__all__ entry {name!r} is not a class"
        for attr_name, member in vars(obj).items():
            if attr_name.startswith("_"):
                continue
            if isinstance(member, property):
                member = member.fget
                if member is None:
                    continue
            if not inspect.isfunction(member):
                continue
            _assert_annotated(f"{name}.{attr_name}", member)


def _assert_annotated(where: str, func) -> None:
    sig = inspect.signature(func)
    assert sig.return_annotation is not inspect.Signature.empty, f"{where}: missing return type"
    params = [
        p.name
        for p in sig.parameters.values()
        if p.name not in ("self", "cls")
        and p.kind not in (p.kind.VAR_POSITIONAL, p.kind.VAR_KEYWORD)
        and p.annotation is inspect.Signature.empty
    ]
    assert not params, f"{where}: unannotated params {params}"


def test_drivers_all_importable():
    """The drivers.__all__ surface resolves to live objects."""
    for name in tollgate_lab.drivers.__all__:
        assert hasattr(tollgate_lab.drivers, name), f"drivers.__all__ entry {name!r} missing"
