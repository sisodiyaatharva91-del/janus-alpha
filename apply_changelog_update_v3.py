"""
apply_changelog_update_v3.py
============================
Third changelog patch. Adds Part E item 41 and closes two gaps in the record
that item 41 is itself about.

WHY A THIRD SCRIPT AND NOT AN EDIT TO v2
    Same reasoning as v2-vs-v1, and it has now held twice. `apply_changelog_
    update_v2.py`'s sentinel is item 32's heading, so it no-ops on an
    already-patched file; its anchors target text that item 41 rewrites; and it
    is the record of what the SECOND pass found. Editing it would make that
    record claim the second pass knew about a defect it did not find -- the
    numbering collision was found afterwards, by the test written to check the
    second pass's own output. v1 and v2 are left byte-for-byte alone.

WHAT ITEM 41 IS
    Two numbering schemes shared one syntax. `finding #5` meant `--fix5` (the
    CAGR units bug = item 28) while changelog item 5 is an unrelated Part A
    entry, so the reference resolved to a real item about the wrong thing.
    16 references used the retired scheme. Fixed by renumber_finding_refs.py.

    The part worth recording is not the collision, it is why it survived:
    `test_changelog_consistency.py` TEST 3 printed "OK ... 'finding #5' exists
    (no keyword registered)". It passed BECAUSE item 5 exists. The check had no
    keyword for 5, could not evaluate the reference, and reported OK anyway.

WHAT ELSE THIS FIXES
    * The inventory advertised 19 second-pass files but omitted two that exist
      (`renumber_finding_refs.py`, `test_changelog_consistency.py`). A file
      inventory that silently omits files is the same defect class as an item
      reference that silently resolves wrong.
    * `apply_lookahead_patch.py` (superseded standalone draft of `--fix1`) was
      deleted. It shared the sentinel `'DECISION TIMING (see section 5b)'` with
      `apply_fixes.py --fix1`, so running it first made `--fix1` no-op and left
      one stale comment line. Verified comment-only: stripping comment lines
      from both outputs gives byte-identical files. Recorded because the
      sentinel-collision class already bit once (item 38).

RUN
    python apply_changelog_update_v3.py --file ENGINEERING_CHANGELOG_updated.md
"""

import argparse
import os
import sys

SENTINEL = '41. **AUDIT TOOLING / RECORD KEEPING — two numbering schemes'
PREREQ = '40. **AUDIT TOOLING — the first draft of the item 32 measurement'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', default='ENGINEERING_CHANGELOG_updated.md')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    if not os.path.exists(args.file):
        sys.exit(f"ERROR: {args.file} not found.")
    text = open(args.file, encoding='utf-8').read()

    if SENTINEL in text:
        print("Already patched (item 41 present) -- nothing to do.")
        return 0
    if PREREQ not in text:
        sys.exit("ERROR: item 40 not found. This patch builds on the second "
                 "pass; run apply_changelog_update_v2.py first.")

    edits = 0

    def sub(old, new, label):
        nonlocal text, edits
        c = text.count(old)
        if c != 1:
            sys.exit(f"ERROR [{label}]: expected 1 occurrence, found {c}.\n"
                     f"  anchor: {old[:78]!r}")
        text = text.replace(old, new)
        edits += 1
        print(f"  [{edits}] {label}")

    # ---- 1. section heading -------------------------------------------
    sub('### 2026-08-22 (second pass) — EXECUTION-MODEL AUDIT (items 32-40)',
        '### 2026-08-22 (second pass) — EXECUTION-MODEL AUDIT (items 32-41)',
        'second-pass section heading -> items 32-41')

    # ---- 2. section preamble ------------------------------------------
    sub('Items 32-37 are defects in the traded system. Items 38-40 are defects in the\n'
        'audit tooling built to check it — recorded at equal weight on purpose, because',
        'Items 32-37 are defects in the traded system. Items 38-41 are defects in the\n'
        'audit tooling built to check it, and in this record itself (41) — recorded at\n'
        'equal weight on purpose, because',
        'section preamble -> tooling items 38-41')

    # ---- 3. top warning: the breakdown --------------------------------
    # Anchor spans all five wrapped lines. The counts and the item list have to
    # move together or the arithmetic stops closing, and an earlier pass shipped
    # a breakdown that did not add up (9 + 5 = 14 against a stated 15), so this
    # is replaced wholesale rather than line by line.
    sub('> The audit ran in two passes. Items 26-40 break down as **ten defects in the\n'
        '> traded system** (26, 27, 28, 29, 32, 33, 34, 35, 36, 37), **three in the\n'
        '> audit tooling** built to check it (38, 39, 40), one operational consequence\n'
        '> that needed a decision from you (30), and one deferred documentation fix\n'
        '> (31). If you read only one, read **34**: it is a selection defect in the',
        '> The audit ran in two passes. Items 26-41 break down as **ten defects in the\n'
        '> traded system** (26, 27, 28, 29, 32, 33, 34, 35, 36, 37), **four in the\n'
        '> audit tooling** built to check it and in this record (38, 39, 40, 41), one\n'
        '> operational consequence that needed a decision from you (30), and one\n'
        '> deferred documentation fix (31). That is 16 items and 14 defects: 10 + 4 +\n'
        '> 1 + 1. If you read only one, read **34**: it is a selection defect in the',
        'top warning -> 16 items / 14 defects, arithmetic shown')

    # ---- 4. top warning: the fixed-and-verified count -----------------
    sub('> All thirteen defects are fixed and unit-verified.',
        '> All fourteen defects are fixed and unit-verified.',
        'top warning -> fourteen defects fixed')

    # ---- 5. inventory sub-heading -------------------------------------
    sub('Added by the second pass (items 32-40):',
        'Added by the second pass (items 32-41):',
        'inventory sub-heading -> items 32-41')

    # ---- 6. inventory: the two omitted files --------------------------
    # Inserted before the RUNBOOK entry so the list ends with the deliverable,
    # as it did before.
    sub('- `RUNBOOK_2026-08-22.md` — the ordered apply/re-run/redeploy path with the',
        '- `test_changelog_consistency.py` — asserts that the changelog\'s item\n'
        '  numbers and the scripts\' references to them agree, by keyword and not\n'
        '  merely by existence (item 41)\n'
        '- `renumber_finding_refs.py` — one-shot rename of the retired fix-flag\n'
        '  numbering in prose, so "finding #N" has a single meaning (item 41)\n'
        '- `apply_changelog_update_v3.py` — applies this changelog update (item 41)\n'
        '- `RUNBOOK_2026-08-22.md` — the ordered apply/re-run/redeploy path with the',
        'inventory -> add the two omitted files, and this script')

    # ---- 7. item 36: mark -0.15pp as an upper bound ---------------------
    # Found while verifying the runbook's arithmetic, after item 41 was
    # written. -0.1484pp is the change in GROSS CASH YIELD, which only reaches
    # CAGR in full if capital sits 100% in cash for the whole period. Since the
    # sleeves are partly invested it is an upper bound, and the changelog stated
    # it as if it were the expected value. Same defect class as the rest of this
    # patch: a number in prose that nothing checks.
    sub('    Which is the useful thing about this bug: the corrected 4% is worth almost\n'
        '    exactly what the broken 6% was actually paying, so the headline effect of\n'
        '    items 29+36 together is small (about −0.15pp on CAGR) even though the\n'
        '    parameter moved by a third. A number that changed by 2 and an outcome that\n'
        '    changed by 0.15 is the signature of a units bug, and it is why "we lowered\n'
        '    the yield assumption from 6% to 4%" would be an actively misleading\n'
        '    description of this change.',
        '    Which is the useful thing about this bug: the corrected 4% is worth almost\n'
        '    exactly what the broken 6% was actually paying, so the headline effect of\n'
        '    items 29+36 together is small — an effective **4.2291%/yr becomes\n'
        '    4.0807%**, a change of **−0.1484pp of gross cash yield** — even though the\n'
        '    parameter moved by a third. A parameter that changed by 2 and an outcome\n'
        '    that changed by a seventh of a point is the signature of a units bug, and\n'
        '    it is why "we lowered the yield assumption from 6% to 4%" would be an\n'
        '    actively misleading description of this change.\n'
        '\n'
        '    **−0.1484pp is an upper bound on the CAGR effect, not the expected\n'
        '    value.** Yield accrues only on *uninvested* sleeve cash, so the full\n'
        '    figure lands only if capital sits 100% in cash throughout. With the\n'
        '    sleeves partly invested the realised drag is smaller, scaled by the\n'
        '    average cash fraction — which the re-run reports and which has not been\n'
        '    measured here. Called out because the earlier wording ("about −0.15pp on\n'
        '    CAGR") gave a bound the authority of a forecast.',
        'item 36 -> -0.15pp marked as an upper bound, with the compounded figures')

    # ---- 8. item 41 ----------------------------------------------------
    ITEM_41 = '''
41. **AUDIT TOOLING / RECORD KEEPING — two numbering schemes shared one
    syntax, so a cross-reference could resolve to a real item about the wrong
    thing. Fixed.** Found 2026-08-22 by `test_changelog_consistency.py`, which
    is also the reason it survived as long as it did.

    Two schemes were in use, both written `#N`:

    - the **fix-flag** scheme — `--fix1`, `--fix3`, `--fix5` in
      `apply_fixes.py`, written in prose as "finding #1/#3/#5"
    - the **changelog** scheme — Part E items 26-41, written in prose as
      "finding #32/#33/#34"

    16 references used the first. `apply_fixes_v2.py` carried
    `<- finding #5` next to the CAGR formula, meaning `--fix5`, i.e. **item
    28** — but changelog item 5 exists, in Part A, about something else
    entirely. A reader following that reference lands on a real entry and has
    no signal that it is the wrong one. **That is worse than a dangling
    reference: a dangling reference announces itself.**

    Fixed by `renumber_finding_refs.py`: fix1 → 26, fix3 → 27, fix5 → 28,
    applied to 16 references across 6 files, with per-file expected counts
    asserted before anything is written and a closing sweep that proves no
    reference below 26 remains. The **flags keep their names** — `--fix1` is a
    command line already run and recorded in shell history; renaming it to fix
    a problem that exists only in prose would invalidate notes to no purpose.
    Verified by re-running from a pristine snapshot: byte-identical result, and
    a second run is a clean no-op.

    **WHY THE TEST DID NOT CATCH IT SOONER — the part worth keeping.** TEST 3
    checked each `finding #N` against the changelog and printed, as a pass:

    ```
    OK   apply_fixes_v2.py: 'finding #5' exists (no keyword registered)
    ```

    It reported OK *because item 5 exists*. It had no keyword for 5, could not
    evaluate whether the reference pointed at the right thing, and returned
    green anyway. **A check that reports success on the input it cannot assess
    is worse than no check — it converts an unknown into a tick.** TEST 3 now
    fails on any reference with no keyword registered or with a number below 26
    (all real audit findings are Part E items, so a low number is the retired
    scheme leaking back in). The two files that legitimately *quote* the old
    scheme are allowed to, per file and per number, rather than by exempting
    the whole file — a blanket exemption would stop checking their valid
    references too, which is the same trade that produced the false OK.

    Two further gaps closed in the same pass, both the same class of defect —
    a record that omits something without saying so:

    - **The file inventory omitted two files that exist**
      (`test_changelog_consistency.py`, `renumber_finding_refs.py`). TEST 4 now
      checks the inventory in **both** directions: every file the build claims
      to have added must exist, and every `.py` in the directory must be
      listed. Pre-existing repo files are reported but not asserted, since the
      changelog can legitimately be read from a partial checkout.
    - **`apply_lookahead_patch.py` deleted.** A superseded standalone draft of
      `--fix1`, referenced by nothing, that wrote the **same sentinel**
      (`'DECISION TIMING (see section 5b)'`) as `apply_fixes.py --fix1`.
      Running it first made `--fix1` silently no-op and left one stale comment
      line. Verified comment-only — stripping comment lines from both outputs
      gives byte-identical files — so no behaviour was at risk, but the
      sentinel-collision class already bit once in item 38 and a second live
      instance of it is not worth keeping on disk.

    A note on all three of items 38-41 and on the two counting errors the top
    warning now shows arithmetic for: every one was a defect in **my own
    output**, and every one biased toward making the audit look tidier than it
    was. What caught them was checking each claim against a source instead of
    re-reading the prose — counting the item list, asking which file a bug is
    actually in, diffing the scripts' help text against the changelog
    headings. Re-reading is not verification.
'''
    sub('\n#### Measurements taken during the second pass, for the record',
        ITEM_41 + '\n#### Measurements taken during the second pass, for the record',
        'insert item 41')

    if args.dry_run:
        print(f"\n--dry-run: {edits} edits resolved, nothing written.")
        return 0

    with open(args.file, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f"\nWrote {args.file} ({edits} edits, "
          f"{len(text.splitlines())} lines).")
    print()
    print("VERIFY")
    print("  python test_changelog_consistency.py "
          "--file ENGINEERING_CHANGELOG_updated.md")
    print()
    print("DELIBERATELY NOT CHANGED")
    print("  * apply_changelog_update.py and _v2.py -- byte-for-byte untouched.")
    print("    Each is the record of what its own pass found; item 41 was found")
    print("    after both, by the test written to check the second one.")
    print("  * Item 31 (SETUP_GUIDE.md §4 path text) stays OPEN.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
