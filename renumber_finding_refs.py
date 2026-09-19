"""
renumber_finding_refs.py
========================
Makes every "finding #N" in the repo mean the SAME N -- a changelog item number.

THE DEFECT THIS FIXES (found 2026-08-22 by test_changelog_consistency.py)
    Two numbering schemes were in use with identical syntax:

      * the FIX-FLAG scheme -- `--fix1`, `--fix3`, `--fix5` in apply_fixes.py,
        written in prose as "finding #1", "finding #3", "finding #5"
      * the CHANGELOG scheme -- items 26-41 in ENGINEERING_CHANGELOG.md,
        written in prose as "finding #32", "finding #33", "finding #34"

    16 references used the first scheme (see TOTAL_EXPECTED below, which is
    asserted rather than described) and the majority used the second. Nothing
    marks which is which, so `finding #5` in apply_fixes_v2.py:1083 means the CAGR
    units bug, while changelog item 5 is an unrelated Part A entry. A reader
    following the reference lands on a real item about the wrong thing, and
    that is worse than a dangling reference: a dangling one announces itself.

    WHY IT SURVIVED THIS LONG
        test_changelog_consistency.py TEST 3 checked `finding #N` against the
        changelog and printed "OK ... 'finding #5' exists (no keyword
        registered)". It passed precisely BECAUSE item 5 exists. A check that
        reports success on the input it cannot evaluate is worse than no check;
        it converts an unknown into a green tick. TEST 3 now fails on any
        `finding #N` with N < 26 or with no keyword registered.

THE MAPPING (fix flag -> changelog item), verified against the item headings
    --fix1  Sniper per-stock look-ahead in entry price/stop/size  -> item 26
    --fix3  exits ordered before the allocation rebalance         -> item 27
    --fix5  CAGR annualised with 365.25/days on trading-day count -> item 28

WHY RENUMBER THE PROSE AND NOT THE FLAGS
    The flags are a command-line interface dell has already run. Renaming
    `--fix1` to `--fix26` would invalidate every note and shell history entry
    that used it, to fix a problem that only exists in prose. The flags keep
    their names; the prose stops borrowing their numbers.

    After this runs, "finding #N" has exactly one meaning everywhere, so the
    ambiguity is gone by construction rather than by convention.

IDEMPOTENT
    Re-running is a no-op: the sweep at the end finds no low-numbered
    references and the script exits 0 having written nothing.

A NOTE ON THE COUNTS IN THIS DOCSTRING
    An earlier draft said "15 references used the first scheme and 39 used the
    second". The 15 was wrong -- TOTAL_EXPECTED is 16, and the assertion below
    is what proved it, not a re-reading. The 39 was probably right when it was
    measured, but the renumber moved 16 references INTO the second scheme and
    several files have been added or rewritten since, so it cannot now be
    reconstructed. It is left unstated rather than replaced with a fresh number:
    a count in a docstring is checked by nothing and will drift again. The count
    that matters is asserted in code, just below.

RUN
    python renumber_finding_refs.py --dry-run
    python renumber_finding_refs.py
"""

import argparse
import os
import re
import sys

# fix-flag number -> changelog item number
REMAP = {1: 26, 3: 27, 5: 28}

# Every file expected to contain old-scheme references, and how many. Stated
# explicitly so that a file quietly gaining or losing one is a failure rather
# than a silent difference in the diff.
EXPECTED = {
    'apply_fixes_v2.py': 1,
    'measure_lookahead_bias.py': 6,
    'reset_paper_state.py': 4,          # 3 "finding #N" + 1 bare ", #3 ("
    'test_cagr_units.py': 1,
    'test_lookahead.py': 1,
    'test_window_gap_decomposition.py': 3,
}
# Sum of the above: 15 written as "finding #N" plus the 1 bare
# reference below. (Written as 15 on the first attempt -- the grep that found
# the "finding #N" references by definition could not see the bare one. The
# assertion below caught it, which is the whole reason it is an assertion and
# not a comment.)
TOTAL_EXPECTED = 16

# "finding #1" / "Findings #3" / "FINDING #5" -- case and plural preserved.
PAT = re.compile(r'\b([Ff]indings?|FINDINGS?)(\s+)#(\d+)\b')

# The one bare reference: reset_paper_state.py's REASON string wraps mid-list,
# so "#3" there has no "finding" in front of it and PAT cannot see it. Handled
# as an exact string because a bare "#3" is far too generic to regex safely --
# it would also match a "#33" prefix, a colour literal or a comment marker.
BARE = {
    'reset_paper_state.py': [
        ('"size), #3 (exits ordered before the allocation rebalance), #33 (no "',
         '"size), #27 (exits ordered before the allocation rebalance), #33 (no "'),
    ],
}

# Bullet list in reset_paper_state.py aligns its labels before the "--". The
# single-digit labels ("finding #1", "finding #3") carried two spaces to line up
# with "finding #33"; renumbered to two digits they need one, so the padding is
# corrected here in the same pass. Also renames the unnumbered "idle yield"
# bullet to name its items, since a bullet pointing at nothing is a quieter
# version of the same defect.
#
# (An earlier draft of this comment asserted the alignment "survives the
# renumber untouched". It does not -- "finding #1  " is 12 columns and
# "finding #26  " is 13. Recorded because the wrong version was written with
# the same confidence as the right one, and only looking at the output settled
# it.)
EXTRA = {
    'reset_paper_state.py': [
        # Re-pad the two renumbered bullets: one fewer space now that the label
        # is two digits. Applied AFTER PAT.sub, so these match the renumbered
        # text, not the original.
        ('      * finding #26  -- the 3 Sniper positions',
         '      * finding #26 -- the 3 Sniper positions'),
        ('      * finding #27  -- fills were recorded',
         '      * finding #27 -- fills were recorded'),
        ('      * idle yield  -- accrued at a stated 6%/yr on a /365 basis (a true',
         '      * items 29+36 -- accrued at a stated 6%/yr on a /365 basis (a true'),
    ],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default='.')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    # ---- survey before touching anything -------------------------------
    hits = {}
    for name in sorted(EXPECTED):
        path = os.path.join(args.dir, name)
        if not os.path.exists(path):
            sys.exit(f"ERROR: {name} not found in {args.dir}. Point --dir at "
                     f"the repo rather than renumbering a partial checkout.")
        src = open(path, encoding='utf-8').read()
        n = len([m for m in PAT.finditer(src) if int(m.group(3)) in REMAP])
        n += sum(src.count(o) for o, _ in BARE.get(name, []))
        hits[name] = n

    total = sum(hits.values())
    if total == 0:
        print("No old-scheme references found -- already renumbered. Nothing "
              "to do.")
        return 0

    print("OLD-SCHEME REFERENCES FOUND")
    for name, n in hits.items():
        flag = '' if n == EXPECTED[name] else f"  <-- EXPECTED {EXPECTED[name]}"
        print(f"  {name:36s} {n}{flag}")
    print(f"  {'TOTAL':36s} {total}  (expected {TOTAL_EXPECTED})")

    if hits != EXPECTED or total != TOTAL_EXPECTED:
        sys.exit("\nERROR: the reference counts do not match what this script "
                 "was written against. The files changed since the survey, so "
                 "the remap may not mean what it did then. Re-read the "
                 "references before forcing this through.")
    print()

    # ---- rewrite --------------------------------------------------------
    changed = []
    for name in sorted(EXPECTED):
        path = os.path.join(args.dir, name)
        src = open(path, encoding='utf-8').read()
        before = src

        def sub(m):
            n = int(m.group(3))
            return (f"{m.group(1)}{m.group(2)}#{REMAP[n]}" if n in REMAP
                    else m.group(0))
        src = PAT.sub(sub, src)

        for old, new in BARE.get(name, []) + EXTRA.get(name, []):
            c = src.count(old)
            if c != 1:
                sys.exit(f"ERROR: {name}: expected exactly 1 occurrence of\n"
                         f"  {old!r}\nfound {c}.")
            src = src.replace(old, new)

        if src == before:
            continue
        n_lines = sum(1 for a, b in zip(before.splitlines(), src.splitlines())
                      if a != b)
        print(f"  {name:36s} {n_lines} line(s) rewritten")
        changed.append(name)
        if not args.dry_run:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)

    # ---- sweep: prove no low-numbered reference is left anywhere --------
    print()
    if args.dry_run:
        print("--dry-run: nothing written.")
        return 0

    leftover = []
    for name in sorted(os.listdir(args.dir)):
        if not name.endswith(('.py', '.md')):
            continue
        if name == os.path.basename(__file__):
            continue                      # this file documents the old numbers
        src = open(os.path.join(args.dir, name), encoding='utf-8').read()
        for i, line in enumerate(src.splitlines(), 1):
            for m in PAT.finditer(line):
                if int(m.group(3)) < 26:
                    leftover.append(f"{name}:{i}: {m.group(0)}")
    if leftover:
        print("ERROR: low-numbered 'finding #N' references remain:")
        for s in leftover:
            print("  " + s)
        return 1

    print(f"Renumbered {len(changed)} file(s). Sweep confirms no "
          f"'finding #N' with N < 26 remains in any .py or .md file.")
    print()
    print("VERIFY")
    print("  python test_changelog_consistency.py "
          "--file ENGINEERING_CHANGELOG_updated.md")
    print("  -- TEST 3 should now resolve every reference by keyword, with no")
    print("     'no keyword registered' lines at all.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
