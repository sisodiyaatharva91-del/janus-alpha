"""
engine_harness.py
-----------------
Shared loader for run_headless_simulation.

WHY THIS FILE EXISTS
    wfo_engine_updated.py runs the entire walk-forward optimisation at import
    time (it reads the parquet at module level), so tests cannot import it.
    Every test instead pulls the function's SOURCE TEXT out of the file and
    exec's it. That is the right call -- it tests the real production function
    rather than a copy that could quietly drift -- but the exec needs a globals
    dict, and three separate files had each hand-written their own:

        ns = {'pd': pd, 'np': np, 'MAX_GAP_LOSS_PCT': 0.03,
              'ASSUMED_WORST_CASE_GAP_PCT': 0.20}

    Hand-listing means the harness silently encodes an assumption about which
    module-level constants the engine happens to reference today. On 2026-08-22
    the idle-yield fix added TRADING_DAYS_PER_YEAR and IDLE_YIELD_PCT and made
    run_headless_simulation reference the first of them, and all three files
    broke at once with

        NameError: name 'TRADING_DAYS_PER_YEAR' is not defined

    including measure_lookahead_bias.py, which is the first thing you are
    supposed to run against the V9 parquet. Worse, the hardcoded 0.03 and 0.20
    were copies of the engine's values, free to disagree with it.

    So: read the constants FROM the engine with ast.literal_eval instead of
    restating them. A future constant is picked up automatically, and a changed
    value cannot diverge from what the engine actually uses.

USE
    from engine_harness import load_engine
    run_sim, ns = load_engine()                       # plain
    run_sim, ns = load_engine(probe=True)             # ns['_PROBE'] collects
                                                      # (date, active_bb) per bar
"""

import ast
import re

import numpy as np
import pandas as pd

ENGINE_FILE = 'wfo_engine_updated.py'

# The engine text between `def run_headless_simulation` and the METRICS banner.
_FN_RE = re.compile(r'^def run_headless_simulation.*?(?=^# =+\n# 3\. METRICS)',
                    re.S | re.M)

_PROBE_ANCHOR = "        equity_curve.append(bb_equity + mr_equity)"
_PROBE_INJECT = (_PROBE_ANCHOR + "\n"
                 "        _PROBE.append((current_date, "
                 "{k: dict(v) for k, v in active_bb.items()}))")


def engine_constants(src):
    """Every module-level `NAME = <literal>` in the engine source.

    ast.literal_eval, not eval: this parses data, and the engine file is a
    local source file, but there is no reason to give it execution rights in a
    test harness. Assignments whose right-hand side is not a literal (computed
    values, function calls) are skipped rather than guessed at -- if the engine
    ever needs one of those in the exec namespace, the NameError will say so
    plainly instead of the harness inventing a value.
    """
    out = {}
    for node in ast.parse(src).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            out[target.id] = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            pass
    return out


def load_engine(probe=False, engine_file=ENGINE_FILE):
    """(run_headless_simulation, namespace) built from the engine's real source.

    Returns the namespace too, so callers can read constants the engine
    actually uses (ns['TRADING_DAYS_PER_YEAR'] and so on) rather than restating
    them. With probe=True, ns['_PROBE'] accumulates (date, active_bb snapshot)
    once per simulated bar.
    """
    src = open(engine_file, encoding='utf-8').read()

    m = _FN_RE.search(src)
    if not m:
        raise RuntimeError(
            f"Could not locate run_headless_simulation in {engine_file}. The "
            f"function or the '# 3. METRICS' banner after it has moved -- fix "
            f"the regex in engine_harness.py rather than working around it, or "
            f"every test that uses this harness is silently testing nothing.")
    body = m.group(0)

    if probe:
        probed = body.replace(_PROBE_ANCHOR, _PROBE_INJECT)
        if probed == body:
            raise RuntimeError(
                "Probe injection failed -- the engine's equity_curve.append "
                "line changed shape. Update _PROBE_ANCHOR in engine_harness.py.")
        body = probed

    ns = engine_constants(src)
    ns.update({'pd': pd, 'np': np, '_PROBE': []})
    exec(compile(body, f'<{engine_file}:run_headless_simulation>', 'exec'), ns)
    return ns['run_headless_simulation'], ns


def engine_line_count(engine_file=ENGINE_FILE):
    """Lines of run_headless_simulation -- some tests print this as a sanity
    check that they loaded the real function and not a stub."""
    src = open(engine_file, encoding='utf-8').read()
    m = _FN_RE.search(src)
    return len(m.group(0).splitlines()) if m else 0


def load_function(name, engine_file=ENGINE_FILE):
    """Extract ONE top-level function from the engine and exec it alone.

    Located by walking the AST rather than by regex, so it does not depend on a
    comment banner sitting after the function -- which is what _FN_RE above
    keys on, and which is fragile in exactly the way its own error message
    admits. Used for calculate_fitness, which lives inside the '# 3. METRICS'
    section that _FN_RE deliberately stops at.

    The function's globals are the engine's module-level literal constants, so
    e.g. calculate_fitness finds W_SORTINO / TRADING_DAYS_PER_YEAR without the
    caller restating them.
    """
    src = open(engine_file, encoding='utf-8').read()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            body = ast.get_source_segment(src, node)
            ns = engine_constants(src)
            ns.update({'pd': pd, 'np': np})
            exec(compile(body, f'<{engine_file}:{name}>', 'exec'), ns)
            return ns[name], ns
    raise RuntimeError(f"No top-level function {name!r} in {engine_file}")


def load_functions(names, engine_file=ENGINE_FILE):
    """Extract SEVERAL top-level functions into ONE shared namespace.

    load_function above gives each function its own globals dict, which breaks
    the moment one of them calls another. measure_lookahead_bias.stage_1b calls
    slots() and bb_frac(), so testing it needs all three co-resident.

    Returns (dict_of_functions, namespace). The namespace also carries the
    file's module-level literal constants, so e.g. MACRO_COLS resolves without
    the caller restating it -- restating is what engine_constants exists to
    avoid.
    """
    src = open(engine_file, encoding='utf-8').read()
    tree = ast.parse(src)
    found = {n.name: ast.get_source_segment(src, n) for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name in set(names)}
    absent = [n for n in names if n not in found]
    if absent:
        raise RuntimeError(f"No top-level function(s) {absent} in {engine_file}")
    ns = engine_constants(src)
    ns.update({'pd': pd, 'np': np})
    for n in names:                       # exec into the SAME ns, so they see
        exec(compile(found[n], f'<{engine_file}:{n}>', 'exec'), ns)   # each other
    return {n: ns[n] for n in names}, ns


if __name__ == '__main__':
    fn, ns = load_engine(probe=True)
    consts = {k: v for k, v in ns.items()
              if k.isupper() and not k.startswith('_')}
    print(f"loaded run_headless_simulation ({engine_line_count()} lines)")
    print(f"constants pulled from {ENGINE_FILE}:")
    for k in sorted(consts):
        print(f"    {k} = {consts[k]!r}")
