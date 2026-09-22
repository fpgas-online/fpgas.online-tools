# SPDX-License-Identifier: Apache-2.0
"""fleet-sheet: diff board records against the tracking sheet, and apply what a person accepts.

    fleet-sheet diff  RECORD...            show what the sheet would need to change (writes nothing)
    fleet-sheet apply RECORD... [--yes]    show it, ask, write exactly that, then re-read and re-check

RECORD is a bring-up JSON file or a directory of them. The sheet is never
written without this command being run by a person; there is no daemon mode
and there will not be one.
"""

import argparse
import sys

from . import records, sheet_io, sheetmap

TABS = {
    "acorn": "Acorn/LiteFury/NiteFury",
    "arty": "Arty Boards",
    "netv2": "NeTV2",
}


def build_parser():
    p = argparse.ArgumentParser(
        prog="fleet-sheet", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--key", default=sheet_io.DEFAULT_KEY, help="service-account key file (default: %(default)s)")
    p.add_argument(
        "--tab", default="acorn", help="tab name or alias: " + ", ".join(f"{k}={v!r}" for k, v in TABS.items())
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("diff", help="propose changes; write nothing")
    d.add_argument("records", nargs="+")
    a = sub.add_parser("apply", help="propose, confirm, write, verify")
    a.add_argument("records", nargs="+")
    a.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt (you are still the human in the loop)"
    )
    return p


def propose(sheet, tab, recs):
    header, rows = sheet.read(tab)
    return header, sheetmap.compute_updates(recs, header, rows)


def main(argv=None):
    args = build_parser().parse_args(argv)
    tab = TABS.get(args.tab, args.tab)
    recs = records.load(args.records)
    sheet = sheet_io.Sheet(args.key)
    title, tabs = sheet.tabs()
    if tab not in tabs:
        sys.exit(f"no tab {tab!r} in {title!r}; tabs: {sorted(tabs)}")
    print(f"{title!r} / {tab!r} as {sheet.account}; {len(recs)} record(s)")
    header, result = propose(sheet, tab, recs)
    print(sheetmap.render(result))
    if args.cmd == "diff" or (not result.updates and not result.new_rows):
        return 1 if result.conflicts else 0

    if not args.yes:
        answer = input(f"write {len(result.updates)} cell(s) and {len(result.new_rows)} new row(s)? [yes/NO] ")
        if answer.strip().lower() != "yes":
            print("nothing written")
            return 2
    added = sheet.ensure_columns(tab, len(result.header))
    if added:
        print(f"grew the tab by {added} column(s)")
    n = sheet.write(tab, sheet_io.header_writes(header, result.header, tab) + sheet_io.plan_writes(result, tab))
    m = sheet.append_rows(tab, result.new_rows)
    print(f"wrote {n} cell(s), appended {m} row(s)")

    _, again = propose(sheet, tab, recs)
    if again.updates or again.new_rows:
        print("VERIFY FAILED: the sheet still differs after writing:")
        print(sheetmap.render(again))
        return 3
    print(
        "verified: sheet now agrees with the records"
        + (" (conflicts above remain for a person)" if again.conflicts else "")
    )
    return 1 if again.conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
