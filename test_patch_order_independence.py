"""
test_patch_order_independence.py -- proves the two patch scripts compose in
either order WITHOUT any fix silently going missing.

WHY THIS TEST EXISTS
    On 2026-08-22, applying apply_fixes_v2.py --idle-yield before
    apply_fixes.py --fix5 caused fix5 to print

        fix5: already applied, skipping.

    and do nothing. The CAGR annualization units bug survived. The cause was
    fix5 guarding itself with `if 'TRADING_DAYS_PER_YEAR' in src`, a token that
    v2's --idle-yield legitimately writes into the same file. So a sentinel
    meant to say "I already did my work" actually said "somebody else used my
    variable name".

    That failure mode is nasty for three reasons:
      1. It is SILENT and the message is reassuring rather than alarming.
      2. fix5 feeds parameter SELECTION (inflated CAGR saturates the Sortino
         cap in calculate_fitness), so the damage is not a cosmetic printed
         number -- a re-run would pick different parameters.
      3. It is ORDER-DEPENDENT, so testing one order proves nothing about the
         other. The original verification ran both orders and declared success
         because neither crashed; nothing checked that the fixes were actually
         THERE afterwards.

WHAT THIS TEST CHECKS
    Not byte-equality -- the two orders legitimately differ in cosmetic ways
    (docstring paragraph position, parameter position in a signature). It
    checks the thing that actually matters: after both scripts have run, in
    EITHER order, every fix's fingerprint is present and every removed bug's
    fingerprint is gone. Plus both trees import-compile.

RUN
    python test_patch_order_independence.py
    python test_patch_order_independence.py --dir /path/to/janus-alpha
"""

import argparse
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile

ap = argparse.ArgumentParser()
ap.add_argument('--dir', default='.', help='directory holding the scripts and sources')
args = ap.parse_args()

SRC = os.path.abspath(args.dir)
V1 = os.path.join(SRC, 'apply_fixes.py')
V2 = os.path.join(SRC, 'apply_fixes_v2.py')

# The four files both scripts touch. coiled_alpha_logic.py.orig is the
# pre-patch original; if it exists we start from it so the test is meaningful
# on a tree where fixes were already applied by hand.
FILES = ['coiled_alpha_logic.py', 'data_prep_updated.py',
         'live_pipeline.py', 'wfo_engine_updated.py', 'generate_live_params.py']

V1_FLAGS = ['--fix1', '--fix3', '--fix5']
V2_FLAGS = ['--macro-lag', '--idle-yield', '--run-guard', '--sheets', '--live-params']

# (file, must_contain, human label) -- one fingerprint per fix.
MUST_CONTAIN = [
    ('coiled_alpha_logic.py', 'DECISION TIMING (see section 5b)', 'fix1  Sniper decision lag'),
    ('coiled_alpha_logic.py', 'def compute_macro_regime(',        'macro-lag  shared macro impl'),
    ('coiled_alpha_logic.py', 'Market_Breadth_Today',             'macro-lag  breadth lag (7b)'),
    ('live_pipeline.py',      'def rebalance_allocation(',        'fix3  rebalance ordering'),
    ('live_pipeline.py',      'compute_macro_regime',             'macro-lag  live uses shared impl'),
    ('live_pipeline.py',      'def accrue_idle_yield(',           'idle-yield  live accrual'),
    ('live_pipeline.py',      'def trading_days_since(',          'idle-yield  live day count'),
    ('live_pipeline.py',      'def is_new_trading_date(',         'run-guard  duplicate-run guard'),
    ('live_pipeline.py',      'def build_sheet_payloads(',        'sheets  payload builder'),
    ('live_pipeline.py',      'Trade_Log',                        'sheets  trade log tab'),
    ('wfo_engine_updated.py', 'UNITS FIX 2026-08-22',             'fix5  CAGR annualization units'),
    ('wfo_engine_updated.py', 'IDLE_YIELD_PCT',                   'idle-yield  engine constant'),
    ('wfo_engine_updated.py', 'MACRO GATES ARRIVE PRE-LAGGED',    'macro-lag  engine warning note'),
    ('data_prep_updated.py',  'compute_macro_regime',             'macro-lag  data_prep uses shared impl'),
    ('generate_live_params.py', 'COPY PARITY FIX 2026-08-22',     'live-params  finding #34 sentinel'),
    ('generate_live_params.py', 'A COPY of wfo_engine_updated.run_headless',
                                                                  'live-params  honest docstring'),
]

# (file, must_NOT_contain, human label) -- the bug each fix removed. These are
# the assertions that catch a silent skip; MUST_CONTAIN alone can be satisfied
# by a comment while the buggy line is still live.
MUST_NOT_CONTAIN = [
    ('wfo_engine_updated.py', '(365.25 / days)',                  'fix5  old 365.25-day annualization'),
    ('wfo_engine_updated.py', "/ 100) / 365\n",                   'idle-yield  old /365 daily rate'),
    ('wfo_engine_updated.py', "'idle_yield': 6.0,",               'idle-yield  old 6% default'),
    ('live_pipeline.py',      "macro['VIX_Spike'] = False",        'macro-lag  hardcoded VIX_Spike'),
    # finding #34 -- the same two units bugs, in the copy that writes the LIVE
    # config. Note the needle for the docstring is the ORIGINAL's first line,
    # not the phrase 'kept in sync manually' on its own: the replacement
    # docstring quotes that phrase while explaining that it was false, so the
    # short needle would match the fixed file and this check would never fail.
    # Same class of mistake as the fix5 sentinel collision -- a needle has to be
    # unique to the thing it is looking for.
    ('generate_live_params.py', "/ 100) / 365\n",                  'live-params  old /365 daily rate'),
    ('generate_live_params.py', '(365.25 / days)',                 'live-params  old CAGR annualization'),
    ('generate_live_params.py', "'idle_yield': 6.0,",              'live-params  old 6% default'),
    ('generate_live_params.py',
     '"""Identical logic to wfo_engine_updated.py -- kept in sync manually.',
                                                                   'live-params  false sync claim'),
    ('generate_live_params.py', "* 0.03) / (row['OPEN'] * 0.20",   'live-params  unnamed gap constants'),
]


def preflight():
    """Refuse to run against an ALREADY-PATCHED tree.

    This test works by applying the patches to a pristine copy in both orders.
    If --dir points at a tree whose sources are already patched (and has no
    .orig copies to fall back on), every flag legitimately reports "already
    applied" -- and the sentinel-collision detector below then flags all twelve
    of them as collisions. The diagnosis is completely misleading: nothing is
    wrong with the sentinels, the input was just wrong.

    Encountered 2026-08-22 while running the suite against a fully-patched
    verification tree. Fail early with the real reason instead.
    """
    prepatched = []
    for f, needle, label in MUST_CONTAIN:
        if os.path.exists(os.path.join(SRC, f + '.orig')):
            continue          # a pristine fallback exists, so this is fine
        p = os.path.join(SRC, f)
        if os.path.exists(p) and needle in open(p, encoding='utf-8').read():
            prepatched.append((f, label))
    if prepatched:
        print(f"ERROR: the sources in {SRC} are ALREADY PATCHED, so applying the")
        print("patches to them proves nothing. Found, for example:")
        for f, label in prepatched[:4]:
            print(f"    {f}  already contains  {label}")
        if len(prepatched) > 4:
            print(f"    ... and {len(prepatched) - 4} more")
        print()
        print("Point --dir at a PRISTINE checkout, or place pre-patch copies")
        print("alongside them as <filename>.orig -- build_tree() prefers those.")
        sys.exit(2)


def build_tree(dest):
    os.makedirs(dest, exist_ok=True)
    for f in FILES:
        orig = os.path.join(SRC, f + '.orig')
        src = orig if os.path.exists(orig) else os.path.join(SRC, f)
        if not os.path.exists(src):
            sys.exit(f"ERROR: {src} not found. Use --dir to point at the repo.")
        shutil.copy(src, os.path.join(dest, f))
    # copies inherit read-only mode from the uploads mount; make them writable
    for f in FILES:
        p = os.path.join(dest, f)
        os.chmod(p, os.stat(p).st_mode | 0o200)


def run(script, flags, tree):
    r = subprocess.run([sys.executable, script, *flags, '--dir', tree],
                       capture_output=True, text=True)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def check(tree, label, failures):
    for fname, needle, human in MUST_CONTAIN:
        src = open(os.path.join(tree, fname), encoding='utf-8').read()
        if needle not in src:
            failures.append(f"{label}: MISSING  {human}  ({fname} lacks {needle!r})")
    for fname, needle, human in MUST_NOT_CONTAIN:
        src = open(os.path.join(tree, fname), encoding='utf-8').read()
        if needle in src:
            failures.append(f"{label}: BUG SURVIVED  {human}  ({fname} still has {needle!r})")
    for fname in FILES:
        try:
            py_compile.compile(os.path.join(tree, fname), doraise=True)
        except py_compile.PyCompileError as e:
            failures.append(f"{label}: SYNTAX ERROR in {fname}: {e}")


def main():
    failures = []
    preflight()
    root = tempfile.mkdtemp(prefix='janus_order_')
    print(f"scratch: {root}\n")

    orders = [
        ('v1-then-v2', [(V1, V1_FLAGS), (V2, V2_FLAGS)]),
        ('v2-then-v1', [(V2, V2_FLAGS), (V1, V1_FLAGS)]),
    ]

    trees = {}
    for label, steps in orders:
        tree = os.path.join(root, label)
        build_tree(tree)
        trees[label] = tree
        print(f"=== {label} ===")
        for script, flags in steps:
            rc, out = run(script, flags, tree)
            tag = os.path.basename(script)
            if rc != 0:
                failures.append(f"{label}: {tag} {' '.join(flags)} exited {rc}\n{out}")
                print(f"  {tag}: EXIT {rc}")
                continue
            # A "skipping" line on a PRISTINE tree means a sentinel misfired.
            for line in out.splitlines():
                if 'skipping' in line.lower() or 'already applied' in line.lower():
                    failures.append(
                        f"{label}: {tag} reported a skip on a tree where that fix "
                        f"had NOT been applied -> sentinel collision: {line.strip()}")
                    print(f"  {tag}: !! {line.strip()}")
            print(f"  {tag}: ok")
        check(tree, label, failures)
        print()

    # Third pass: re-running both scripts must be a genuine no-op.
    print("=== idempotency: re-run both scripts over v1-then-v2 ===")
    tree = trees['v1-then-v2']
    before = {f: open(os.path.join(tree, f), encoding='utf-8').read() for f in FILES}
    for script, flags in [(V1, V1_FLAGS), (V2, V2_FLAGS)]:
        rc, out = run(script, flags, tree)
        if rc != 0:
            failures.append(f"idempotency: {os.path.basename(script)} exited {rc}\n{out}")
    for f in FILES:
        after = open(os.path.join(tree, f), encoding='utf-8').read()
        if after != before[f]:
            failures.append(f"idempotency: re-run MODIFIED {f} (patch is not idempotent)")
        else:
            print(f"  unchanged  {f}")
    print()

    # Report cosmetic drift for the record, without failing on it.
    print("=== cosmetic drift between orders (expected, not a failure) ===")
    for f in FILES:
        a = open(os.path.join(trees['v1-then-v2'], f), encoding='utf-8').read()
        b = open(os.path.join(trees['v2-then-v1'], f), encoding='utf-8').read()
        if a == b:
            print(f"  byte-identical  {f}")
        else:
            na, nb = len(a.splitlines()), len(b.splitlines())
            same = 'same line count' if na == nb else f'{na} vs {nb} lines'
            print(f"  differs         {f}  ({same} -- ordering only, both verified above)")
    print()

    if failures:
        print("FAILED")
        for x in failures:
            print(f"  - {x}")
        sys.exit(1)
    # Counts derived from the lists, not written out by hand: the previous
    # version of this line said "all 5 fixes, remove all 4 bugs" and was already
    # stale by the time --live-params was added. A summary that can go quietly
    # wrong is the same failure mode this whole test exists to catch.
    print(f"PASSED: both orders apply all {len(MUST_CONTAIN)} fix fingerprints, "
          f"remove all {len(MUST_NOT_CONTAIN)} bug fingerprints across "
          f"{len(FILES)} files, compile, and are idempotent.")


if __name__ == '__main__':
    main()
