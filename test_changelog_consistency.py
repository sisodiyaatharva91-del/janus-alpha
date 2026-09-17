"""
test_changelog_consistency.py
-----------------------------
Checks that the changelog's item numbers and the code's references to them
still agree.

WHY THIS EXISTS
    On 2026-08-22 the second-pass changelog was written with items numbered
    33 = VIX_Spike and 34 = duplicate-run guard, while `apply_fixes_v2.py`'s
    own `--help` said `--run-guard` was "finding #33" and `--live-params` was
    "finding #34". Both documents were internally coherent and they disagreed
    with each other, so someone reading `--live-params  finding #34` would look
    up item 34 and find a defect about `VIX_Spike`. Nothing would crash; the
    record would just quietly mislead, which is the failure mode a changelog
    exists to prevent.

    Caught by eye. That is not a control, so this is the control: the numbering
    is now asserted, and inserting a new item in the middle without updating
    the scripts fails here.

WHY THE FIRST VERSION OF THIS TEST DID NOT CATCH item 41
    It printed, and counted as a pass:

        OK   apply_fixes_v2.py: 'finding #5' exists (no keyword registered)

    `finding #5` meant `--fix5` (the CAGR units bug, changelog item 28), but
    changelog item 5 is an unrelated Part A entry, so the reference resolved to
    a real item about the wrong thing. The check reported OK *because* item 5
    exists -- it had no keyword for 5, could not evaluate the claim, and said
    OK anyway. A check that returns green on the input it cannot assess is
    worse than no check: it converts an unknown into a tick.

    So TEST 3 now FAILS on any reference it cannot evaluate -- no keyword
    registered, or a number below 26. All real audit findings are Part E items
    26+, so a low number is by definition the old fix-flag scheme leaking back
    in (see renumber_finding_refs.py).

  Test 1 : items 26-41 each appear exactly once as a heading, in order.
  Test 2 : every "item N" reference inside the changelog points at an item
           that exists.
  Test 3 : each `finding #N` in the scripts lands on a changelog item about
           the same thing (keyword match, so a renumber cannot pass), and
           every reference is evaluatable.
  Test 4 : every file the changelog says THIS BUILD added exists on disk.
           Pre-existing repo files are reported but not asserted -- the
           changelog can legitimately be read from a partial checkout.

RUN
    python test_changelog_consistency.py
    python test_changelog_consistency.py --file ENGINEERING_CHANGELOG_updated.md
"""

import argparse
import os
import re
import sys

ap = argparse.ArgumentParser()
ap.add_argument('--dir', default='.')
ap.add_argument('--file', default='ENGINEERING_CHANGELOG.md')
args = ap.parse_args()

PATH = os.path.join(args.dir, args.file)
if not os.path.exists(PATH):
    sys.exit(f"ERROR: {PATH} not found.")
text = open(PATH, encoding='utf-8').read()

FIRST_ITEM, LAST_ITEM = 26, 41

failures = []


def check(cond, msg):
    print(f"  {'OK  ' if cond else 'FAIL'} {msg}")
    if not cond:
        failures.append(msg)


# Heading = "NN. **<bold title>**". The title WRAPS: item 29's begins with
# 'RESOLVED (dell's decision...' on line 1 and carries the substantive words
# ("accrued idle yield and live accrued none") onto line 2. Capturing only the
# first line made three keyword checks fail against a changelog that was
# correct, which is the mirror image of the false OK above -- a check wrong in
# the safe direction is still a check that cannot be trusted to mean what it
# says. So capture to the closing '**', across lines, and flatten whitespace.
# Bounded at 400 chars so an unbalanced '**' cannot swallow the rest of the
# file and silently make every keyword match.
HEADINGS = {int(m.group(1)): ' '.join(m.group(2).split())
            for m in re.finditer(r'^(\d+)\. \*\*(.{0,400}?)\*\*',
                                 text, re.M | re.S)}

# ======================================================================
print("=" * 74)
print(f"TEST 1 -- items {FIRST_ITEM}-{LAST_ITEM} appear exactly once each, in order")
print("=" * 74)
nums = [int(m.group(1)) for m in re.finditer(r'^(\d+)\. \*\*', text, re.M)]
part_e = [n for n in nums if n >= FIRST_ITEM]
check(part_e == sorted(part_e), f"Part E items are in ascending order: {part_e}")
check(len(part_e) == len(set(part_e)),
      f"no duplicate item numbers (got {len(part_e)}, {len(set(part_e))} distinct)")
expected = list(range(FIRST_ITEM, LAST_ITEM + 1))
missing = [n for n in expected if n not in HEADINGS]
check(not missing,
      f"items {FIRST_ITEM}-{LAST_ITEM} all present (missing: {missing or 'none'})")
# The multi-line capture is itself worth asserting: if the regex silently
# stopped matching, every keyword check below would fail confusingly rather
# than pointing here.
short = sorted(n for n in expected if n in HEADINGS and len(HEADINGS[n]) < 20)
check(not short,
      f"every item title captured non-trivially (suspiciously short: {short or 'none'})")
print()


# ======================================================================
print("=" * 74)
print("TEST 2 -- every 'item N' reference points at an item that exists")
print("=" * 74)
refs = set()
for m in re.finditer(r'\b[Ii]tems?\s+#?((?:\d+)(?:\s*(?:,|and|-|\+|to)\s*#?\d+)*)', text):
    for n in re.findall(r'\d+', m.group(1)):
        refs.add(int(n))
# Items 1-25 live in Parts A-D under their own numbering; only check Part E.
dangling = sorted(n for n in refs if FIRST_ITEM <= n <= 60 and n not in HEADINGS)
check(not dangling,
      f"no dangling Part E references (dangling: {dangling or 'none'}); "
      f"checked {len([n for n in refs if n >= FIRST_ITEM])} distinct")
print()


# ======================================================================
print("=" * 74)
print("TEST 3 -- 'finding #N' in the scripts matches the changelog item")
print("=" * 74)
print("  Keyword match, not just existence: a renumber that leaves the scripts")
print("  pointing at a real-but-wrong item is the exact bug this catches.")
print("  A reference this test cannot evaluate is a FAILURE, not an OK.\n")

# One distinctive word per finding, chosen to survive rewording of the title.
KEYWORDS = {
    26: 'LOOK-AHEAD', 27: 'rebalance', 28: 'CAGR', 29: 'idle yield',
    32: 'MACRO-GATE', 33: 're-processing', 34: 'generate_live_params',
    35: 'VIX_Spike', 36: 'IDLE-YIELD UNITS', 37: 'JSON-safety',
    38: 'fix5', 39: 'harness', 40: 'measurement', 41: 'numbering',
}

# Two files QUOTE the retired scheme in order to document it: the script that
# renamed it, and this test's own docstring explaining the false OK. Both must
# be allowed to say "finding #5" while nothing else may.
#
# Allowed per FILE and per NUMBER rather than by exempting the whole file: both
# files also carry legitimate #33/#34 references, and a blanket exemption would
# stop checking those -- buying a clean run by narrowing what is looked at,
# which is the same trade that produced the false OK in the first place.
OLD_SCHEME_QUOTES = {
    'renumber_finding_refs.py': {1, 3, 5},
    'test_changelog_consistency.py': {1, 5},
    'apply_changelog_update_v3.py': {1, 5},
}

SCRIPTS = sorted(f for f in os.listdir(args.dir) if f.endswith('.py'))
found_any = 0
quoted = 0
for script in SCRIPTS:
    src = open(os.path.join(args.dir, script), encoding='utf-8').read()
    for n in sorted({int(m.group(1)) for m in
                     re.finditer(r'[Ff][Ii][Nn][Dd][Ii][Nn][Gg][Ss]?\s+#(\d+)', src)}):
        if n < FIRST_ITEM and n in OLD_SCHEME_QUOTES.get(script, set()):
            quoted += 1
            continue
        found_any += 1
        if n < FIRST_ITEM:
            check(False, f"{script}: 'finding #{n}' uses the retired fix-flag "
                         f"numbering -- run renumber_finding_refs.py (item 41)")
            continue
        if n not in HEADINGS:
            check(False, f"{script}: 'finding #{n}' -- no such changelog item")
            continue
        kw = KEYWORDS.get(n)
        if kw is None:
            check(False, f"{script}: 'finding #{n}' -- item exists but NO KEYWORD "
                         f"registered, so this reference is unverified. Add one to "
                         f"KEYWORDS rather than trusting it")
            continue
        check(kw.lower() in HEADINGS[n].lower(),
              f"{script}: 'finding #{n}' -> item {n} mentions {kw!r}  "
              f"[{HEADINGS[n][:44]}...]")
check(found_any > 0,
      f"'finding #N' references were found to check (got {found_any})")
print(f"  --   {quoted} retired-scheme reference(s) allowed as documentation "
      f"quotes, per OLD_SCHEME_QUOTES")
print()


# ======================================================================
print("=" * 74)
print("TEST 4 -- every file THIS BUILD added exists")
print("=" * 74)
print("  Split deliberately. A file this build claims to have added and did not")
print("  is a changelog advertising something that does not exist. A")
print("  pre-existing repo file missing from this directory just means a")
print("  partial checkout, which is not a defect in the record.\n")

m = re.search(r'^## Files in this build\n(.*?)^---', text, re.S | re.M)
check(m is not None, "the 'Files in this build' section was located")
if m:
    section = m.group(1)
    FILE_RE = r'`([A-Za-z0-9_./-]+\.(?:py|md|json|parquet))`'

    # The trailing sub-section is what this build added; everything above it is
    # pre-existing or from the first pass.
    split = re.search(r'^Added by the second pass \(items [\d-]+\):$',
                      section, re.M)
    check(split is not None, "the 'Added by the second pass' sub-section was located")
    added = sorted(set(re.findall(FILE_RE, section[split.end():]))) if split else []
    earlier = sorted(set(re.findall(FILE_RE, section[:split.start()]))) if split else []

    absent_added = [f for f in added
                    if not os.path.exists(os.path.join(args.dir, f))]
    check(not absent_added,
          f"all {len(added)} second-pass files exist "
          f"(absent: {absent_added or 'none'})")

    absent_earlier = [f for f in earlier
                      if not os.path.exists(os.path.join(args.dir, f))]
    print(f"  --   {len(earlier) - len(absent_earlier)}/{len(earlier)} "
          f"pre-existing files present (informational)")
    if absent_earlier:
        print(f"       not in this directory: {absent_earlier}")

    # The converse gap: a file this build added that the inventory never lists.
    # How renumber_finding_refs.py and this very test went unlisted.
    on_disk = {f for f in os.listdir(args.dir) if f.endswith('.py')}
    listed = set(added) | set(earlier)
    unlisted = sorted(on_disk - listed)
    check(not unlisted,
          f"no build file is missing from the inventory "
          f"(unlisted: {unlisted or 'none'})")
print()


# ======================================================================
print("=" * 74)
if failures:
    print(f"FAILED -- {len(failures)} check(s):")
    for f in failures:
        print("  - " + f)
    print("=" * 74)
    sys.exit(1)
print("CHANGELOG CONSISTENCY OK")
print("  Item numbering is contiguous and unique, every cross-reference")
print("  resolves, every 'finding #N' label was EVALUATED (not assumed) and")
print("  lands on the item it names, and the file inventory and the directory")
print("  agree in both directions.")
print("=" * 74)
