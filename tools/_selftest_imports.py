#!/usr/bin/env python
"""Verify every local module the runtime chain imports is actually importable.

Why this exists: on 2026-07-20 a repo reorganisation moved `racing_line.py` and
`winshot.py` out of the root. The follower crashed on the first (loud, found in
minutes). The second was imported inside a try/except that set `grab_window = None`,
so it failed SILENTLY -- every OCR guard in afk_recover then evaluated against an
empty string and never fired, and recovery navigated FH6's menus blind for hours,
eventually swapping the car out from under a calibrated bot.

The check that missed it used `grep -E "^(from|import) ..."`, which only matches
imports at column 0. Both of the dangerous ones were INDENTED inside try blocks.
This uses the AST, so indentation and try/except cannot hide anything.

Run from the repo root:  python tools/_selftest_imports.py
"""
import ast
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RUNTIME = ["follow.py", "afk_recover.py", "local_planner.py", "track_features.py",
           "vtrim_net.py", "residual_net.py", "fh6_telemetry.py", "press_enter.py",
           "racing_line.py", "winshot.py"]


def local_imports(path):
    """Every top-level module name imported by `path`, at ANY indentation."""
    out = []
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append((a.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                out.append((node.module.split(".")[0], node.lineno))
    return out


def swallowed_imports(path):
    """Imports wrapped in try/except -- these fail SILENTLY, so they need extra care."""
    out = []
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Import):
                    out += [(a.name.split(".")[0], sub.lineno) for a in sub.names]
                elif isinstance(sub, ast.ImportFrom) and sub.module:
                    out.append((sub.module.split(".")[0], sub.lineno))
    return out


def main():
    fails, swallowed = [], []
    for fn in RUNTIME:
        p = os.path.join(ROOT, fn)
        if not os.path.exists(p):
            fails.append(f"{fn}: MISSING from the repo root")
            continue
        sw = {n for n, _ in swallowed_imports(p)}
        for mod, line in local_imports(p):
            if importlib.util.find_spec(mod) is not None:
                continue
            where = ""
            for sub in ("attic", "tools"):
                if os.path.exists(os.path.join(ROOT, sub, mod + ".py")):
                    where = f"  (found in {sub}/ -- moved out of the root?)"
            tag = "SILENT" if mod in sw else "loud "
            fails.append(f"{fn}:{line} [{tag}] cannot import {mod!r}{where}")
            if mod in sw:
                swallowed.append(mod)

    print("=" * 70)
    if fails:
        print("BROKEN IMPORTS:")
        for f in fails:
            print("  " + f)
        if swallowed:
            print("\n  The [SILENT] ones are the dangerous class: wrapped in try/except, so the")
            print("  program keeps running with the feature invisibly disabled.")
        print("=" * 70)
        return 1
    print("OK  every local import in the runtime chain resolves")

    # The recovery stack specifically must be able to SEE, not merely import.
    try:
        import afk_recover as A
        if not A.ocr_available():
            print("WARN  afk_recover imported but ocr_available() is False -- recovery would")
            print("      run blind. Menu navigation self-disables, but fix the OCR stack.")
            print("=" * 70)
            return 1
        print("OK  afk_recover.ocr_available() -- the recovery stack can see")
    except Exception as e:
        print(f"WARN  could not check afk_recover: {e}")
        print("=" * 70)
        return 1
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
